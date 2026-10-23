"""Workflow : les installeurs des builds d'essai ne sont gardés que 14 jours.

Le stockage des artefacts GitHub est commun à tous les dépôts du compte ;
sans limite, il s'est rempli (PodAdmin, 2026-10-22). Repris de PodAdmin.
"""
import os

import yaml

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _envois_d_artefacts():
    with open(os.path.join(RACINE, ".github", "workflows", "build.yml"), encoding="utf-8") as f:
        w = yaml.safe_load(f)
    return [etape for nom_job, job in w["jobs"].items()
            for etape in job.get("steps", [])
            if str(etape.get("uses", "")).startswith("actions/upload-artifact")]


def test_chaque_installeur_est_garde_14_jours():
    envois = _envois_d_artefacts()
    assert len(envois) == 2, "un envoi d'installeur a disparu ou s'est ajouté"
    assert [e["with"].get("retention-days") for e in envois] == [14, 14]
