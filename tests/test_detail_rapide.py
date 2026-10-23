"""« Mes vidéos » : panneau de détail construit une fois puis rempli, liste
recolorée au lieu d'être reconstruite (repris de PodAdmin 1.13.0).

Avant, chaque clic détruisait et recréait la liste et le panneau : de 1,3 à
4,7 s par clic sur 40 vidéos (mesuré le 2026-10-23). Les commandes du
panneau doivent lire la vidéo affichée AU MOMENT DU CLIC.
"""
import pytest

B = "https://exemple.invalid/rest"


def _widgets(widget):
    for enfant in widget.winfo_children():
        yield enfant
        yield from _widgets(enfant)


def _bouton(app, debut):
    import customtkinter as ctk
    for w in _widgets(app.myvids_detail):
        if isinstance(w, ctk.CTkButton) and str(w.cget("text")).startswith(debut):
            return w
    raise AssertionError(f"bouton « {debut} » absent")


class _API:
    def __init__(self):
        self.pistes = {}
        self.patchs = []

    def get_tracks(self, v):
        return self.pistes.get(v["slug"], [])

    def patch_video(self, v, payload):
        self.patchs.append((v["slug"], dict(payload)))


@pytest.fixture
def mes_videos(app):
    sauvegarde = {n: app.__dict__.get(n) for n in ("_myvids_current_owner", "api", "_run")}
    app._myvids_current_owner = lambda: (f"{B}/users/42/", "abc1234d")
    app.api = _API()
    app._run = lambda fn, *x: fn(*x)
    app.type_map = {"Cours": f"{B}/types/1/", "Conférence": f"{B}/types/2/"}
    app.myvids_videos = [
        {"slug": "v0", "title": "Premier", "is_draft": True, "type": f"{B}/types/1/",
         "owner": f"{B}/users/42/", "channel": []},
        {"slug": "v1", "title": "Second", "is_draft": False, "is_restricted": True,
         "type": f"{B}/types/2/", "owner": f"{B}/users/42/", "channel": []},
        {"slug": "v2", "title": "Troisième", "is_draft": False,
         "owner": f"{B}/users/42/", "channel": []},
    ]
    app.myvids_filtered = list(app.myvids_videos)
    app.myvids_multi, app.myvids_selected = [], None
    app._render_myvids_list()
    app._myvids_render_detail()
    app.update()
    yield app
    app.myvids_multi, app.myvids_selected = [], None
    for nom, valeur in sauvegarde.items():
        if valeur is None:
            app.__dict__.pop(nom, None)
        else:
            app.__dict__[nom] = valeur


def _choisir(app, i):
    app._myvids_select(app.myvids_videos[i])
    app.update()


class TestPanneauConstruitUneFois:

    def test_les_widgets_ne_sont_pas_recrees(self, mes_videos):
        """Hors la liste des sous-titres, recréée exprès pour chaque vidéo."""
        app = mes_videos

        def hors_sous_titres():
            pistes = set(map(id, _widgets(app.myvids_subs)))
            return {id(w) for w in _widgets(app.myvids_detail)} - pistes

        _choisir(app, 0)
        avant = hors_sous_titres()
        _choisir(app, 1)
        assert hors_sous_titres() == avant

    def test_valeurs_de_la_nouvelle_video(self, mes_videos):
        app = mes_videos
        _choisir(app, 0)
        _choisir(app, 1)
        d = app._myvids_detail_w
        assert d["titre"].cget("text") == "Second"
        assert app.myvids_title_entry.get() == "Second"
        assert d["statut"].get() == "Restreint"
        assert d["type"].get() == "Conférence"

    def test_les_commandes_visent_la_video_affichee(self, mes_videos):
        """Le bouton Renommer, créé pendant l'affichage de v0, doit renommer v1."""
        app = mes_videos
        _choisir(app, 0)
        _choisir(app, 1)
        app.myvids_title_entry.delete(0, "end")
        app.myvids_title_entry.insert(0, "Second renommé")
        _bouton(app, "Renommer").invoke()
        assert app.api.patchs == [("v1", {"title": "Second renommé"})]

    def test_statut_applique_a_la_video_affichee(self, mes_videos):
        app = mes_videos
        _choisir(app, 0)
        _choisir(app, 2)
        # CTkSegmentedButton n'a pas d'invoke() : on appelle sa commande.
        app._myvids_detail_w["statut"]._command("Brouillon")
        assert app.api.patchs[-1] == ("v2", {"is_draft": True, "is_restricted": False})

    def test_reconstruit_apres_le_panneau_de_lot(self, mes_videos):
        """Le panneau de lot vide le cadre : la vidéo suivante doit retrouver
        un panneau de détail complet et à ses valeurs."""
        app = mes_videos
        _choisir(app, 0)
        app._myvids_toggle_multi(app.myvids_videos[1])
        app.update()
        _choisir(app, 2)
        assert app._myvids_detail_w["titre"].winfo_exists()
        assert app._myvids_detail_w["titre"].cget("text") == "Troisième"
        _bouton(app, "Renommer")


class TestMessagesEtSousTitres:

    def test_le_message_reste_affiche_apres_une_modification(self, mes_videos):
        app = mes_videos
        _choisir(app, 0)
        app._do_myvids_patch(app.myvids_videos[0], {"title": "Neuf"}, "titre → Neuf")
        app.update()
        assert app.myvids_msg.cget("text") == "✅  titre → Neuf"

    def test_le_message_s_efface_en_changeant_de_video(self, mes_videos):
        app = mes_videos
        _choisir(app, 0)
        app._myvids_set_msg("✅  fait", "green")
        _choisir(app, 1)
        assert app.myvids_msg.cget("text") == ""

    def test_sous_titres_d_une_video_quittee_ignores(self, mes_videos):
        app = mes_videos
        _choisir(app, 1)
        app._myvids_sub_render(app.myvids_videos[0], [{"lang": "fr", "kind": "subtitles"}])
        app.update()
        textes = [str(w.cget("text")) for w in _widgets(app.myvids_subs)
                  if "text" in w.keys()]
        assert not any("·" in t for t in textes), textes

    def test_sous_titres_de_la_video_affichee(self, mes_videos):
        app = mes_videos
        app.api.pistes["v1"] = [{"lang": "fr", "kind": "subtitles"}]
        _choisir(app, 1)
        textes = [str(w.cget("text")) for w in _widgets(app.myvids_subs)
                  if "text" in w.keys()]
        assert any("·" in t for t in textes), textes


class TestListeRecoloree:

    def test_un_clic_ne_reconstruit_pas_la_liste(self, mes_videos):
        app = mes_videos
        avant = {s: id(l[0]) for s, l in app._myvids_lignes.items()}
        _choisir(app, 1)
        _choisir(app, 2)
        assert {s: id(l[0]) for s, l in app._myvids_lignes.items()} == avant

    def test_teintes_apres_clics(self, mes_videos):
        import app as module_app
        app = mes_videos
        _choisir(app, 0)
        _choisir(app, 2)
        couleurs = {s: l[0].cget("fg_color") for s, l in app._myvids_lignes.items()}
        assert couleurs["v2"] == ("gray75", "gray30")
        assert couleurs["v0"] == "transparent"
        app._myvids_toggle_multi(app.myvids_videos[1])
        app.update()
        couleurs = {s: l[0].cget("fg_color") for s, l in app._myvids_lignes.items()}
        assert couleurs["v1"] == couleurs["v2"] == module_app.C_MULTI

    def test_repli_si_la_liste_a_disparu(self, mes_videos):
        app = mes_videos
        for w in app.myvids_list.winfo_children():
            w.destroy()
        _choisir(app, 1)
        assert app._myvids_lignes and all(b.winfo_exists() for b, _c in app._myvids_lignes.values())
