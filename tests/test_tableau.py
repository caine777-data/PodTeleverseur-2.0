"""« Mes vidéos » en tableau natif et filtres en pastilles (3.5.0, repris de
PodAdmin 1.12 et 1.13).

Tableau : toutes les lignes (plus de plafond), colonnes statut, titre, rôle,
date et encodage, tri par les en-têtes, clic, Ctrl+clic, Maj+clic, flèches.
Pastilles : neutres au repos, actives en bleu, compteur « n sur N » et lien
« Effacer les filtres ».
"""
import types

import pytest

B = "https://exemple.invalid/rest"
MOI, COLLEGUE = f"{B}/users/42/", f"{B}/users/7/"


@pytest.fixture
def mes_videos(app, monkeypatch):
    sauvegarde = {n: app.__dict__.get(n) for n in ("_myvids_current_owner", "api", "_run")}

    class _API:
        def get_tracks(self, v):
            return []

    app._myvids_current_owner = lambda: (MOI, "abc1234d")
    app.api = _API()
    app._run = lambda fn, *x: fn(*x)
    app.type_map = {"Cours": f"{B}/types/1/", "Conférence": f"{B}/types/2/"}
    app.myvids_videos = [
        {"slug": "a", "title": "Bêta", "is_draft": True, "owner": MOI, "channel": [],
         "date_added": "2026-10-14T09:00:00", "encoded": True, "type": f"{B}/types/1/"},
        {"slug": "b", "title": "alpha", "is_draft": False, "is_restricted": True, "owner": MOI,
         "channel": [], "date_added": "2026-09-02", "encoded": False, "encoding_in_progress": False,
         "type": f"{B}/types/2/"},
        {"slug": "c", "title": "Gamma", "is_draft": False, "owner": COLLEGUE,
         "additional_owners": [MOI], "channel": [], "date_added": "2026-01-20", "encoded": True,
         "type": f"{B}/types/1/"},
    ]
    app._myvids_tri = "Plus récentes"
    app.myvids_multi, app.myvids_selected = [], None
    app._myvids_effacer_filtres()
    app.update()
    yield app
    app._myvids_effacer_filtres()
    app.myvids_multi, app.myvids_selected = [], None
    app.myvids_videos, app.myvids_filtered = [], []
    app._myvids_tri = "Plus récentes"
    for nom, valeur in sauvegarde.items():
        if valeur is None:
            app.__dict__.pop(nom, None)
        else:
            app.__dict__[nom] = valeur


def _lignes(app):
    return list(app.myvids_tree.get_children())


def _clic(app, slug, modificateur=None, region="cell"):
    """Clic simulé sur une ligne : identify_row/region remplacés, la
    géométrie réelle du tableau n'étant pas garantie dans les tests."""
    arbre = app.myvids_tree
    vrai_row, vrai_region = arbre.identify_row, arbre.identify_region
    arbre.identify_row = lambda y: slug
    arbre.identify_region = lambda x, y: region
    try:
        return app._myvids_clic_ligne(types.SimpleNamespace(x=5, y=5), modificateur)
    finally:
        arbre.identify_row, arbre.identify_region = vrai_row, vrai_region


class TestContenu:

    def test_une_ligne_par_video_dans_l_ordre_de_pod(self, mes_videos):
        assert _lignes(mes_videos) == ["a", "b", "c"]

    def test_valeurs_des_colonnes(self, mes_videos):
        arbre = mes_videos.myvids_tree
        assert arbre.item("a", "values") == ("📝", "Bêta", "", "14/10/2026", "oui")
        assert arbre.item("b", "values") == ("🔒", "alpha", "", "02/09/2026", "non")
        assert arbre.item("c", "values") == ("🌐", "Gamma", "👥", "20/01/2026", "oui")

    def test_plus_de_plafond_a_300_lignes(self, mes_videos):
        app = mes_videos
        app.myvids_videos = [{"slug": f"v{i}", "title": f"V{i}", "owner": MOI, "channel": []}
                             for i in range(450)]
        app._myvids_apply_filter()
        assert len(_lignes(app)) == 450


class TestSelection:

    def test_clic_simple_ouvre_la_video(self, mes_videos):
        app = mes_videos
        assert _clic(app, "b") == "break"
        assert app.myvids_selected["slug"] == "b"
        assert app.myvids_tree.item("b", "tags") == ("courante",)

    def test_ctrl_et_maj(self, mes_videos):
        app = mes_videos
        _clic(app, "a")
        _clic(app, "c", "ctrl")
        assert app.myvids_multi == ["a", "c"]
        app.myvids_multi = []
        _clic(app, "a")
        _clic(app, "c", "maj")
        assert app.myvids_multi == ["a", "b", "c"]
        assert {app.myvids_tree.item(s, "tags")[0] for s in "abc"} == {"multi"}

    def test_clic_d_en_tete_laisse_au_tri(self, mes_videos):
        app = mes_videos
        assert _clic(app, "", region="heading") is None
        assert app.myvids_selected is None

    def test_fleches(self, mes_videos):
        app = mes_videos
        app._myvids_deplacer(1)                 # aucune vidéo ouverte : la première
        assert app.myvids_selected["slug"] == "a"
        app._myvids_deplacer(1)
        assert app.myvids_selected["slug"] == "b"
        app._myvids_deplacer(-1)
        app._myvids_deplacer(-1)                # bute sur la première ligne
        assert app.myvids_selected["slug"] == "a"


class TestTri:

    def test_titre_puis_inverse(self, mes_videos):
        app = mes_videos
        app._myvids_trier_par("titre")
        assert _lignes(app) == ["b", "a", "c"]          # alpha, Bêta, Gamma (sans casse)
        assert app.myvids_tree.heading("titre", "text") == "Titre  ▲"
        app._myvids_trier_par("titre")
        assert _lignes(app) == ["c", "a", "b"]
        assert app.myvids_tree.heading("titre", "text") == "Titre  ▼"

    def test_date(self, mes_videos):
        app = mes_videos
        assert app.myvids_tree.heading("date", "text") == "Ajoutée le  ▼"
        app._myvids_trier_par("date")
        assert _lignes(app) == ["c", "b", "a"]
        assert app.myvids_tree.heading("date", "text") == "Ajoutée le  ▲"

    def test_colonnes_sans_tri(self, mes_videos):
        app = mes_videos
        for col in ("statut", "role", "enc"):
            app._myvids_trier_par(col)
        assert app._myvids_tri == "Plus récentes"


class TestPastilles:

    def test_au_repos(self, mes_videos):
        app = mes_videos
        assert app.myvids_statut.cget("text") == "Statut  ▾"
        assert not app.myvids_statut.est_active()
        assert app.myvids_count_lbl.cget("text") == "3 vidéo(s)."
        assert not app.myvids_effacer_btn.winfo_manager()

    def test_filtre_actif(self, mes_videos):
        import tableau
        app = mes_videos
        app.myvids_type._choisir("Cours")
        assert app.myvids_type.cget("text") == "Type : Cours  ✕"
        assert app.myvids_type.cget("fg_color") == tableau.C_FILTRE_ACTIF
        assert _lignes(app) == ["a", "c"]
        assert app.myvids_count_lbl.cget("text") == "2 vidéo(s) sur 3  ·  1 filtre actif"
        assert app.myvids_effacer_btn.winfo_manager()

    def test_la_croix_retire_le_filtre(self, mes_videos):
        app = mes_videos
        app.myvids_type._choisir("Cours")
        app.myvids_type.effacer()
        assert not app.myvids_type.est_active()
        assert _lignes(app) == ["a", "b", "c"]

    def test_effacer_les_filtres(self, mes_videos):
        app = mes_videos
        app.myvids_text.insert(0, "a")
        app.myvids_statut.set("Public")
        app.myvids_role.set("Co-propriétaire")
        app._myvids_apply_filter()
        app._myvids_effacer_filtres()
        assert app.myvids_text.get() == ""
        assert not any(p.est_active() for p in app.myvids_pastilles.elements)
        assert _lignes(app) == ["a", "b", "c"]

    @pytest.mark.parametrize("role, attendus", [
        ("Propriétaire", ["a", "b"]), ("Co-propriétaire", ["c"]),
    ])
    def test_role(self, mes_videos, role, attendus):
        app = mes_videos
        app.myvids_role._choisir(role)
        assert _lignes(app) == attendus

    def test_valeurs_rechargees(self, mes_videos):
        """configure(values=…) garde un choix encore valable, sinon revient au neutre."""
        p = mes_videos.myvids_chan
        p.configure(values=["Toutes chaînes", "Biologie", "Écologie"])
        p.set("Biologie")
        p.configure(values=["Toutes chaînes", "Biologie"])
        assert p.get() == "Biologie"
        p.configure(values=["Toutes chaînes", "Écologie"])
        assert p.get() == "Toutes chaînes" and not p.est_active()


class TestEtatVide:

    def test_aucun_resultat_puis_retour(self, mes_videos):
        app = mes_videos
        app.myvids_text.insert(0, "introuvable")
        app._myvids_apply_filter()
        assert not app._myvids_cadre_arbre.winfo_manager()
        assert app._myvids_vide_widgets
        app._myvids_effacer_filtres()
        assert app._myvids_cadre_arbre.winfo_manager()
        assert not app._myvids_vide_widgets


class TestTheme:

    def test_les_teintes_suivent_le_mode(self, mes_videos, monkeypatch):
        import customtkinter as ctk

        import app as module_app
        app = mes_videos
        monkeypatch.setattr(module_app.cfg, "save_theme", lambda *_: None)
        mode = ctk.get_appearance_mode()
        avant = app.myvids_tree.tag_configure("alt", "background")
        try:
            app._basculer_theme()
            assert app.myvids_tree.tag_configure("alt", "background") != avant
        finally:
            ctk.set_appearance_mode(mode)
            module_app.styler_tableaux(app)


class TestRangeeFluide:

    def test_passe_a_la_ligne(self, mes_videos, monkeypatch):
        rangee = mes_videos.myvids_pastilles
        monkeypatch.setattr(rangee, "winfo_width", lambda: 200)
        rangee.reorganiser()
        assert rangee.nombre_de_lignes() >= 2
        monkeypatch.setattr(rangee, "winfo_width", lambda: 5000)
        rangee.reorganiser()
        assert rangee.nombre_de_lignes() == 1
