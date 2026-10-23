"""Pagination : listes complètes malgré les 12 éléments par page de Pod (3.4.3).

Le serveur de l'université impose 12 éléments par page et ignore `limit`.
Les plafonds fixes (calculés pour 100 par page) coupaient l'annuaire des
co-propriétaires vers 960 comptes et la lecture complète du fonds vers
3 600 vidéos ; types, disciplines et sites n'étaient lus que sur une page.
Correctif repris de PodAdmin 1.13.2.
"""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

import pod_api
from pod_api import PodAPI

BASE = "https://pod.exemple.fr/rest"
PAR_PAGE = 12


class ServeurPagine:
    """Doublure de requests.Session : sert `total` éléments par pages de 12,
    comme le serveur réel, quel que soit le `limit` demandé."""

    class _Reponse:
        def __init__(self, donnees):
            self.status_code = 200
            self.url = BASE
            self._donnees = donnees
            self.text = json.dumps(donnees)

        def json(self):
            return self._donnees

    def __init__(self, total, annonce=None):
        self.total = total
        self.annonce = total if annonce is None else annonce
        self.appels = 0
        self.headers = {}

    def get(self, url, params=None, **kw):
        self.appels += 1
        page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        debut = (page - 1) * PAR_PAGE
        fin = min(debut + PAR_PAGE, self.total)
        chemin = urlsplit(url).path
        suivante = f"https://pod.exemple.fr{chemin}?page={page + 1}" if fin < self.total else None
        return self._Reponse({"count": self.annonce, "next": suivante,
                              "results": [{"id": i} for i in range(debut, fin)]})


def _api(total, annonce=None):
    api = PodAPI("https://pod.exemple.fr", "jeton-de-test")
    api.session = ServeurPagine(total, annonce)
    return api


class TestListesCompletes:

    def test_annuaire_au_dela_de_80_pages(self):
        """get_all_users plafonnait à 80 pages : 960 comptes sur 5 000."""
        api = _api(5000)
        assert len(api.get_all_users()) == 5000

    def test_fonds_au_dela_de_300_pages(self):
        """Lecture complète de « Mes vidéos » (filtre refusé) : 3 600 au plus."""
        api = _api(4000)
        assert len(api.get_all_videos()) == 4000

    @pytest.mark.parametrize("methode", ["get_types", "get_disciplines", "get_sites"])
    def test_listes_de_reference_sur_plusieurs_pages(self, methode):
        api = _api(30)
        assert [x["id"] for x in getattr(api, methode)()] == list(range(30))


class TestPagesNecessaires:

    def test_le_plafond_est_un_minimum(self):
        assert PodAPI._pages_necessaires({"count": 24, "results": [{}] * 12}, 300) == 300

    def test_releve_d_apres_le_total(self):
        # 1 000 / 12 = 83,3 → 84 pages, + 1 pour un ajout pendant la lecture.
        assert PodAPI._pages_necessaires({"count": 1000, "results": [{}] * 12}, 80) == 85

    def test_garde_fou_absolu(self):
        page = {"count": 10**9, "results": [{}] * 12}
        assert PodAPI._pages_necessaires(page, 80) == pod_api.PAGES_MAX_ABSOLU

    @pytest.mark.parametrize("page", [
        [], None, {"results": [{}] * 12}, {"count": "12", "results": [{}]},
        {"count": 50, "results": []},
    ])
    def test_reponse_inattendue_garde_le_plafond(self, page):
        assert PodAPI._pages_necessaires(page, 80) == 80

    def test_total_sous_estime_ne_boucle_pas_sans_fin(self, monkeypatch):
        """Un serveur qui annonce un total énorme mais dont `next` ne s'arrête
        jamais : la lecture s'arrête au garde-fou."""
        monkeypatch.setattr(pod_api, "PAGES_MAX_ABSOLU", 50)
        api = _api(10**6, annonce=10**6)
        api._paginate("/videos/", max_pages=10)
        assert api.session.appels == 50
