"""« Mes vidéos » ne permet plus de supprimer une vidéo (décision du 28/09/2026).

Une suppression est définitive (aucune corbeille sur Pod). Le Téléverseur ne
la propose plus, ni pour une vidéo ni en sélection multiple, et n'en a plus
le moyen technique : aucune méthode de suppression de vidéo dans PodAPI.
L'aide et les tutoriels n'en parlent pas.

Chaque test a été éprouvé par mutation (bouton ou méthode réintroduits).
"""
import ast
import os
import re

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOMS_INTERDITS = {"delete_video", "_myvids_delete", "_do_myvids_delete",
                  "_myvids_lot_supprimer"}


def _textes(widget):
    """Tous les textes affichés sous `widget` (libellés et boutons)."""
    trouves = []
    for enfant in widget.winfo_children():
        try:
            trouves.append(str(enfant.cget("text")))
        except Exception:
            pass
        trouves.extend(_textes(enfant))
    return trouves


# ── Aucun moyen technique ──────────────────────────────────────────────────

class TestAucunMoyenDeSupprimer:

    def test_pod_api_sans_suppression_de_video(self):
        from pod_api import PodAPI
        assert not hasattr(PodAPI, "delete_video")

    def test_aucune_definition_ni_appel_dans_le_code(self):
        """Analyse de l'arbre syntaxique (pas du texte) : un commentaire qui
        nomme delete_video ne compte pas, un appel ou une définition si."""
        trouves = []
        for nom_fichier in os.listdir(RACINE):
            if not nom_fichier.endswith(".py"):
                continue
            with open(os.path.join(RACINE, nom_fichier), encoding="utf-8") as f:
                arbre = ast.parse(f.read())
            for n in ast.walk(arbre):
                nom = (n.name if isinstance(n, ast.FunctionDef)
                       else n.attr if isinstance(n, ast.Attribute) else None)
                if nom in NOMS_INTERDITS:
                    trouves.append(f"{nom_fichier}:{n.lineno} {nom}")
        assert not trouves, trouves

    def test_la_suppression_des_sous_titres_reste(self):
        """Seules les VIDÉOS sont concernées : retirer une piste de sous-titres
        reste possible."""
        from pod_api import PodAPI
        assert hasattr(PodAPI, "delete_track")


# ── Aucun bouton (vraie fenêtre, fixture `app` du conftest) ────────────────

class TestAucunBoutonDeSuppression:
    B = "https://exemple.invalid/rest"

    @pytest.fixture
    def mes_videos(self, app, monkeypatch):
        """Trois vidéos du compte affiché, dont une en co-propriété."""
        moi = f"{self.B}/users/42/"
        monkeypatch.setattr(app, "_myvids_current_owner", lambda: (moi, "abc1234d"))
        monkeypatch.setattr(app, "_run", lambda *a, **k: None)   # pas de sous-titres
        app.myvids_videos = [
            {"slug": "v0", "title": "V0", "owner": moi, "is_draft": True, "channel": []},
            {"slug": "v1", "title": "V1", "owner": moi, "is_draft": False, "channel": []},
            {"slug": "co", "title": "Partagée", "owner": f"{self.B}/users/7/",
             "additional_owners": [moi], "is_draft": False, "channel": []}]
        app.myvids_filtered = list(app.myvids_videos)
        yield app
        app.myvids_multi, app.myvids_selected = [], None
        app.myvids_videos, app.myvids_filtered = [], []

    @staticmethod
    def _aucune_suppression(textes):
        suspects = [t for t in textes if re.search(r"supprim|zone sensible", t, re.I)]
        assert not suspects, suspects

    def test_panneau_d_une_video_qui_m_appartient(self, mes_videos):
        app = mes_videos
        app.myvids_multi, app.myvids_selected = [], app.myvids_videos[0]
        app._myvids_render_detail()
        app.update()
        textes = _textes(app.myvids_detail)
        assert any("Remplacer" in t for t in textes), "le panneau n'a pas été construit"
        self._aucune_suppression(textes)

    def test_panneau_d_une_video_en_copropriete(self, mes_videos):
        app = mes_videos
        app.myvids_multi, app.myvids_selected = [], app.myvids_videos[2]
        app._myvids_render_detail()
        app.update()
        self._aucune_suppression(_textes(app.myvids_detail))

    def test_panneau_de_selection_multiple(self, mes_videos):
        app = mes_videos
        app.myvids_multi = ["v0", "v1", "co"]
        app._myvids_render_detail()
        app.update()
        textes = _textes(app.myvids_detail)
        assert any("3 vidéos sélectionnées" in t for t in textes), textes[:5]
        self._aucune_suppression(textes)


# ── L'aide n'en parle pas ──────────────────────────────────────────────────

class TestAideSansSuppression:

    @staticmethod
    def _titres():
        with open(os.path.join(RACINE, "app.py"), encoding="utf-8") as f:
            source = f.read()
        d = source.index("        sections = [")
        f = source.index("        # Rendu automatique des sections")
        bloc = source[d:f]
        return bloc, re.findall(r'\n            \("(\d+)\. ([^"]*)"', bloc)

    def test_aucune_rubrique_de_suppression(self):
        bloc, titres = self._titres()
        assert not [t for _, t in titres if "upprim" in t], titres
        assert "Supprimer cette vidéo" not in bloc

    def test_numerotation_continue(self):
        """Une rubrique retirée ne doit pas laisser de trou (1, 2, …, 9, 11)."""
        _, titres = self._titres()
        numeros = [int(n) for n, _ in titres]
        assert numeros == list(range(1, len(numeros) + 1)), numeros
