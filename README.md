# Pod Téléverseur — Université de Toulouse

Application de bureau pour **téléverser des vidéos par lot** vers l'instance
Esup-Pod de l'Université de Toulouse (`videos.utoulouse.fr`).

Version légère dérivée de **PodAdmin** : seuls le téléversement, la
configuration et le journal sont conservés ; tous les modules d'administration
ont été retirés. Destinée aux enseignants et au support.

## Fonctionnalités

- **Téléversement par lot** : ajout de fichiers, d'un dossier entier
  (scan récursif) ou **glisser-déposer** de fichiers et dossiers.
- **Titres éditables** avant l'envoi, état par vidéo, barre de progression
  (fichier courant + lot global), upload streamé (gros fichiers).
- **Réglages communs au lot** : type de vidéo, visibilité
  (Brouillon/Privé ou Public), propriétaires additionnels, et case
  **« Lancer l'encodage après le téléversement »** (cochée par défaut).
- **Assistant de première utilisation** : au tout premier lancement (aucun
  token enregistré), une fenêtre guide l'utilisateur en deux étapes — coller
  le token (adresse pré-remplie) puis choisir le compte déposant — avant
  d'arriver sur l'onglet Téléversement.
- **Configuration** : connexion à l'instance (URL + token), choix du
  compte déposant (propriétaire des vidéos), bouton « Oublier le token ».
- **Choix guidé du compte déposant** : à la première connexion, le compte
  est détecté automatiquement s'il est certain, sinon une fenêtre invite à
  le choisir explicitement (modifiable ensuite dans Configuration).
- **Journal** horodaté des opérations.
- **Aide** : fenêtre expliquant chaque fonction (pour les enseignants).
- **À propos** : fenêtre d'information (version, auteurs, contact).

## Sécurité du token

Le token est stocké dans le **coffre-fort de l'OS** (Windows Credential
Manager / macOS Keychain) via `keyring`, avec repli sur un fichier local à
permissions restreintes si le coffre-fort est indisponible. **Toujours par
poste, jamais dans l'exécutable.** Clé dédiée `PodTeleverseur-UToulouse`,
distincte de celle de PodAdmin : les deux applications cohabitent sans
conflit.

## Lancer en développement

```bash
pip install -r requirements.txt
python app.py
```

## Compiler

### En local (PyInstaller)

Windows (PowerShell) :

```powershell
python -m PyInstaller --onefile --windowed --name "PodTeleverseur" `
  --icon "assets/icon.ico" --version-file version.txt `
  --collect-all customtkinter --collect-all keyring --collect-all tkinterdnd2 `
  --add-data "assets;assets" app.py
```

macOS / Linux (séparateur `:` au lieu de `;`) :

```bash
python -m PyInstaller --onefile --windowed --name "PodTeleverseur" \
  --icon "assets/icon.icns" \
  --collect-all customtkinter --collect-all keyring --collect-all tkinterdnd2 \
  --add-data "assets:assets" app.py
```

### Via GitHub Actions (recommandé)

Le workflow `.github/workflows/build.yml` compile et fabrique les **installeurs**
pour Windows et macOS :
- bouton **« Run workflow »** (onglet Actions) pour un build manuel ;
- push d'un **tag `v*`** (ex. `v1.0.0`) pour créer une **Release** avec les
  installeurs attachés.

Artefacts produits :
- `PodTeleverseur-Setup.exe` — installeur Windows (Inno Setup) ;
- `PodTeleverseur.exe` — version portable Windows (sans installation) ;
- `PodTeleverseur.dmg` — image disque macOS (glisser l'appli dans Applications).

> ⚠️ Le dossier caché `.github` est souvent oublié à l'envoi : vérifier sa
> présence dans le dépôt (ou créer le fichier directement sur GitHub).

## Installation (utilisateur final)

### Windows
Double-cliquez sur **`PodTeleverseur-Setup.exe`** et suivez l'assistant. L'appli
s'installe **sans droits administrateur** (dans le profil de l'utilisateur) et
ajoute les raccourcis menu Démarrer + Bureau. Désinstallation via « Ajout/
Suppression de programmes ».

### macOS
Ouvrez **`PodTeleverseur.dmg`**, puis glissez **Pod Téléverseur** dans le
dossier **Applications**.

### ⚠️ Avertissements de sécurité (applications non signées)
Les installeurs ne sont pas signés numériquement : au premier lancement, le
système affiche un avertissement. C'est normal et contournable :
- **Windows (SmartScreen)** : « Windows a protégé votre ordinateur » →
  « Informations complémentaires » → « Exécuter quand même ».
- **macOS (Gatekeeper)** : clic droit sur l'appli → « Ouvrir », ou Réglages
  Système → Confidentialité et sécurité → « Ouvrir quand même ». En dernier
  recours : `xattr -cr "/Applications/PodTeleverseur.app"`.

Pour supprimer ces avertissements, il faut **signer le code** : certificat
Authenticode (Windows) et compte Apple Developer + notarisation (macOS),
généralement disponibles via le service informatique de l'université.

> Note macOS : les runners GitHub sont des Mac **Apple Silicon** → l'appli est
> en arm64 (ne tourne pas sur un Mac Intel sans build dédié).

## Diagnostic

`verifier.py` teste le token et liste les champs requis de l'API (méthode
OPTIONS). Le dossier `scripts/` contient des commandes curl de référence
(commentées en français).

## Arborescence

```
pod-televerseur/
├── app.py                       # Interface (CustomTkinter) — Téléversement, Config, Journal, À propos
├── pod_api.py                   # Client API REST Esup-Pod
├── config.py                    # Config + stockage chiffré du token
├── verifier.py                  # Diagnostic API
├── requirements.txt
├── version.txt                  # Métadonnées Windows de l'exe
├── assets/
│   ├── logo_ut.png
│   ├── icon.ico            # icône Windows (exe + installeur)
│   └── icon_master.png     # source de l'icône macOS (.icns généré au build)
├── scripts/                     # Commandes curl de référence
├── installer/installer.iss      # Script de l'installeur Windows (Inno Setup)
└── .github/workflows/build.yml  # Compilation Windows + macOS
```

---

Développé par **Cédric MONNA**, **Philippe BAQUÉ** et **Michel JACOB** — Université de Toulouse — `support-pod@utoulouse.fr`
Usage interne, non redistribuable.

---

## Droits

© Copyright 2026 Cédric MONNA

Développé pour l'Université de Toulouse, avec Philippe BAQUÉ et Michel JACOB.

**Tous droits réservés.** La réutilisation, la diffusion ou l'adaptation de cet
outil, en tout ou partie, sont soumises à l'autorisation préalable de l'auteur.

Contact : support-pod@utoulouse.fr
