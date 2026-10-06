"""Panneau de sélection multiple de « Mes vidéos » : même présentation que
PodAdmin, sans « Restreindre au groupe… » ni zone de suppression.
"""
import pytest

B = "https://exemple.invalid/rest"


def _widgets(widget):
    for enfant in widget.winfo_children():
        yield enfant
        yield from _widgets(enfant)


def _textes(widget):
    trouves = []
    for w in _widgets(widget):
        try:
            trouves.append(str(w.cget("text")))
        except Exception:
            pass
    return trouves


def _bouton(app, debut):
    import customtkinter as ctk
    for w in _widgets(app.myvids_detail):
        if isinstance(w, ctk.CTkButton) and str(w.cget("text")).startswith(debut):
            return w
    raise AssertionError(f"bouton « {debut} » absent")


@pytest.fixture
def lot(app, monkeypatch):
    sauvegarde = {n: app.__dict__.get(n) for n in ("_myvids_current_owner", "api", "_run")}
    app._myvids_current_owner = lambda: (f"{B}/users/42/", "marie")
    app.myvids_videos = [{"slug": f"v{i}", "title": f"Titre {i}", "owner": f"{B}/users/42/",
                          "is_draft": False, "channel": []} for i in range(4)]
    app.myvids_filtered = list(app.myvids_videos)
    app.myvids_multi, app.myvids_selected = ["v0", "v1", "v2"], None
    app._myvids_lot_actif = False
    app.myvids_lot_interrompu.clear()
    app._run = lambda fn, *x: fn(*x)
    app._myvids_render_detail()
    app.update()
    yield app
    app.myvids_multi, app.myvids_selected = [], None
    app._myvids_lot_actif = False
    app.myvids_lot_interrompu.clear()
    for nom, valeur in sauvegarde.items():
        if valeur is None:
            app.__dict__.pop(nom, None)
        else:
            app.__dict__[nom] = valeur


class TestPresentation:

    def test_en_tete_et_liste_des_videos_concernees(self, lot):
        textes = _textes(lot.myvids_detail)
        assert "☑  3 vidéos sélectionnées" in textes
        for t in ("• Titre 0", "• Titre 1", "• Titre 2"):
            assert t in textes
        assert "• Titre 3" not in textes

    def test_boutons_dans_l_ordre_de_podadmin(self, lot):
        attendus = ["📝  Mettre en brouillon", "🌐  Rendre public", "🔒  Rendre restreint",
                    "📺  Affecter à une chaîne…", "Appliquer le type à 3 vidéos",
                    "🏷️  Disciplines…", "🛑  Interrompre le traitement",
                    "✖  Annuler la sélection"]
        textes = _textes(lot.myvids_detail)
        positions = [textes.index(t) for t in attendus]
        assert positions == sorted(positions), textes

    def test_teintes_de_podadmin(self, lot):
        import app as module_app
        assert _bouton(lot, "🌐").cget("fg_color") == module_app.COULEURS_LOT["public"] \
            == ("#15803d", "#15803d")
        assert _bouton(lot, "🔒").cget("fg_color") == ("#b45309", "#b45309")
        assert _bouton(lot, "📺").cget("fg_color") == ("#2563eb", "#2563eb")

    def test_ni_groupes_ni_suppression(self, lot):
        textes = " ".join(_textes(lot.myvids_detail)).lower()
        assert "groupe" not in textes
        assert "supprimer" not in textes and "zone sensible" not in textes

    def test_interrompre_desactive_au_repos(self, lot):
        assert _bouton(lot, "🛑").cget("state") == "disabled"

    def test_annuler_la_selection(self, lot):
        _bouton(lot, "✖").invoke()
        assert lot.myvids_multi == []


class TestActions:

    @pytest.mark.parametrize("emoji, attendu", [
        ("📝", {"is_draft": True, "is_restricted": False}),
        ("🌐", {"is_draft": False, "is_restricted": False}),
        ("🔒", {"is_draft": False, "is_restricted": True}),
    ])
    def test_chaque_statut_envoie_les_deux_booleens(self, lot, monkeypatch, emoji, attendu):
        import app as module_app
        envois = []

        class _API:
            def patch_video(self, v, p):
                envois.append((v["slug"], dict(p)))
        lot.api = _API()
        monkeypatch.setattr(module_app.messagebox, "askyesno", lambda *x, **k: True)
        _bouton(lot, emoji).invoke()
        assert envois == [(s, attendu) for s in ("v0", "v1", "v2")]

    def test_refus_de_confirmation_n_envoie_rien(self, lot, monkeypatch):
        import app as module_app
        envois = []

        class _API:
            def patch_video(self, v, p):
                envois.append(v)
        lot.api = _API()
        monkeypatch.setattr(module_app.messagebox, "askyesno", lambda *x, **k: False)
        _bouton(lot, "📝").invoke()
        assert envois == []


class TestInterruption:

    def test_arret_entre_deux_videos(self, lot):
        """La vidéo en cours est terminée ; les suivantes ne sont pas traitées."""
        faites = []

        def action(v):
            faites.append(v["slug"])
            if v["slug"] == "v1":
                lot._myvids_lot_interrompre()
        lot._myvids_lancer_lot(lot._myvids_lot(), action, lambda v: None, "test")
        lot.update()
        assert faites == ["v0", "v1"]
        assert not lot._myvids_lot_actif, "le lot reste marqué en cours"
        assert "interrompu" in str(lot.myvids_msg.cget("text"))

    def test_bouton_actif_pendant_le_lot(self, lot):
        etats = []
        lot._myvids_lancer_lot(lot._myvids_lot(),
                               lambda v: etats.append(lot.myvids_stop_btn.cget("state")),
                               lambda v: None, "test")
        assert etats and all(e == "normal" for e in etats)

    def test_un_seul_lot_a_la_fois(self, lot):
        lot._myvids_lot_actif = True
        lances = []
        lot._myvids_lancer_lot(lot._myvids_lot(), lances.append, lambda v: None, "test")
        assert lances == []
        assert "déjà en cours" in str(lot.myvids_msg.cget("text"))

    def test_nouveau_lot_repart_apres_une_interruption(self, lot):
        lot.myvids_lot_interrompu.set()
        faites = []
        lot._myvids_lancer_lot(lot._myvids_lot(), lambda v: faites.append(v["slug"]),
                               lambda v: None, "test")
        assert faites == ["v0", "v1", "v2"]
