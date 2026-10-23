"""Filtres de « Mes vidéos » : les trois statuts sont exclusifs.

Le filtre « Public » gardait aussi les vidéos restreintes (il ne testait que
`is_draft`), alors que le panneau de détail les classe à part.
"""
import pytest


@pytest.fixture
def mes_videos(app):
    app.myvids_videos = [
        {"slug": "b", "title": "B", "is_draft": True, "channel": []},
        {"slug": "p", "title": "P", "is_draft": False, "is_restricted": False, "channel": []},
        {"slug": "r", "title": "R", "is_draft": False, "is_restricted": True, "channel": []},
    ]
    yield app
    app.myvids_statut.set(app.myvids_statut.cget("values")[0])
    app.myvids_videos, app.myvids_filtered, app.myvids_selected = [], [], None


@pytest.mark.parametrize("statut, attendus", [
    ("Brouillon", ["b"]), ("Public", ["p"]), ("Restreint", ["r"]),
])
def test_un_statut_par_video(mes_videos, statut, attendus):
    app = mes_videos
    valeurs = app.myvids_statut.cget("values")
    choix = next(v for v in valeurs if v.startswith(statut))   # « Restreinte » ou « Restreint »
    app.myvids_statut.set(choix)
    app._myvids_apply_filter()
    assert [v["slug"] for v in app.myvids_filtered] == attendus
