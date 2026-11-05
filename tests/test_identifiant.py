"""Tests : propriétaire des vidéos désigné par son identifiant.

Le propriétaire n'est plus choisi dans l'annuaire de tous les comptes : il est
SAISI, puis retrouvé EXACTEMENT sur la plateforme. Depuis la 3.6.0, un compte
LOCAL est accepté comme un identifiant universitaire (ex. abc1234a) ; seul le
compte véhicule (DEPOT) reste refusé. Les co-propriétaires, eux, gardent la
liste complète.

Chaque test a été éprouvé par mutation. Aucun réseau : API simulée. Rien
n'est écrit dans la vraie configuration du poste (save_config neutralisé).
"""
import pytest

import config
from pod_api import PodAPI, PodAPIError


# ── Format ─────────────────────────────────────────────────────────────────

class TestFormat:
    """Plus de format imposé (3.6.0) : universitaire ou local, tout nom sans
    espace est cherché sur la plateforme. Le compte véhicule est écarté."""

    @pytest.mark.parametrize("ident", [
        "abc1234a", "ABC1234A", "  abc1234a  ",
        "Jean.Dupont", "prof.dupont", "aaa_aaaa", "abc1234", "local-42"])
    def test_identifiants_acceptes(self, module_app, ident):
        assert module_app.App._identifiant_valide(ident)

    @pytest.mark.parametrize("ident", [
        "DEPOT", "depot", "  Depot ", "abc 1234a", "jean\tdupont", "", "   ", None])
    def test_identifiants_refuses(self, module_app, ident):
        assert not module_app.App._identifiant_valide(ident)

    def test_la_casse_est_gardee(self, module_app):
        """Un compte local peut contenir des majuscules : on ne les efface pas."""
        assert module_app.App._normaliser_identifiant(" Jean.Dupont ") == "Jean.Dupont"

    def test_le_compte_vehicule_n_est_jamais_un_identifiant(self, module_app):
        """Garantie de sécurité : aucun dépôt ne peut être attribué à DEPOT."""
        assert not module_app.App._identifiant_valide(config.VEHICLE_USERNAME)


@pytest.fixture
def module_app():
    try:
        import app as m
    except Exception as e:                        # pas d'affichage disponible
        pytest.skip(f"interface indisponible : {e}")
    return m


# ── Recherche exacte côté API ──────────────────────────────────────────────

class Rep:
    def __init__(self, donnees, status=200):
        import json
        self.status_code, self._d = status, donnees
        self.text = json.dumps(donnees)
        self.url = "https://pod.exemple.fr/rest/users/"

    def json(self):
        return self._d


class SessionUsers:
    """Faux /rest/users/ : `reponse(params)` décide de ce que renvoie le serveur."""

    def __init__(self, reponse):
        self.reponse = reponse
        self.appels = []
        self.headers = {}

    def get(self, url, params=None, **k):
        self.appels.append(dict(params or {}))
        return Rep(self.reponse(params or {}))


ANNUAIRE = [{"username": n, "url": f"https://pod.exemple.fr/rest/users/{i}/"}
            for i, n in enumerate(["xyz9876a", "xyz9876ab", "xxyz9876a", "DEPOT",
                                   "abc1234a"], 1)]


def _api(reponse):
    api = PodAPI("https://pod.exemple.fr", "jeton")
    api.session = SessionUsers(reponse)
    return api


class TestRechercheExacte:

    def test_utilise_le_filtre_username_pas_la_recherche(self):
        api = _api(lambda p: {"results": [u for u in ANNUAIRE
                                          if u["username"] == p.get("username")]})
        assert api.find_user_by_username("xyz9876a")["url"].endswith("/users/1/")
        (params,) = api.session.appels
        assert params.get("username") == "xyz9876a" and "search" not in params

    def test_serveur_qui_ignore_le_filtre(self):
        """Si le serveur renvoyait tout l'annuaire, le 1er résultat ne serait
        pas le bon compte : l'égalité exacte est vérifiée côté client."""
        api = _api(lambda p: {"count": len(ANNUAIRE), "results": ANNUAIRE})
        assert api.find_user_by_username("ABC1234A")["username"] == "abc1234a"

    def test_recherche_approchante_refusee(self):
        # Le serveur répond par des comptes qui CONTIENNENT l'identifiant.
        api = _api(lambda p: {"results": [ANNUAIRE[1], ANNUAIRE[2]]})
        assert api.find_user_by_username("xyz9876a") is None

    def test_deux_comptes_exacts_ambigu(self):
        api = _api(lambda p: {"results": [ANNUAIRE[0], dict(ANNUAIRE[0], url="x")]})
        assert api.find_user_by_username("xyz9876a") is None

    def test_compte_local_avec_majuscules(self):
        """`?username=` distingue la casse : le nom est d'abord demandé tel
        que saisi, sinon « Jean.Dupont » ne serait jamais trouvé."""
        local = {"username": "Jean.Dupont", "url": "https://pod.exemple.fr/rest/users/9/"}
        api = _api(lambda p: {"results": [local] if p.get("username") == "Jean.Dupont" else []})
        assert api.find_user_by_username(" Jean.Dupont ") == local
        assert [a["username"] for a in api.session.appels] == ["Jean.Dupont"]

    def test_repli_en_minuscules(self):
        """Saisi en majuscules, un identifiant universitaire (en minuscules sur
        Pod) est retrouvé par la seconde requête."""
        api = _api(lambda p: {"results": [u for u in ANNUAIRE
                                          if u["username"] == p.get("username")]})
        assert api.find_user_by_username("ABC1234A")["username"] == "abc1234a"
        assert [a["username"] for a in api.session.appels] == ["ABC1234A", "abc1234a"]

    def test_identifiant_vide_aucune_requete(self):
        api = _api(lambda p: {"results": ANNUAIRE})
        assert api.find_user_by_username("  ") is None
        assert api.session.appels == []


# ── Résolution dans l'application ──────────────────────────────────────────

class _Rien:
    def __getattr__(self, nom):
        return _Rien()

    def __call__(self, *a, **k):
        return _Rien()


class FausseAPI:
    def __init__(self, comptes=(), erreur=None):
        self.comptes = {c["username"]: c for c in comptes}
        self.erreur = erreur
        self.recherches = []

    def find_user_by_username(self, ident):
        """Comme le vrai : égalité exacte, casse ignorée."""
        self.recherches.append(ident)
        if self.erreur:
            raise self.erreur
        return next((c for n, c in self.comptes.items() if n.lower() == ident.lower()), None)


def _faux(m, api):
    f = _Rien()
    f.__dict__.update(api=api, all_users=[])
    f._normaliser_identifiant = m.App._normaliser_identifiant
    f._identifiant_valide = m.App._identifiant_valide
    f._est_compte_vehicule = m.App._est_compte_vehicule
    f._compte_dans_annuaire = m.App._compte_dans_annuaire.__get__(f)
    f._resoudre_identifiant = m.App._resoudre_identifiant.__get__(f)
    return f


PROF = {"username": "abc1234a", "url": "https://pod.exemple.fr/rest/users/8/"}
LOCAL = {"username": "Jean.Dupont", "url": "https://pod.exemple.fr/rest/users/9/"}


class TestResolution:

    def test_compte_trouve(self, module_app):
        f = _faux(module_app, FausseAPI([PROF]))
        assert f._resoudre_identifiant(" ABC1234A ") == (PROF, "")
        assert f.api.recherches == ["ABC1234A"]

    def test_compte_local_trouve(self, module_app):
        f = _faux(module_app, FausseAPI([LOCAL]))
        assert f._resoudre_identifiant("Jean.Dupont") == (LOCAL, "")

    def test_compte_vehicule_refuse_sans_appel_reseau(self, module_app):
        f = _faux(module_app, FausseAPI([PROF, {"username": "DEPOT", "url": "u"}]))
        compte, message = f._resoudre_identifiant("depot")
        assert compte is None and "compte de service" in message
        assert f.api.recherches == []

    @pytest.mark.parametrize("ident, indice", [("", "Saisissez"), ("jean dupont", "espace")])
    def test_saisie_impossible_sans_appel_reseau(self, module_app, ident, indice):
        f = _faux(module_app, FausseAPI([PROF]))
        compte, message = f._resoudre_identifiant(ident)
        assert compte is None and indice in message
        assert f.api.recherches == []

    def test_trouve_dans_l_annuaire_si_le_serveur_ne_trouve_pas(self, module_app):
        """Filet : un compte local absent du filtre serveur, mais présent dans
        la liste des comptes chargée au premier lancement."""
        f = _faux(module_app, FausseAPI([]))
        f.all_users = [PROF, LOCAL]
        assert f._resoudre_identifiant("jean.dupont") == (LOCAL, "")

    def test_annuaire_ambigu_refuse(self, module_app):
        f = _faux(module_app, FausseAPI([]))
        f.all_users = [LOCAL, dict(LOCAL, url="https://pod.exemple.fr/rest/users/10/")]
        compte, message = f._resoudre_identifiant("Jean.Dupont")
        assert compte is None and "Aucun compte" in message

    def test_compte_inconnu(self, module_app):
        f = _faux(module_app, FausseAPI([]))
        compte, message = f._resoudre_identifiant("abc1234d")
        assert compte is None and "Aucun compte" in message and "abc1234d" in message

    def test_erreur_reseau_expliquee(self, module_app):
        f = _faux(module_app, FausseAPI(erreur=PodAPIError("HTTP 503", status=503)))
        compte, message = f._resoudre_identifiant("abc1234d")
        assert compte is None and message.startswith("Recherche impossible")

    def test_non_connecte(self, module_app):
        f = _faux(module_app, None)
        compte, message = f._resoudre_identifiant("abc1234d")
        assert compte is None and "Connectez-vous" in message


class TestGardeFouAuLancement:
    """Un propriétaire enregistré par une version antérieure peut être le
    compte véhicule (DEPOT) : l'envoi est refusé et l'identifiant redemandé.
    Un compte local, lui, est accepté (3.6.0)."""

    def _lancer(self, m, username):
        f = _faux(m, object())
        f.__dict__.update(items=[object()], lancements=[], demandes=[],
                          config_data={"agent_username": username,
                                       "agent_owner_url": "https://pod.exemple.fr/rest/users/1/"})
        f._choose_upload_owner = lambda: f.demandes.append(1)
        f._run = lambda *a: f.lancements.append(a)
        f._depot_debut = lambda: None
        f.type_map = {"Capsule": "https://pod.exemple.fr/rest/types/1/"}
        f.type_combo = type("C", (), {"get": lambda self: "Capsule"})()
        m.App._start_upload(f)
        return f

    def test_compte_local_refuse(self, module_app):
        f = self._lancer(module_app, "DEPOT")
        assert f.demandes == [1] and f.lancements == []

    def test_identifiant_valide_lance(self, module_app):
        f = self._lancer(module_app, "abc1234a")
        assert f.demandes == [] and len(f.lancements) == 1

    def test_compte_local_lance(self, module_app):
        f = self._lancer(module_app, "Jean.Dupont")
        assert f.demandes == [] and len(f.lancements) == 1


# ── Fenêtres réelles (une seule instance App pour le module) ───────────────

@pytest.fixture
def fen(app, monkeypatch, module_app):
    """Fenêtre réelle, exécution synchrone, API simulée, config intouchée."""
    monkeypatch.setattr(module_app.cfg, "save_config", lambda *a, **k: None)
    # Exécution synchrone, et chaque tâche de fond est comptée : un format
    # invalide doit être refusé SUR PLACE, sans lancer de recherche.
    app.taches = []
    monkeypatch.setattr(app, "_run", lambda fn, *a: app.taches.append(fn) or fn(*a))
    monkeypatch.setattr(app, "_ui", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(app, "api", FausseAPI([PROF]))
    monkeypatch.setattr(app, "config_data", dict(app.config_data))
    monkeypatch.setattr(app, "_refresh_owner_status", lambda: None)
    return app


class TestFenetreDeSaisie:

    def test_compte_vehicule_reste_ouverte(self, fen, module_app):
        trouves = []
        d = module_app.IdentifiantDialog(fen, on_found=trouves.append)
        try:
            d.entry.insert(0, "DEPOT")
            d._valider()
            assert trouves == [] and d.winfo_exists()
            assert "compte de service" in d.msg.cget("text")
            assert fen.api.recherches == []
            assert fen.taches == []                  # refusé sans tâche de fond
        finally:
            d.destroy()

    def test_identifiant_valide_ferme_et_transmet(self, fen, module_app):
        trouves = []
        d = module_app.IdentifiantDialog(fen, on_found=trouves.append)
        d.entry.insert(0, "ABC1234A")
        d._valider()
        assert trouves == [PROF]
        assert not d.winfo_exists()

    def test_compte_local_ferme_et_transmet(self, fen, module_app, monkeypatch):
        monkeypatch.setattr(fen, "api", FausseAPI([LOCAL]))
        trouves = []
        d = module_app.IdentifiantDialog(fen, on_found=trouves.append)
        d.entry.insert(0, "Jean.Dupont")
        d._valider()
        assert trouves == [LOCAL]
        assert not d.winfo_exists()

    def test_compte_inconnu_reste_ouverte(self, fen, module_app):
        trouves = []
        d = module_app.IdentifiantDialog(fen, on_found=trouves.append)
        try:
            d.entry.insert(0, "abc1234d")
            d._valider()
            assert trouves == [] and "Aucun compte" in d.msg.cget("text")
            assert d.btn.cget("state") == "normal"      # on peut corriger et revalider
        finally:
            d.destroy()


class TestOngletConfiguration:

    def test_plus_d_annuaire_dans_la_configuration(self, fen):
        """L'ancienne liste de tous les comptes a disparu de l'onglet."""
        assert not hasattr(fen, "agent_results") and not hasattr(fen, "agent_filter")

    def test_validation_enregistre_le_proprietaire(self, fen):
        fen.agent_entry.delete(0, "end")
        fen.agent_entry.insert(0, "abc1234a")
        fen._valider_identifiant_config()
        assert fen.config_data["agent_owner_url"] == PROF["url"]
        assert fen.config_data["agent_username"] == "abc1234a"
        assert "✅" in fen.agent_msg.cget("text")

    def test_compte_local_accepte(self, fen, monkeypatch):
        monkeypatch.setattr(fen, "api", FausseAPI([LOCAL]))
        fen.agent_entry.delete(0, "end")
        fen.agent_entry.insert(0, "Jean.Dupont")
        fen._valider_identifiant_config()
        assert fen.config_data["agent_username"] == "Jean.Dupont"
        assert "✅" in fen.agent_msg.cget("text")

    def test_compte_vehicule_refuse(self, fen):
        avant = dict(fen.config_data)
        fen.agent_entry.delete(0, "end")
        fen.agent_entry.insert(0, "DEPOT")
        fen._valider_identifiant_config()
        assert fen.config_data == avant
        assert "❌" in fen.agent_msg.cget("text")
        assert fen.taches == []                      # refusé sans tâche de fond
