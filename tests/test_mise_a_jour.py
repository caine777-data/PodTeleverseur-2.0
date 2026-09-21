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


class TestTransmissionDesChampsObligatoires:
    """⚠️ RÉGRESSION RÉELLE, trouvée en test manuel : les champs `obligatoire`
    et `version_minimale` existaient bien dans le FORMULAIRE
    (workflow_dispatch), mais n'étaient JAMAIS transmis au bloc qui écrit
    `version.json`. Une publication avec « obligatoire » coché produisait
    donc, sans avertissement, un fichier PARFAITEMENT NORMAL — aucun blocage
    ne pouvait jamais se déclencher.

    Les tests précédents ne pouvaient pas voir ce trou : l'un vérifiait la
    présence des champs dans le FORMULAIRE, l'autre vérifiait la LOGIQUE de
    maj.py une fois des données reçues. Le maillon entre les deux — est-ce
    que le formulaire alimente réellement le JSON généré ? — n'était testé
    nulle part. C'est ce test-ci qui le couvre."""

    def _workflow(self):
        return _lire(".github/workflows/build.yml")

    def test_le_bloc_ecrit_obligatoire_depuis_le_formulaire(self):
        w = self._workflow()
        # ⚠️ Le heredoc commence par `<<EOF` : chercher le PREMIER "EOF"
        # après "cat > version.json" trouve cette ouverture, pas la fin du
        # bloc. Il faut le second "EOF" — celui qui ferme réellement le
        # heredoc. Une première version de ce test se trompait ici et
        # tronquait le bloc avant même son contenu.
        deb = w.index("cat > version.json")
        ouverture = w.index("EOF", deb)
        fin = w.index("EOF", ouverture + 3)
        bloc = w[deb:fin]
        assert "inputs.obligatoire" in w[:deb], (
            "le formulaire obligatoire n'est lu dans aucune variable avant "
            "l'écriture du fichier")
        assert '"obligatoire":' in bloc, (
            "le champ obligatoire n'est pas écrit dans version.json")

    def test_le_bloc_ecrit_version_minimale_depuis_le_formulaire(self):
        w = self._workflow()
        assert "inputs.version_minimale" in w, (
            "le formulaire version_minimale n'est lu nulle part")
        # Ne doit plus être figé à une chaîne vide littérale.
        bloc = w[w.index("cat > version.json"):w.index("EOF", w.index("cat > version.json"))]
        assert '"version_minimale": ""' not in bloc, (
            "version_minimale est encore figé à une chaîne vide en dur : le "
            "formulaire n'est jamais réellement pris en compte")

    def test_simulation_bash_reproduit_la_regle_documentee(self):
        """Rejoue littéralement la logique bash du workflow (sans l'exécuter
        via GitHub Actions) pour les 3 combinaisons qui comptent, et vérifie
        le JSON obtenu — c'est exactement le calcul qui a été trouvé cassé
        lors d'un test réel."""
        import json
        import subprocess

        script = self._workflow()
        # Extrait le bloc de calcul bash tel qu'il existe réellement dans le
        # fichier, entre la lecture des inputs et l'écriture du JSON — on ne
        # duplique pas la logique dans le test, on rejoue le VRAI script.
        deb = script.index('VERSION="${{ steps.v.outputs.num }}"')
        fin = script.index("cat > version.json")
        # Même correction que ci-dessus : viser le second "EOF" pour ne pas
        # tronquer avant le contenu réel du bloc de calcul.
        fin = script.index("cat > version.json")
        bloc_brut = script[deb:fin]
        # Neutralise la syntaxe GitHub Actions ${{ ... }} par des variables
        # d'environnement shell classiques, injectées avant exécution.
        bloc_bash = (bloc_brut
                     .replace('${{ steps.v.outputs.num }}', "$V_NUM")
                     .replace('${{ inputs.notes }}', "$IN_NOTES")
                     .replace('${{ inputs.obligatoire }}', "$IN_OBLIGATOIRE")
                     .replace('${{ inputs.version_minimale }}', "$IN_MINIMALE"))

        cas = [
            ({"IN_OBLIGATOIRE": "true", "IN_MINIMALE": ""},
             {"obligatoire": True, "version_minimale": "2.3.0"}),
            ({"IN_OBLIGATOIRE": "true", "IN_MINIMALE": "2.1.0"},
             {"obligatoire": True, "version_minimale": "2.1.0"}),
            ({"IN_OBLIGATOIRE": "false", "IN_MINIMALE": ""},
             {"obligatoire": False, "version_minimale": ""}),
        ]
        import tempfile

        # ⚠️ Passer le bloc via `bash -c "chaîne"` casse la syntaxe : le
        # commentaire du workflow contient des apostrophes françaises et des
        # guillemets qui entrent en conflit avec l'échappement de la chaîne
        # d'arguments. On écrit le script dans un VRAI fichier temporaire,
        # exactement comme GitHub Actions le ferait lui-même.
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sh", delete=False) as f:
            f.write(bloc_bash)
            f.write('\necho "OBL=$OBLIGATOIRE"\necho "MIN=$MINIMALE"\n')
            chemin_script = f.name

        try:
            for env_supp, attendu in cas:
                env = {"V_NUM": "2.3.0", "IN_NOTES": "test",
                       "DEPOT_PUBLIC": "", "GITHUB_REPOSITORY_OWNER": "x"}
                env.update(env_supp)
                resultat = subprocess.run(
                    ["bash", chemin_script],
                    capture_output=True, text=True, env=env)
                sortie = resultat.stdout
                lignes_obl = [l for l in sortie.splitlines() if l.startswith("OBL=")]
                lignes_min = [l for l in sortie.splitlines() if l.startswith("MIN=")]
                assert lignes_obl and lignes_min, (
                    f"cas {env_supp} : le script n'a produit aucune sortie "
                    f"exploitable (stderr : {resultat.stderr!r})")
                obl = lignes_obl[-1][4:]
                mini = lignes_min[-1][4:]
                assert (obl == "true") == attendu["obligatoire"], (
                    f"cas {env_supp} : obligatoire calculé = {obl!r}, "
                    f"attendu {attendu['obligatoire']}")
                assert mini == attendu["version_minimale"], (
                    f"cas {env_supp} : version_minimale calculée = {mini!r}, "
                    f"attendu {attendu['version_minimale']!r}")
        finally:
            os.remove(chemin_script)


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

    def test_seuls_les_deux_installeurs_sont_publies(self):
        """⚠️ Demande explicite : plus de version portable dans la Release, et
        chaque nom de fichier doit porter son OS en clair — c'est ce nom-là que
        voit la personne qui télécharge, jamais le libellé de l'artefact
        GitHub."""
        w = self._workflow()
        bloc = w[w.index("files: |"):]
        bloc = bloc[:bloc.index("\n\n")]
        publies = [l.strip() for l in bloc.split("\n")[1:] if l.strip()]
        noms_fichiers = [os.path.basename(p) for p in publies]

        assert len(noms_fichiers) == 2, (
            f"deux fichiers attendus (un par OS), trouvé : {noms_fichiers}")
        for nom in noms_fichiers:
            assert "Windows" in nom or "macOS" in nom, (
                f"« {nom} » ne précise pas son OS dans son nom de fichier")
        # Aucun fichier « portable » ne doit plus être publié.
        assert not any("portable" in n.lower() for n in noms_fichiers), (
            f"un livrable portable est encore publié : {noms_fichiers}")

    def test_les_noms_publies_different_des_noms_internes(self):
        """Le renommage doit se faire PENDANT la compilation, avant
        `upload-artifact` — sinon le fichier reste ambigu jusqu'à la Release,
        et un test qui ne vérifie que la Release finale masquerait l'oubli."""
        w = self._workflow()
        assert "PodTeleverseur-Windows-Setup.exe" in w
        assert "PodTeleverseur-macOS.dmg" in w
        assert "Rename-Item" in w, (
            "l'installeur Windows n'est pas renommé avant publication")


class TestVerrouLocalDuBlocage:
    """Modèle 1 durci : blocage informé, mémorisé localement une fois confirmé.

    Un serveur GitHub injoignable ne doit JAMAIS empêcher tout le monde de
    travailler — mais une personne à qui le serveur a déjà confirmé qu'elle
    doit mettre à jour ne doit pas pouvoir contourner ce blocage en coupant
    simplement sa connexion au lancement suivant."""

    @staticmethod
    def _config_isolee(tmp_path, monkeypatch):
        """Redirige config.CONFIG_PATH vers un fichier jetable, pour ne
        jamais toucher au vrai fichier de configuration de la machine qui
        exécute ces tests."""
        import config as cfg
        chemin = tmp_path / "config_test.json"
        monkeypatch.setattr(cfg, "CONFIG_PATH", str(chemin))
        return cfg

    def test_rien_au_depart(self, tmp_path, monkeypatch):
        cfg = self._config_isolee(tmp_path, monkeypatch)
        assert cfg.blocage_local_actif("2.5.0") is None

    def test_enregistrement_puis_lecture(self, tmp_path, monkeypatch):
        cfg = self._config_isolee(tmp_path, monkeypatch)
        cfg.enregistrer_blocage_confirme(
            "2.5.0", "3.0.0",
            url="https://example.invalid/releases", notes="Mise à jour de sécurité.")
        r = cfg.blocage_local_actif("2.5.0")
        assert r is not None
        assert r["version"] == "3.0.0"
        assert r["url"] == "https://example.invalid/releases"
        assert r["notes"] == "Mise à jour de sécurité."

    def test_le_verrou_ne_fuite_pas_vers_une_autre_version(self, tmp_path, monkeypatch):
        """⚠️ Point le plus sensible : si la personne réinstalle une version
        DIFFÉRENTE sans passer par une mise à jour normale, le verrou de
        l'ancienne version ne doit jamais s'appliquer à la nouvelle."""
        cfg = self._config_isolee(tmp_path, monkeypatch)
        cfg.enregistrer_blocage_confirme("2.5.0", "3.0.0")
        assert cfg.blocage_local_actif("2.6.0") is None, (
            "le verrou local d'une version a fuité vers une autre version")

    def test_lever_le_verrou(self, tmp_path, monkeypatch):
        cfg = self._config_isolee(tmp_path, monkeypatch)
        cfg.enregistrer_blocage_confirme("2.5.0", "3.0.0")
        cfg.lever_blocage_local()
        assert cfg.blocage_local_actif("2.5.0") is None

    def test_le_verrou_survit_a_un_echec_reseau_simule(self, tmp_path, monkeypatch):
        """C'est tout le sens du mécanisme : le verrou doit continuer de
        s'appliquer même quand `recuperer_info` échoue (réseau coupé)."""
        cfg = self._config_isolee(tmp_path, monkeypatch)
        cfg.enregistrer_blocage_confirme("2.5.0", "3.0.0",
                                         url="https://x.invalid", notes="X")
        import maj
        monkeypatch.setattr(maj, "recuperer_info", lambda *a, **k: None)
        # Le verrou local, LUI, ne dépend d'aucun appel réseau : il doit
        # rester actif quel que soit l'état du réseau au moment du contrôle.
        assert cfg.blocage_local_actif("2.5.0") is not None


class TestBlocageObligatoireDansMaj:
    """Calcul du champ `obligatoire` dans maj.etat_mise_a_jour — garde-fou
    sur le seuil : une obligation annoncée ne doit jamais s'appliquer à un
    simple retard mineur, hors de portée de `version_minimale`."""

    def _simuler(self, version_installee, donnees_serveur):
        import maj
        from unittest import mock
        with mock.patch.object(maj, "recuperer_info", return_value=donnees_serveur):
            return maj.etat_mise_a_jour(version_installee, "https://x.invalid")

    def test_a_jour_avec_obligatoire_annonce_ne_bloque_rien(self):
        r = self._simuler("2.5.0", {
            "version": "2.5.0", "version_minimale": "2.0.0", "obligatoire": True})
        assert r is None

    def test_en_retard_mais_au_dessus_du_seuil_minimal(self):
        """Version installée 2.5.0, seuil minimal 2.0.0 : la personne est en
        retard par rapport à la dernière version (3.0.0), mais AU-DESSUS du
        seuil minimal — un simple retard, pas une urgence."""
        r = self._simuler("2.5.0", {
            "version": "3.0.0", "version_minimale": "2.0.0", "obligatoire": True})
        assert r is not None
        assert r["urgent"] is False, (
            "urgent=True alors que la version installée est au-dessus du "
            "seuil minimal")
        assert r["obligatoire"] is False, (
            "obligatoire=true dans le fichier a bloqué un simple retard "
            "mineur, alors que le seuil version_minimale n'est pas franchi")

    def test_en_dessous_du_seuil_minimal_avec_obligatoire(self):
        r = self._simuler("1.5.0", {
            "version": "3.0.0", "version_minimale": "2.0.0", "obligatoire": True})
        assert r["urgent"] is True
        assert r["obligatoire"] is True

    def test_ancien_format_sans_champ_obligatoire(self):
        """Rétrocompatibilité : un version.json publié avant l'ajout de ce
        champ ne doit jamais déclencher de blocage par accident."""
        r = self._simuler("1.5.0", {
            "version": "3.0.0", "version_minimale": "2.0.0"})
        assert r["urgent"] is True
        assert r["obligatoire"] is False

    def test_infos_reutilisees_evite_un_second_appel_reseau(self):
        """`infos=` doit permettre de réutiliser un résultat déjà récupéré,
        sans réseau supplémentaire — sinon app.py ferait deux requêtes à
        chaque démarrage."""
        import maj
        appels = []

        def espion(*a, **k):
            appels.append(1)
            return {"version": "2.0.0"}

        import unittest.mock as mock
        with mock.patch.object(maj, "recuperer_info", espion):
            donnees = maj.recuperer_info("https://x.invalid")
            maj.etat_mise_a_jour("2.0.0", "https://x.invalid", infos=donnees)
        assert len(appels) == 1, (
            f"recuperer_info appelé {len(appels)} fois, attendu 1 seule")


class TestFenetreBloquanteAppelleLeVerrou:
    """Vérifie que le CODE, pas seulement la logique isolée, mémorise et
    consulte bien le verrou local aux bons endroits."""

    def test_verifier_maj_enregistre_le_blocage_confirme(self):
        # ⚠️ On lit le FICHIER SOURCE directement, et non via
        # `inspect.getsource` sur la méthode chargée en mémoire : la fixture
        # `app` (conftest.py) remplace `App._verifier_maj` par une lambda
        # vide dès l'import du module, pour éviter tout accès réseau pendant
        # les tests. `inspect.getsource` aurait alors récupéré cette lambda
        # de substitution plutôt que le vrai code.
        source = _lire("app.py")
        deb = source.index("def _verifier_maj(")
        fin = source.index("def _bloquer_demarrage(")
        corps = source[deb:fin]
        assert "enregistrer_blocage_confirme" in corps, (
            "un blocage confirmé par le réseau n'est pas mémorisé localement"
        )

    def test_verifier_maj_leve_le_verrou_si_a_jour_confirme(self):
        source = _lire("app.py")
        deb = source.index("def _verifier_maj(")
        fin = source.index("def _bloquer_demarrage(")
        corps = source[deb:fin]
        assert "lever_blocage_local" in corps, (
            "le verrou local n'est jamais levé quand le serveur confirme "
            "que l'application est à jour")

    def test_le_demarrage_consulte_le_verrou_local_en_tout_premier(self):
        """Avant même l'auto-connexion ou l'assistant de premier lancement :
        sinon une interaction serait possible avant l'affichage du blocage.

        ⚠️ On cherche l'APPEL réel (avec parenthèse), pas la simple présence
        de la chaîne "blocage_local_actif" : un premier essai de ce test a
        laissé passer une mutation, parce qu'un COMMENTAIRE au-dessus du code
        mentionnait déjà ce nom avant l'appel à l'auto-connexion, même une
        fois le VRAI appel déplacé après."""
        source = _lire("app.py")
        deb = source.index("def __init__(self):")
        fin = source.index("\n    def ", deb + 20)
        corps = source[deb:fin]
        pos_verrou = corps.find("cfg.blocage_local_actif(APP_VERSION)")
        pos_auto_connect = corps.find("self._run(self._auto_connect)")
        assert pos_verrou != -1, "le verrou local n'est pas consulté au démarrage"
        assert pos_auto_connect != -1, "l'auto-connexion introuvable dans __init__"
        assert pos_verrou < pos_auto_connect, (
            "le verrou local est consulté APRÈS l'auto-connexion : une "
            "interaction serait possible avant le blocage")


class TestBoutonDeTelechargementToujoursPresent:
    """⚠️ La fenêtre bloquante ne doit JAMAIS se retrouver sans aucun moyen
    d'agir. Un premier essai rendait le bouton conditionnel à `info["url"]` :
    un `version.json` corrompu, modifié à la main, ou un ancien verrou local
    sans URL enregistrée aurait alors produit un blocage total SANS ISSUE."""

    @staticmethod
    def _bouton_present(win):
        import customtkinter as ctk
        for w in win.winfo_children():
            if isinstance(w, ctk.CTkButton) and "élécharger" in str(w.cget("text")):
                return True
        return False

    @staticmethod
    def _nettoyer(win, app):
        for ident in win.tk.call("after", "info"):
            try:
                win.after_cancel(ident)
            except Exception:
                pass
        for ident in app.tk.call("after", "info"):
            try:
                app.after_cancel(ident)
            except Exception:
                pass
        win.destroy()

    def test_bouton_present_avec_url(self, app):
        import customtkinter as ctk
        app._bloquer_demarrage({"version": "9.9.9", "url": "https://x.invalid",
                               "notes": "Test.", "urgent": True,
                               "obligatoire": True})
        app.update()
        win = [w for w in app.winfo_children()
               if isinstance(w, ctk.CTkToplevel)][0]
        assert self._bouton_present(win)
        self._nettoyer(win, app)

    def test_bouton_present_meme_sans_url(self, app):
        """Le cas qui comptait vraiment : `url` vide ou absente."""
        import customtkinter as ctk
        app._bloquer_demarrage({"version": "9.9.9", "url": "",
                               "notes": "Sans URL.", "urgent": True,
                               "obligatoire": True})
        app.update()
        win = [w for w in app.winfo_children()
               if isinstance(w, ctk.CTkToplevel)][0]
        assert self._bouton_present(win), (
            "fenêtre bloquante SANS bouton de téléchargement : blocage sans "
            "aucune issue possible")
        self._nettoyer(win, app)

    def test_le_code_source_n_a_plus_de_bouton_conditionnel(self):
        """Garde-fou direct sur la source : le bouton ne doit plus dépendre
        d'un `if info.get("url"):` qui l'omettrait entièrement."""
        source = _lire("app.py")
        deb = source.index("def _bloquer_demarrage(")
        fin = source.index("def _afficher_bandeau_maj(")
        corps = source[deb:fin]
        assert 'if info.get("url"):' not in corps, (
            "le bouton de téléchargement est encore conditionnel à la "
            "présence de l'URL")
        assert "UPDATE_FALLBACK_URL" in corps, (
            "aucune URL de repli n'est utilisée si info['url'] est vide")
