"""Vérification de mise à jour — portée depuis PodAdmin.

Le dispositif a deux moitiés, qui doivent rester cohérentes : l'application qui
CONSULTE `version.json`, et le workflow qui le PUBLIE. Une divergence entre les
deux ne produit aucune erreur — seulement un bandeau qui n'apparaît jamais, ou
qui apparaît en permanence.
"""
import os
import re

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lire(nom):
    return open(os.path.join(RACINE, nom), encoding="utf-8").read()


class TestSourceUniqueDeVersion:
    """⚠️ La version était définie dans l'en-tête de CHAQUE fichier. Lors de la
    publication 2.1.0, elle a été changée dans `config.py` mais pas dans
    `app.py`, qui fait foi : l'application se serait crue éternellement en
    2.0.0, et aurait signalé en permanence une mise à jour… vers elle-même."""

    def test_l_application_lit_la_source_unique(self):
        import __version__ as v

        import app as module_app
        assert module_app.APP_VERSION == v.__version__, (
            f"l'application annonce {module_app.APP_VERSION} au lieu de "
            f"{v.__version__}")

    def test_app_et_config_n_ont_plus_leur_propre_numero(self):
        for nom in ("app.py", "config.py"):
            assert not re.search(r'^__version__\s*=\s*"', _lire(nom), re.M), (
                f"{nom} redéfinit sa propre version : elle divergera")

    def test_version_txt_concorde(self):
        """Métadonnées de l'exécutable Windows : il ne peut pas importer de
        Python, d'où ce contrôle."""
        import __version__ as v
        texte = _lire("version.txt")
        assert f"u'{v.__version__}'" in texte, (
            f"version.txt ne mentionne pas {v.__version__}")
        attendu = ", ".join(str(x) for x in v.VERSION_TUPLE)
        assert f"({attendu})" in texte, (
            f"filevers/prodvers ne valent pas ({attendu})")


class TestVerification:
    """L'application consulte le fichier publié, sans jamais se bloquer."""

    def test_l_adresse_pointe_le_depot_public(self):
        """Le dépôt du code est PRIVÉ : un enseignant n'y a pas accès."""
        import config as cfg
        assert "podteleverseur-releases" in cfg.UPDATE_URL
        assert cfg.UPDATE_URL.endswith("/version.json")

    def test_la_comparaison_est_numerique(self):
        """« 2.10.0 » est plus récent que « 2.9.0 » : une comparaison
        alphabétique conclurait l'inverse."""
        import maj
        assert maj.comparer_versions("2.10.0", "2.9.0") > 0
        assert maj.comparer_versions("2.1.0", "2.2.0") < 0
        assert maj.comparer_versions("2.2.0", "2.2.0") == 0

    def test_un_reseau_absent_ne_bloque_rien(self):
        """La vérification ne doit JAMAIS empêcher de travailler."""
        import maj
        info = maj.etat_mise_a_jour("2.2.0", "https://exemple.invalid/v.json",
                                    timeout=1)
        assert info is None


class TestBandeau:
    """⚠️ Un conteneur vide réservé d'avance se dessinait en CARRÉ NOIR sur
    macOS. Le bandeau est donc créé de toutes pièces à la détection."""

    def test_aucun_bandeau_au_repos(self, app):
        assert app.maj_bandeau is None

    def test_affichage_et_remplacement(self, app):
        app._afficher_bandeau_maj({"version": "9.9.9",
                                   "url": "https://exemple.invalid",
                                   "notes": "Test.", "urgent": False})
        app.update()
        premier = app.maj_bandeau
        assert premier.winfo_ismapped() and premier.winfo_height() > 1
        # Une seconde détection ne doit pas empiler deux bandeaux.
        app._afficher_bandeau_maj({"version": "9.9.9", "urgent": True})
        app.update()
        assert not premier.winfo_exists(), "l'ancien bandeau n'a pas été détruit"

    def test_le_bouton_telecharger_a_sa_methode(self):
        """Le bandeau appelle `_ouvrir_lien_maj` : sans elle, le clic sur
        « Télécharger » lèverait une erreur."""
        import app as module_app
        assert hasattr(module_app.App, "_ouvrir_lien_maj")


class TestWorkflowDePublication:
    """Les deux moitiés du dispositif doivent concorder."""

    def _workflow(self):
        return _lire(".github/workflows/build.yml")

    def test_la_version_est_lue_dans_le_code(self):
        assert "__version__.py" in self._workflow(), (
            "le workflow ne lit pas la version dans le code")

    def test_publication_sur_le_depot_public(self):
        w = self._workflow()
        assert "podteleverseur-releases" in w
        assert "secrets.RELEASES_TOKEN" in w

    def test_version_json_est_publie(self):
        assert "cp version.json public/version.json" in self._workflow()

    def test_les_fichiers_publies_sont_bien_produits(self):
        """Piège rencontré dans PodAdmin : un fichier publié mais jamais
        produit fait échouer la Release à la toute dernière étape."""
        w = self._workflow()
        attendus = set()
        for bloc in w.split("uses: actions/upload-artifact")[1:]:
            nom = re.search(r"name:\s*([\w.-]+)", bloc)
            chemin = re.search(r"path:\s*([^\s]+)", bloc)
            if nom and chemin:
                attendus.add(f"{nom.group(1)}/"
                             f"{os.path.basename(chemin.group(1).rstrip('/'))}")
        bloc = w[w.index("files: |"):]
        bloc = bloc[:bloc.index("\n\n")]
        publies = {l.strip() for l in bloc.split("\n")[1:] if l.strip()}
        assert not (publies - attendus), (
            f"publiés mais jamais produits : {sorted(publies - attendus)}")
