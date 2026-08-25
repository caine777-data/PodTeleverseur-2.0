; ============================================================================
;  installer.iss — Script Inno Setup pour l'installeur Windows de Pod Téléverseur
;  Université de Toulouse
;
;  Génère "PodTeleverseur-Setup.exe" : un installeur classique qui copie l'appli,
;  crée les raccourcis (menu Démarrer + Bureau au choix) et un désinstalleur.
;
;  Compilation : iscc installer\installer.iss   (exécuté depuis la racine du projet)
;  L'exécutable "dist\PodTeleverseur.exe" doit avoir été produit au préalable par
;  PyInstaller (c'est ce que fait le workflow GitHub Actions juste avant).
; ============================================================================

; --- Variables pratiques (modifiables à chaque nouvelle version) ---
#define MyAppName "Pod Téléverseur"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Université de Toulouse"
#define MyAppCopyright "© Copyright 2026 Cédric MONNA"
#define MyAppExeName "PodTeleverseur.exe"
#define MyAppContact "support-pod@utoulouse.fr"

[Setup]
; AppId identifie l'application de façon unique (NE PAS changer entre les versions,
; sinon Windows considère qu'il s'agit d'un logiciel différent).
AppId={{8F3A6C21-4D7B-4E2A-9C15-7B2E5D9A1C04}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright={#MyAppCopyright}
AppContact={#MyAppContact}
AppSupportURL=mailto:{#MyAppContact}

; Les chemins ci-dessous sont relatifs à la RACINE du projet (voir SourceDir).
SourceDir=..
OutputDir=installer_output
OutputBaseFilename=PodTeleverseur-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; Installation par UTILISATEUR (pas besoin de droits administrateur) : idéal pour
; des postes d'enseignants verrouillés. L'appli s'installe alors dans le profil.
PrivilegesRequired=lowest
DefaultDirName={autopf}\PodTeleverseur
DefaultGroupName=Pod Téléverseur
DisableProgramGroupPage=yes

; Compression et apparence
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

; N'autoriser que les Windows 64 bits récents
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
; Interface de l'installeur en français (fichier livré avec Inno Setup).
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
; Raccourci Bureau proposé (coché par défaut).
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; \
  GroupDescription: "Raccourcis :"

[Files]
; Le programme lui-même (un seul .exe autonome produit par PyInstaller --onefile).
Source: "dist\PodTeleverseur.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Raccourci dans le menu Démarrer
Name: "{group}\Pod Téléverseur"; Filename: "{app}\{#MyAppExeName}"
; Raccourci de désinstallation dans le menu Démarrer
Name: "{group}\Désinstaller Pod Téléverseur"; Filename: "{uninstallexe}"
; Raccourci Bureau (si la tâche correspondante est cochée)
Name: "{autodesktop}\Pod Téléverseur"; Filename: "{app}\{#MyAppExeName}"; \
  Tasks: desktopicon

[Run]
; Proposer de lancer l'appli à la fin de l'installation.
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer Pod Téléverseur maintenant"; \
  Flags: nowait postinstall skipifsilent
