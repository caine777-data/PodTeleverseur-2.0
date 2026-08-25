#!/usr/bin/env python3
"""
app.py — Pod Téléverseur (interface graphique)
Université de Toulouse

Application de téléversement par lot pour l'instance Esup-Pod de
l'Université de Toulouse. Version légère destinée aux enseignants :
  • Téléversement par lot (glisser-déposer, titres éditables, propriétaires
    additionnels communs, lancement d'encodage automatique après l'envoi).
  • Configuration (connexion à l'instance + choix du compte déposant).
  • Journal des opérations.
Dérivée de PodAdmin : tous les modules d'administration ont été retirés.
"""

from __future__ import annotations

__author__      = "Cédric MONNA, Philippe BAQUÉ, Michel JACOB"
__contact__     = "support-pod@utoulouse.fr"
__institution__ = "Université de Toulouse"
__version__     = "2.0.0"
__date__        = "2026"
__copyright__   = "© Copyright 2026 Cédric MONNA"
__license__     = ("Tous droits réservés — réutilisation, diffusion ou "
                   "adaptation soumises à l'autorisation de l'auteur.")


import os
import sys
import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox

import config as cfg
from pod_api import PodAPI, PodAPIError
# Moteur de téléversement par morceaux via session web (gros fichiers > seuil).
from pod_chunked import PodChunkedSession, PodChunkedError

# Pillow (fourni avec customtkinter) — pour afficher le logo
try:
    from PIL import Image as PILImage
    HAS_PIL = True
except Exception:
    HAS_PIL = False


def resource_path(rel: str) -> str:
    """Chemin d'une ressource, compatible PyInstaller (--onefile) et exécution directe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

# Glisser-déposer (optionnel — l'appli fonctionne sans, via les boutons)
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception:
    HAS_DND = False

APP_TITLE = "Pod Téléverseur — Université de Toulouse"
APP_VERSION = __version__


# ════════════════════════════════════════════════════════════════════════════
#  MODÈLE : une entrée de la file d'attente
# ════════════════════════════════════════════════════════════════════════════

class UploadItem:
    """Une vidéo dans la file de téléversement.

    Regroupe le fichier à envoyer, son titre (modifiable), son état d'avancement
    et, une fois déposée, son slug et son URL. Les attributs `row`, `title_var`
    et `status_lbl` sont les widgets d'affichage, remplis au moment du rendu."""
    def __init__(self, path: str):
        """Crée une entrée de la file d'upload à partir d'un chemin de fichier."""
        self.path = path
        self.filename = os.path.basename(path)
        # Titre par défaut = nom de fichier sans extension, nettoyé
        base = os.path.splitext(self.filename)[0]
        self.title = base.replace("_", " ").replace("-", " ").strip()
        self.status = "en attente"     # en attente | en cours | terminé | échec
        self.done = False              # True dès qu'un envoi a réussi (pour ne pas
                                       # ré-uploader un succès lors d'une relance)
        self.slug = ""
        self.video_url = ""
        self.error = ""
        # widgets (remplis à l'affichage)
        self.row = None
        self.title_var = None
        self.status_lbl = None


# ════════════════════════════════════════════════════════════════════════════
#  APPLICATION
# ════════════════════════════════════════════════════════════════════════════

# Base conditionnelle : mixe le moteur de glisser-déposer si disponible.
# tkinterdnd2 n'est pas toujours installé → on choisit la classe de base en
# conséquence, pour que l'appli fonctionne même sans glisser-déposer.
if HAS_DND:
    class _AppBase(ctk.CTk, TkinterDnD.DnDWrapper):
        pass          # CTk + capacité de glisser-déposer
else:
    class _AppBase(ctk.CTk):
        pass          # CTk seul (pas de glisser-déposer)


class App(_AppBase):
    """Fenêtre principale de Pod Téléverseur.

    Assemble l'interface (barre latérale + onglets Téléversement, Configuration,
    Journal…), gère la connexion à l'instance (token), le scan et le dépôt des
    vidéos par lot, et — pour les fichiers > 500 Mo — la bascule vers le
    téléversement par morceaux via le compte véhicule DEPOT puis la réattribution
    au propriétaire choisi. Toutes les opérations réseau tournent dans des threads
    séparés ; les mises à jour d'interface repassent par le thread principal via
    les helpers `_run` (tâche de fond) et `_ui` (mise à jour d'affichage)."""
    def __init__(self):
        """Initialise la fenêtre, charge config + token, construit l'UI et tente une connexion auto."""
        super().__init__()
        # Initialiser le moteur glisser-déposer (tkdnd)
        self.dnd_ok = False
        if HAS_DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_ok = True
            except Exception:
                self.dnd_ok = False

        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(1000, 660)

        self.config_data = cfg.load_config()
        self.token = cfg.load_token()
        # Compte VÉHICULE embarqué (DEPOT) : session web pour le chunké des gros
        # fichiers. Les enseignants ne le voient ni ne le saisissent.
        self.vehicle_username = cfg.VEHICLE_USERNAME
        self.vehicle_password = cfg.VEHICLE_PASSWORD
        self.vehicle_owner_url = ""      # URL Pod du véhicule (résolue à la connexion)
        self.api: PodAPI | None = None

        self.types: list[dict] = []
        self.type_map: dict[str, str] = {}     # titre → url
        self.site_urls: list[str] = []         # sites (requis à l'upload)
        self.items: list[UploadItem] = []
        self.all_users: list[dict] = []        # liste complète Pod (pour sélection owner)
        self.additional_owner_urls: list[str] = []
        self.additional_owner_map: dict[str, str] = {}   # url → libellé (pour ré-ouverture)
        self.common_contributors: list[dict] = []

        # Liaisons (« hooks ») utilisées par l'assistant de première utilisation
        # pour réagir au résultat de la connexion. None = aucun assistant en cours.
        self._post_connect_ok = None    # appelé après une connexion réussie
        self._post_connect_err = None   # appelé après un échec de connexion

        self._build_ui()
        self._show_tab("upload")

        # Démarrage :
        #   • token déjà enregistré → reconnexion automatique silencieuse ;
        #   • aucun token (= première utilisation sur ce poste) → on ouvre
        #     l'assistant guidé qui prend l'enseignant par la main.
        if self.config_data.get("url") and self.token:
            self._run(self._auto_connect)
        elif not self.token:
            self.after(300, self._first_run_wizard)

    # ── Threading helpers ────────────────────────────────────────────────

    def _run(self, fn, *a):
        """Lance une fonction dans un thread d'arrière-plan (pour ne pas geler l'interface)."""
        threading.Thread(target=fn, args=a, daemon=True).start()

    def _ui(self, fn, *a, **kw):
        """Planifie une mise à jour d'interface dans le thread principal Tk (thread-safe)."""
        self.after(0, lambda: fn(*a, **kw))

    # ── Construction de l'interface ──────────────────────────────────────

    def _build_ui(self):
        """Construit la barre latérale (logo, état, navigation) et la zone de contenu."""
        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # En-tête : logo Université de Toulouse sur bandeau blanc (repli texte si absent)
        logo_loaded = False
        if HAS_PIL:
            try:
                logo_path = resource_path(os.path.join("assets", "logo_ut.png"))
                if os.path.exists(logo_path):
                    pil = PILImage.open(logo_path)
                    W = 178
                    H = round(W * pil.height / pil.width)
                    self.logo_img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(W, H))
                    card = ctk.CTkFrame(self.sidebar, fg_color="white", corner_radius=8)
                    card.pack(padx=12, pady=(18, 6), fill="x")
                    ctk.CTkLabel(card, image=self.logo_img, text="").pack(padx=10, pady=10)
                    logo_loaded = True
            except Exception:
                logo_loaded = False

        if not logo_loaded:
            ctk.CTkLabel(self.sidebar, text="Université de Toulouse",
                         font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(20, 0), padx=14)

        ctk.CTkLabel(self.sidebar, text="📂  Pod Téléverseur",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(2, 0), padx=14)

        # État connexion
        box = ctk.CTkFrame(self.sidebar, fg_color="gray20", corner_radius=8)
        box.pack(padx=12, pady=14, fill="x")
        self.status_dot = ctk.CTkLabel(box, text="⚫", font=ctk.CTkFont(size=13))
        self.status_dot.pack(side="left", padx=8, pady=6)
        self.status_lbl = ctk.CTkLabel(box, text="Non connecté",
                                       font=ctk.CTkFont(size=11), text_color="gray")
        self.status_lbl.pack(side="left")

        # Agent identifié
        self.agent_lbl = ctk.CTkLabel(self.sidebar, text="", font=ctk.CTkFont(size=11),
                                      text_color="gray70", wraplength=190, justify="left")
        self.agent_lbl.pack(padx=14, pady=(0, 6), anchor="w")

        ctk.CTkFrame(self.sidebar, height=1, fg_color="gray30").pack(fill="x", padx=12, pady=4)

        self.nav_btns = {}
        for label, key in [
            ("📂   Téléversement", "upload"),
            ("⚙️   Configuration", "config"),
            ("📋   Journal",       "log"),
        ]:
            b = ctk.CTkButton(self.sidebar, text=label, anchor="w", height=40,
                              fg_color="transparent", text_color=("gray10", "gray90"),
                              hover_color=("gray75", "gray28"),
                              font=ctk.CTkFont(size=13),
                              command=lambda k=key: self._show_tab(k))
            b.pack(fill="x", padx=6, pady=2)
            self.nav_btns[key] = b

        # Bouton « Aide » (fenêtre d'explications, pas un onglet)
        ctk.CTkButton(self.sidebar, text="❓   Aide", anchor="w", height=40,
                      fg_color="transparent", text_color=("gray10", "gray90"),
                      hover_color=("gray75", "gray28"),
                      font=ctk.CTkFont(size=13),
                      command=self._show_help).pack(fill="x", padx=6, pady=2)

        # Bouton « À propos » (fenêtre d'information, pas un onglet)
        ctk.CTkButton(self.sidebar, text="ℹ️   À propos", anchor="w", height=40,
                      fg_color="transparent", text_color=("gray10", "gray90"),
                      hover_color=("gray75", "gray28"),
                      font=ctk.CTkFont(size=13),
                      command=self._show_about).pack(fill="x", padx=6, pady=2)

        ctk.CTkLabel(self.sidebar, text=f"v{APP_VERSION}",
                     font=ctk.CTkFont(size=9), text_color="gray40").pack(side="bottom", pady=10)

        # Zone principale
        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.pack(side="right", fill="both", expand=True, padx=14, pady=14)

        self.tabs = {}
        self._build_tab_upload()
        self._build_tab_config()
        self._build_tab_log()

    def _show_tab(self, key: str):
        """Affiche l'onglet `key` et met en surbrillance son bouton de navigation."""
        for f in self.tabs.values():
            f.pack_forget()
        self.tabs[key].pack(fill="both", expand=True)
        for k, b in self.nav_btns.items():
            b.configure(fg_color=("gray75", "gray24") if k == key else "transparent")

    # ═════════════════════════════════════════════════════════════════════
    #  ONGLET TÉLÉVERSEMENT
    # ═════════════════════════════════════════════════════════════════════

    def _build_tab_upload(self):
        """Construit l'onglet Téléversement (sélection, réglages communs, liste, lancement)."""
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.tabs["upload"] = frame

        ctk.CTkLabel(frame, text="📂  Téléversement par lot",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", pady=(0, 10))

        # — Barre de sélection —
        sel = ctk.CTkFrame(frame, fg_color="transparent")
        sel.pack(fill="x", pady=(0, 6))

        ctk.CTkButton(sel, text="➕  Ajouter des fichiers", width=190,
                      command=self._add_files).pack(side="left", padx=(0, 8))
        ctk.CTkButton(sel, text="📁  Ajouter un dossier", width=190,
                      command=self._add_folder).pack(side="left", padx=(0, 8))
        ctk.CTkButton(sel, text="🗑  Vider la liste", width=140,
                      fg_color="gray35", hover_color="gray28",
                      command=self._clear_items).pack(side="left")

        self.count_lbl = ctk.CTkLabel(sel, text="0 vidéo(s)", text_color="gray",
                                      font=ctk.CTkFont(size=11))
        self.count_lbl.pack(side="right")

        # — Réglages communs (appliqués à tout le lot) —
        common = ctk.CTkFrame(frame)
        common.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(common, text="Réglages communs au lot",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=4,
                                                           padx=12, pady=(10, 4), sticky="w")

        ctk.CTkLabel(common, text="Type :").grid(row=1, column=0, padx=(12, 4), pady=8, sticky="e")
        self.type_combo = ctk.CTkComboBox(common, values=["(chargement…)"], width=200)
        self.type_combo.grid(row=1, column=1, padx=4, pady=8, sticky="w")

        ctk.CTkLabel(common, text="Visibilité :").grid(row=1, column=2, padx=(20, 4), pady=8, sticky="e")
        self.visibility_combo = ctk.CTkComboBox(
            common, width=200, values=["Brouillon / Privé", "Public"])
        self.visibility_combo.set("Brouillon / Privé")
        self.visibility_combo.grid(row=1, column=3, padx=4, pady=8, sticky="w")

        self.encode_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(common, text="Lancer l'encodage après le téléversement",
                        variable=self.encode_var).grid(row=2, column=0, columnspan=2,
                                                        padx=12, pady=(0, 6), sticky="w")

        # — Propriétaire des vidéos (choix EXPLICITE et OBLIGATOIRE) —
        # On impose un choix explicite du compte propriétaire avant tout envoi :
        # plus aucune attribution « devinée » automatiquement. Tant qu'aucun
        # propriétaire n'est défini, l'envoi est bloqué (voir _start_upload).
        ctk.CTkLabel(common, text="Propriétaire des vidéos :",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=4, column=0, columnspan=4, padx=12, pady=(6, 0), sticky="w")
        ctk.CTkButton(common, text="🎯  Choisir le propriétaire…", width=240,
                      command=self._choose_upload_owner).grid(
            row=5, column=0, columnspan=2, padx=12, pady=(2, 10), sticky="w")
        self.owner_status_lbl = ctk.CTkLabel(common, text="⚠️ à définir avant l'envoi",
                                             text_color="#f59e0b",
                                             font=ctk.CTkFont(size=12, weight="bold"))
        self.owner_status_lbl.grid(row=5, column=2, columnspan=2, padx=12, pady=(2, 10),
                                   sticky="w")

        # Propriétaires additionnels communs
        ctk.CTkButton(common, text="👥  Propriétaires additionnels…", width=240,
                      fg_color="gray35", hover_color="gray28",
                      command=self._edit_additional_owners).grid(
            row=2, column=2, columnspan=2, padx=12, pady=(0, 6), sticky="w")
        self.add_owners_lbl = ctk.CTkLabel(common, text="aucun", text_color="gray",
                                           font=ctk.CTkFont(size=11))
        self.add_owners_lbl.grid(row=3, column=2, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        common.columnconfigure(3, weight=1)

        # — Tableau des vidéos (titres éditables) —
        hint = ("Vérifiez / corrigez les titres avant l'envoi  —  "
                "💡 vous pouvez aussi glisser-déposer fichiers et dossiers ci-dessous :"
                if getattr(self, "dnd_ok", False) else
                "Vérifiez / corrigez les titres avant l'envoi :")
        ctk.CTkLabel(frame, text=hint, font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(2, 2))

        self.list_frame = ctk.CTkScrollableFrame(frame, height=240)
        self.list_frame.pack(fill="both", expand=True)

        # Activer le glisser-déposer sur la zone de liste
        if getattr(self, "dnd_ok", False):
            try:
                self.list_frame.drop_target_register(DND_FILES)
                self.list_frame.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

        empty_text = ("Aucune vidéo.\nGlissez-déposez ici des fichiers ou des dossiers,\n"
                      "ou utilisez les boutons ci-dessus."
                      if getattr(self, "dnd_ok", False) else
                      "Aucune vidéo.\nUtilisez « Ajouter des fichiers » ou « Ajouter un dossier ».")
        self._empty_hint = ctk.CTkLabel(self.list_frame, text=empty_text, text_color="gray")
        self._empty_hint.pack(pady=40)

        # — Lancement + progression —
        launch = ctk.CTkFrame(frame, fg_color="transparent")
        launch.pack(fill="x", pady=(8, 0))

        self.launch_btn = ctk.CTkButton(
            launch, text="🚀  Lancer le téléversement", height=40,
            fg_color="#16a34a", hover_color="#15803d",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_upload)
        self.launch_btn.pack(side="left")

        # Bouton « Relancer les échecs » : créé maintenant mais NON affiché
        # (pack_forget). Il n'apparaît qu'après un lot comportant des échecs,
        # et re-tente uniquement les vidéos en échec (voir _on_batch_done).
        self.retry_btn = ctk.CTkButton(
            launch, text="🔄  Relancer les échecs", height=40,
            fg_color="#f59e0b", hover_color="#d97706",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._retry_failed)
        self.retry_btn.pack(side="left", padx=(8, 0))
        self.retry_btn.pack_forget()   # masqué par défaut

        self.global_msg = ctk.CTkLabel(launch, text="", text_color="gray",
                                       font=ctk.CTkFont(size=12))
        self.global_msg.pack(side="left", padx=14)

        # Progression fichier courant
        self.file_progress = ctk.CTkProgressBar(frame)
        self.file_progress.pack(fill="x", pady=(8, 0))
        self.file_progress.set(0)
        self.file_progress_lbl = ctk.CTkLabel(frame, text="", text_color="gray",
                                              font=ctk.CTkFont(size=10))
        self.file_progress_lbl.pack(anchor="w")

        # Progression globale du lot
        self.batch_progress = ctk.CTkProgressBar(frame, progress_color="#16a34a")
        self.batch_progress.pack(fill="x", pady=(4, 0))
        self.batch_progress.set(0)

        # État initial du propriétaire (reflète un éventuel compte déjà enregistré).
        self._refresh_owner_status()

    # ── Ajout de fichiers / dossier ──────────────────────────────────────

    def _add_files(self):
        """Ouvre un sélecteur de fichiers et ajoute les vidéos choisies à la file."""
        paths = filedialog.askopenfilenames(
            title="Choisir des vidéos",
            filetypes=[("Vidéos", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv *.flv *.mpg *.mpeg"),
                       ("Tous les fichiers", "*.*")])
        self._add_paths(paths)

    def _add_folder(self):
        """Scanne un dossier (récursivement) et ajoute toutes les vidéos trouvées à la file."""
        folder = filedialog.askdirectory(title="Choisir un dossier de vidéos")
        if not folder:
            return
        found = []
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if os.path.splitext(name)[1].lower() in cfg.VIDEO_EXTENSIONS:
                    found.append(os.path.join(root, name))
        if not found:
            self.global_msg.configure(text="Aucune vidéo trouvée dans ce dossier.",
                                      text_color="#f59e0b")
            return
        self._add_paths(sorted(found))

    def _on_drop(self, event):
        """Glisser-déposer : ajoute les vidéos des fichiers/dossiers déposés."""
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        found = []
        for p in paths:
            p = p.strip().strip("{}")
            if not p:
                continue
            if os.path.isdir(p):
                for root, _d, names in os.walk(p):
                    for n in names:
                        if os.path.splitext(n)[1].lower() in cfg.VIDEO_EXTENSIONS:
                            found.append(os.path.join(root, n))
            elif os.path.isfile(p) and os.path.splitext(p)[1].lower() in cfg.VIDEO_EXTENSIONS:
                found.append(p)
        if found:
            self._show_tab("upload")
            self._add_paths(sorted(found))
            self.global_msg.configure(
                text=f"{len(found)} vidéo(s) ajoutée(s) par glisser-déposer.", text_color="#22c55e")
        else:
            self.global_msg.configure(
                text="Aucune vidéo reconnue dans les éléments déposés.", text_color="#f59e0b")

    def _add_paths(self, paths):
        """Ajoute des chemins à la file en évitant les doublons, puis rafraîchit l'affichage."""
        existing = {it.path for it in self.items}
        added = 0
        for p in paths:
            if p not in existing:
                self.items.append(UploadItem(p))
                existing.add(p)          # éviter les doublons dans un même lot
                added += 1
        if added:
            self._refresh_list()
            self._log(f"{added} vidéo(s) ajoutée(s) à la file.")

    def _clear_items(self):
        """Vide la file d'attente et rafraîchit l'affichage."""
        self.items.clear()
        self._refresh_list()

    def _refresh_list(self):
        """Reconstruit le tableau des vidéos en attente (nom, titre éditable, état)."""
        for w in self.list_frame.winfo_children():
            w.destroy()

        if not self.items:
            empty_text = ("Aucune vidéo.\nGlissez-déposez ici des fichiers ou des dossiers,\n"
                          "ou utilisez les boutons ci-dessus."
                          if getattr(self, "dnd_ok", False) else
                          "Aucune vidéo.\nUtilisez « Ajouter des fichiers » ou « Ajouter un dossier ».")
            ctk.CTkLabel(self.list_frame, text=empty_text, text_color="gray").pack(pady=40)
            self.count_lbl.configure(text="0 vidéo(s)")
            return

        # En-tête
        hdr = ctk.CTkFrame(self.list_frame, fg_color="gray22", corner_radius=4)
        hdr.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(hdr, text="Fichier", width=230, anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=8, pady=4)
        ctk.CTkLabel(hdr, text="Titre (éditable)", anchor="w",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=8, expand=True, fill="x")
        ctk.CTkLabel(hdr, text="État", width=110,
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="right", padx=8)

        for i, it in enumerate(self.items):
            row = ctk.CTkFrame(self.list_frame,
                               fg_color="gray17" if i % 2 == 0 else "gray14", corner_radius=4)
            row.pack(fill="x", pady=1)
            it.row = row

            # nom de fichier (tronqué) + taille
            try:
                size_mb = os.path.getsize(it.path) / (1024 * 1024)
                size_txt = f"{size_mb:.0f} Mo"
            except OSError:
                size_txt = "?"
            fname = it.filename if len(it.filename) <= 28 else it.filename[:25] + "…"
            ctk.CTkLabel(row, text=f"{fname}\n{size_txt}", width=230, anchor="w",
                         justify="left", font=ctk.CTkFont(size=11)).pack(side="left", padx=8, pady=4)

            # titre éditable
            it.title_var = ctk.StringVar(value=it.title)
            it.title_var.trace_add("write",
                                    lambda *_x, item=it: setattr(item, "title", item.title_var.get()))
            ctk.CTkEntry(row, textvariable=it.title_var).pack(
                side="left", padx=8, pady=6, expand=True, fill="x")

            # bouton supprimer
            ctk.CTkButton(row, text="✕", width=28, height=26,
                          fg_color="gray30", hover_color="#7f1d1d",
                          command=lambda item=it: self._remove_item(item)).pack(side="right", padx=4)

            # état
            it.status_lbl = ctk.CTkLabel(row, text=it.status, width=100,
                                         text_color="gray60", font=ctk.CTkFont(size=11))
            it.status_lbl.pack(side="right", padx=6)

        self.count_lbl.configure(text=f"{len(self.items)} vidéo(s)")

    def _remove_item(self, item: UploadItem):
        """Retire une vidéo de la file et rafraîchit l'affichage."""
        if item in self.items:
            self.items.remove(item)
            self._refresh_list()

    def _set_item_status(self, item: UploadItem, status: str, color="gray60"):
        """Met à jour le libellé d'état d'une vidéo dans la liste."""
        item.status = status
        if item.status_lbl:
            item.status_lbl.configure(text=status, text_color=color)

    # ── Propriétaires additionnels communs ───────────────────────────────

    def _edit_additional_owners(self):
        """Ouvre OwnerPicker pour choisir les co-propriétaires communs au lot."""
        if not self.api:
            self.global_msg.configure(text="Connectez-vous d'abord (onglet Configuration).",
                                      text_color="#f59e0b")
            return
        OwnerPicker(self, on_done=self._on_owners_picked,
                    preselected=dict(self.additional_owner_map))

    def _on_owners_picked(self, urls: list[str], labels: list[str]):
        """Callback d'OwnerPicker : mémorise les co-propriétaires choisis et met à jour le libellé."""
        self.additional_owner_urls = urls
        self.additional_owner_map = dict(zip(urls, labels))
        if urls:
            self.add_owners_lbl.configure(text=", ".join(labels)[:60], text_color="#22c55e")
        else:
            self.add_owners_lbl.configure(text="aucun", text_color="gray")

    # ── Propriétaire des vidéos (choix explicite et obligatoire) ─────────

    def _refresh_owner_status(self):
        """Met à jour le libellé d'état du propriétaire dans l'onglet Téléversement.

        • Aucun propriétaire défini  → « ⚠️ à définir avant l'envoi » (orange).
        • Propriétaire défini         → « ✅ [nom] » (vert).
        Appelée à la construction de l'onglet et à chaque changement de compte
        (choix manuel, présélection, détection automatique)."""
        if not hasattr(self, "owner_status_lbl"):
            return
        owner_url = self.config_data.get("agent_owner_url", "")
        name = self.config_data.get("agent_username", "")
        if owner_url:
            self.owner_status_lbl.configure(text=f"✅ {name or 'défini'}",
                                            text_color="#22c55e")
        else:
            self.owner_status_lbl.configure(text="⚠️ à définir avant l'envoi",
                                            text_color="#f59e0b")

    def _choose_upload_owner(self):
        """Ouvre le sélecteur pour choisir explicitement le PROPRIÉTAIRE des vidéos.

        Le compte choisi s'applique à TOUT le lot en cours. On présélectionne le
        compte du token (l'agent) pour que le choix se fasse en un clic, tout en
        restant modifiable.

        Détail technique important : OwnerPicker compare les URLs de comptes AVEC
        leur slash final. La clé de présélection doit donc être l'URL BRUTE du
        compte (telle que renvoyée par l'API), sinon rien n'apparaît coché."""
        if not self.api:
            self.global_msg.configure(text="Connectez-vous d'abord (onglet Configuration).",
                                      text_color="#f59e0b")
            self._show_tab("config")
            return

        def on_chosen(user: dict):
            # Enregistre le compte choisi comme propriétaire du lot.
            self.config_data["agent_username"] = user.get("username", "")
            self.config_data["agent_owner_url"] = user.get("url", "")
            cfg.save_config(self.config_data)
            # Cohérence avec l'onglet Configuration (filtre + coche) et la barre latérale.
            self.agent_lbl.configure(text=f"Dépôt au nom de :\n{user.get('username','')}")
            if hasattr(self, "agent_filter"):
                self.agent_filter.delete(0, "end")
                self.agent_filter.insert(0, user.get("username", ""))
                self._render_users()
            self._refresh_owner_status()
            self._log(f"Propriétaire des vidéos défini : {user.get('username','')}.")

        # Présélection = compte actuellement enregistré (URL brute → clé de coche).
        OwnerPicker(
            self, on_done=lambda *_: None, single=True, on_single=on_chosen,
            title="Choisir le propriétaire des vidéos",
            intro=("Au nom de quel compte les vidéos seront-elles déposées ?\n"
                   "Cliquez sur le compte concerné. Ce choix s'applique à tout le lot."),
            prefilter=self.config_data.get("agent_username", ""),
        )

    # ── Lancement du téléversement ───────────────────────────────────────

    def _start_upload(self):
        """Vérifie les prérequis (connexion, propriétaire OBLIGATOIRE, type) puis lance le lot."""
        if not self.api:
            self.global_msg.configure(text="Non connecté. Voir l'onglet Configuration.",
                                      text_color="#ef4444")
            return
        if not self.items:
            self.global_msg.configure(text="Aucune vidéo à téléverser.", text_color="#f59e0b")
            return

        # BLOCAGE VOLONTAIRE : aucun envoi tant que le propriétaire n'est pas
        # explicitement choisi. On prévient clairement et on ouvre le sélecteur,
        # sans rien envoyer (évite tout dépôt au mauvais nom).
        owner_url = self.config_data.get("agent_owner_url", "")
        if not owner_url:
            self.global_msg.configure(
                text="⚠️ Choisissez d'abord le propriétaire des vidéos.",
                text_color="#f59e0b")
            self._choose_upload_owner()
            return

        type_title = self.type_combo.get()
        type_url = self.type_map.get(type_title, "")
        if not type_url:
            self.global_msg.configure(text="Sélectionnez un type valide.", text_color="#f59e0b")
            return

        # Mémorise propriétaire et type pour une éventuelle relance des échecs.
        self._last_owner_url = owner_url
        self._last_type_url = type_url

        self.launch_btn.configure(state="disabled")
        self.retry_btn.configure(state="disabled")
        self.batch_progress.set(0)
        self._run(self._do_batch_upload, owner_url, type_url)

    @staticmethod
    def _file_size(path: str) -> int:
        """Taille d'un fichier en octets (0 si illisible)."""
        try:
            return os.path.getsize(path)
        except Exception:
            return 0

    @staticmethod
    def _search_term_for(filename: str) -> str:
        """Terme de recherche pour retrouver une vidéo créée par chunké (Pod la
        titre d'après le nom de fichier ASCII envoyé)."""
        base = os.path.splitext(os.path.basename(filename))[0]
        return PodChunkedSession._ascii_filename(base)

    def _verify_chunked_creation(self, search_term: str, pre_ids: set, creator_owner_url: str):
        """(Thread) Après un 504 à la finalisation, Pod termine la création côté
        serveur. On sonde l'API jusqu'à voir une vidéo NOUVELLE (id absent de
        pre_ids), créée par le VÉHICULE. Renvoie le dict vidéo, ou None après
        expiration de la fenêtre de vérification."""
        import time as _t
        deadline = _t.time() + cfg.CHUNK_VERIFY_TIMEOUT_S
        while _t.time() < deadline:
            try:
                cands = self.api.search_videos({"search": search_term, "limit": 25})
            except Exception:
                cands = []
            for v in cands:
                if v.get("id") in pre_ids:
                    continue
                own = v.get("owner")
                own_str = own if isinstance(own, str) else (
                    own.get("url", "") if isinstance(own, dict) else "")
                if creator_owner_url and own_str and creator_owner_url.rstrip("/") not in own_str.rstrip("/"):
                    continue
                self._ui(self._log, f"✓ Vidéo apparue après finalisation serveur : {v.get('slug')}")
                return v
            remaining = max(0, int(deadline - _t.time()))
            self._ui(self.global_msg.configure,
                     text=f"⏳ Finalisation côté serveur (gros fichier)… vérification, "
                          f"{remaining//60} min {remaining%60}s restantes",
                     text_color="#f59e0b")
            _t.sleep(cfg.CHUNK_VERIFY_INTERVAL_S)
        return None

    @staticmethod
    def _est_coupure_reseau(err: Exception) -> bool:
        """Cette erreur vient-elle d'une coupure de connexion (et non d'un refus
        du serveur) ?

        On ne veut replier sur l'envoi par morceaux QUE dans ce cas. Un refus
        métier (400 champ manquant, 403 droits insuffisants…) échouerait de la
        même façon en chunké : le rejouer ne ferait que perdre du temps et
        risquerait de créer un doublon.

        Signature typique de la coupure par la passerelle :
        « SSLEOFError: EOF occurred in violation of protocol ».
        """
        texte = f"{getattr(err, 'body', '')} {err}".lower()
        indices = ("sslerror", "ssleoferror", "eof occurred",
                   "connection aborted", "connection reset",
                   "max retries exceeded", "connectionerror",
                   "remotedisconnected", "broken pipe")
        # `status` vaut 0 quand aucune réponse HTTP n'a été reçue (vraie coupure).
        sans_reponse = getattr(err, "status", 0) in (0, 502, 503, 504)
        return sans_reponse and any(i in texte for i in indices)

    def _do_batch_upload(self, owner_url: str, type_url: str):
        """(Thread) Téléverse chaque vidéo, ajoute les crédits, lance l'encodage, suit la progression.

        Les vidéos déjà réussies (it.done) sont ignorées : cette méthode sert
        aussi bien au 1ᵉʳ envoi qu'à la RELANCE des seuls échecs."""
        is_draft = self.visibility_combo.get().startswith("Brouillon")
        do_encode = self.encode_var.get()
        total = len(self.items)
        ok = 0
        chunked = None      # session véhicule DEPOT, ouverte à la 1re nécessité

        for idx, it in enumerate(self.items, 1):
            # On saute les vidéos déjà téléversées avec succès (utile en relance).
            if it.done:
                ok += 1
                self._ui(self.batch_progress.set, idx / total)
                continue

            self._ui(self._set_item_status, it, "en cours", "#3b82f6")
            self._ui(self.file_progress.set, 0)
            self._ui(self.global_msg.configure,
                     text=f"Téléversement {idx}/{total} : {it.title}", text_color="gray")

            def progress(sent, tot, item=it):
                # Callback de progression : met à jour la barre du fichier en cours
                # (fraction envoyée) et le libellé « Mo envoyés / Mo total ».
                frac = sent / tot if tot else 0
                self._ui(self.file_progress.set, frac)
                self._ui(self.file_progress_lbl.configure,
                         text=f"{item.filename} — {sent/1024/1024:.0f} / {tot/1024/1024:.0f} Mo")

            # Callback de relance : tracé dans le Journal + statut « ⟳ essai N ».
            def on_retry(attempt, total_attempts, message, item=it):
                self._ui(self._set_item_status, item,
                         f"⟳ essai {attempt + 1}/{total_attempts}", "#f59e0b")
                self._ui(self._log,
                         f"Relance {item.title} : {message} (essai {attempt}/{total_attempts})")

            # `big` peut être RÉÉVALUÉ : si l'envoi direct est coupé par la
            # passerelle, on repasse ici en forçant la voie chunkée.
            big = self._file_size(it.path) > cfg.CHUNK_THRESHOLD_BYTES
            try:
                if big:
                    # ── Gros fichier : MORCEAUX via le VÉHICULE DEPOT (embarqué) ──
                    if chunked is None:
                        chunked = PodChunkedSession(
                            self.config_data.get("url", ""),
                            self.vehicle_username, self.vehicle_password)
                        chunked.login()
                        self._ui(self._log, "Session véhicule ouverte (upload chunké).")
                    self._ui(self._log,
                             f"Gros fichier (> {cfg.CHUNK_THRESHOLD_BYTES//1024//1024} Mo) : "
                             f"bascule chunkée pour {it.title}.")
                    search_term = self._search_term_for(it.filename)
                    try:
                        pre_ids = {v.get("id") for v in
                                   self.api.search_videos({"search": search_term, "limit": 25})}
                    except Exception:
                        pre_ids = set()
                    # 1) Envoi par morceaux → vidéo créée au nom du VÉHICULE.
                    video = None
                    try:
                        slug = chunked.upload_video_chunked(
                            it.path, chunk_size=cfg.CHUNK_SIZE_BYTES,
                            progress_cb=progress, retry_cb=on_retry)
                    except PodChunkedError as ce:
                        if ce.status in (502, 503, 504):
                            self._ui(self._log,
                                     f"⏳ Finalisation coupée par la passerelle (HTTP {ce.status}) "
                                     "— Pod termine côté serveur, vérification en cours…")
                            self._ui(self._set_item_status, it, "⏳ finalisation serveur", "#f59e0b")
                            video = self._verify_chunked_creation(
                                search_term, pre_ids, self.vehicle_owner_url)
                            if not video:
                                raise
                            slug = video.get("slug", "")
                        else:
                            raise
                    it.slug = slug
                    if video is None:
                        video = self.api.get_video_by_slug(slug)
                    it.video_url = video.get("url", "") if isinstance(video, dict) else ""
                    # 2) RÉATTRIBUTION au propriétaire choisi + métadonnées (token enseignant).
                    #    Si le PATCH owner échoue, la vidéo reste au nom du véhicule :
                    #    on le signale FORT (jamais en silence).
                    if video:
                        patch = {
                            "owner": owner_url,                      # ← propriétaire CHOISI
                            "title": it.title or it.filename,
                            "type": type_url,
                            "is_draft": is_draft,
                            "main_lang": self.config_data.get("main_lang", "fr"),
                            "cursus": self.config_data.get("cursus", "0"),
                        }
                        if self.additional_owner_urls:
                            patch["additional_owners"] = list(self.additional_owner_urls)
                        try:
                            self.api.patch_video(video, patch)
                        except Exception as e:
                            it.error = f"réattribution échouée : {e}"
                            self._ui(self._set_item_status, it, "⚠️ NON réattribuée", "#ef4444")
                            self._ui(self._log,
                                     f"⚠️⚠️ {it.title} : vidéo créée (slug={slug}) mais NON "
                                     f"réattribuée à {owner_url} — RESTE au nom du véhicule ! "
                                     f"Détail : {e}")
                            self._ui(self.batch_progress.set, idx / total)
                            continue
                    else:
                        self._ui(self._log,
                                 f"⚠️ Vidéo créée (slug={slug}) mais introuvable via l'API pour "
                                 "réattribution — à vérifier côté web.")
                else:
                    # ── Fichier sous le seuil : upload classique par TOKEN ──
                    try:
                        video = self.api.upload_video(
                            it.path, it.title or it.filename, owner_url, type_url,
                            main_lang=self.config_data.get("main_lang", "fr"),
                            cursus=self.config_data.get("cursus", "0"),
                            is_draft=is_draft,
                            additional_owner_urls=self.additional_owner_urls,
                            site_urls=self.site_urls,
                            progress_cb=progress,
                            retry_cb=on_retry,
                        )
                    except PodAPIError as e:
                        # REPLI AUTOMATIQUE SUR L'ENVOI PAR MORCEAUX.
                        #
                        # L'envoi direct peut être coupé par la passerelle même
                        # sous le seuil : au-delà d'environ une minute de
                        # transfert, nginx ferme la connexion (erreur SSL « EOF
                        # occurred in violation of protocol »). Le seuil en
                        # octets ne suffit donc pas : ce qui compte est la DURÉE
                        # de l'envoi, qui dépend du débit montant.
                        #
                        # Réessayer à l'identique échoue invariablement. On
                        # bascule donc sur la voie chunkée, conçue pour résister
                        # à ces coupures, plutôt que d'abandonner.
                        if not self._est_coupure_reseau(e):
                            raise
                        self._ui(self._log,
                                 f"⚠️ {it.title} : envoi direct coupé par le serveur. "
                                 "Bascule automatique sur l'envoi par morceaux…")
                        self._ui(self._set_item_status, it,
                                 "⟳ envoi par morceaux", "#f59e0b")
                        if chunked is None:
                            chunked = PodChunkedSession(
                                self.config_data.get("url", ""),
                                self.vehicle_username, self.vehicle_password)
                            chunked.login()
                            self._ui(self._log, "Session véhicule ouverte (repli chunké).")
                        slug = chunked.upload_video_chunked(
                            it.path, chunk_size=cfg.CHUNK_SIZE_BYTES,
                            progress_cb=progress, retry_cb=on_retry)
                        video = self.api.get_video_by_slug(slug) if hasattr(
                            self.api, "get_video_by_slug") else None
                        if not video:
                            raise PodAPIError(
                                f"Vidéo envoyée par morceaux (slug={slug}) mais introuvable "
                                "via l'API — à vérifier côté web.", 0, "")
                        # La vidéo est née au nom du véhicule : on la réattribue.
                        patch = {
                            "owner": owner_url,
                            "title": it.title or it.filename,
                            "type": type_url,
                            "is_draft": is_draft,
                        }
                        if self.additional_owner_urls:
                            patch["additional_owners"] = list(self.additional_owner_urls)
                        try:
                            self.api.patch_video(video, patch)
                            self._ui(self._log,
                                     f"✅ {it.title} : repli par morceaux réussi (slug={slug}).")
                        except Exception as pe:
                            it.error = f"réattribution échouée : {pe}"
                            self._ui(self._set_item_status, it, "⚠️ NON réattribuée", "#ef4444")
                            self._ui(self._log,
                                     f"⚠️⚠️ {it.title} : vidéo créée (slug={slug}) mais NON "
                                     f"réattribuée — RESTE au nom du véhicule ! Détail : {pe}")
                    it.slug = video.get("slug", "") if isinstance(video, dict) else ""
                    it.video_url = video.get("url", "") if isinstance(video, dict) else ""

                # Contributeurs communs
                for c in self.common_contributors:
                    try:
                        self.api.add_contributor(it.video_url, c["name"], c.get("email", ""),
                                                 c.get("role", "author"), c.get("weblink", ""))
                    except Exception as e:
                        self._ui(self._log, f"Contributeur non ajouté ({it.title}) : {e}")

                # Encodage
                if do_encode and it.slug:
                    try:
                        self.api.launch_encoding(it.slug)
                    except Exception as e:
                        self._ui(self._log, f"Encodage non lancé ({it.title}) : {e}")

                it.done = True            # marque le succès (ne sera pas relancé)
                it.error = ""
                ok += 1
                self._ui(self._set_item_status, it, "✅ terminé", "#22c55e")
                self._ui(self._log,
                         f"Téléversé{' (chunké)' if big else ''} : {it.title}  (slug={it.slug})")

            except PodChunkedError as e:
                it.error = f"{e} — {e.body}"
                self._ui(self._set_item_status, it, "❌ échec", "#ef4444")
                self._ui(self._log, f"ÉCHEC chunké {it.title} : {e} | {e.body[:200]}")
            except PodAPIError as e:
                it.error = f"{e} — {e.body}"
                self._ui(self._set_item_status, it, "❌ échec", "#ef4444")
                self._ui(self._log, f"ÉCHEC {it.title} : {e} | {e.body[:200]}")
            except Exception as e:
                it.error = str(e)
                self._ui(self._set_item_status, it, "❌ échec", "#ef4444")
                self._ui(self._log, f"ÉCHEC {it.title} : {e}")

            self._ui(self.batch_progress.set, idx / total)

        # Fermeture propre de la session véhicule si elle a été ouverte.
        if chunked is not None:
            chunked.close()

        self._ui(self._on_batch_done, ok, total)

    def _on_batch_done(self, ok: int, total: int):
        """Réactive l'interface, affiche le bilan et gère le bouton « Relancer les échecs »."""
        self.launch_btn.configure(state="normal")
        self.retry_btn.configure(state="normal")
        self.file_progress.set(0)
        self.file_progress_lbl.configure(text="")
        color = "#22c55e" if ok == total else "#f59e0b"
        self.global_msg.configure(text=f"Terminé : {ok}/{total} vidéo(s) téléversée(s).", text_color=color)
        self._log(f"Lot terminé : {ok}/{total} réussis.")

        # Nombre de vidéos encore en échec (non abouties).
        nb_echecs = sum(1 for it in self.items if not it.done)
        if nb_echecs:
            # Affiche le bouton de relance avec le décompte.
            self.retry_btn.configure(text=f"🔄  Relancer les échecs ({nb_echecs})")
            self.retry_btn.pack(side="left", padx=(8, 0))
        else:
            # Tout est passé : on masque le bouton.
            self.retry_btn.pack_forget()

    def _retry_failed(self):
        """Relance UNIQUEMENT les vidéos en échec, sans re-sélectionner de fichiers.

        Réutilise le propriétaire et le type déjà choisis. Les vidéos réussies
        (it.done) sont ignorées par _do_batch_upload."""
        if not self.api:
            return
        # Propriétaire et type mémorisés lors du dernier lancement.
        owner_url = getattr(self, "_last_owner_url", "") or self.config_data.get("agent_owner_url", "")
        type_url = getattr(self, "_last_type_url", "") or self.type_map.get(self.type_combo.get(), "")
        if not owner_url or not type_url:
            self.global_msg.configure(text="Propriétaire ou type manquant pour la relance.",
                                      text_color="#f59e0b")
            return
        # Remet les échecs en « en attente » pour un affichage propre.
        for it in self.items:
            if not it.done:
                self._set_item_status(it, "en attente", "gray60")
        self.launch_btn.configure(state="disabled")
        self.retry_btn.configure(state="disabled")
        self._log("Relance des vidéos en échec…")
        self._run(self._do_batch_upload, owner_url, type_url)
    def _build_tab_config(self):
        """Construit l'onglet Configuration (connexion API + choix de l'agent déposant)."""
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.tabs["config"] = frame

        ctk.CTkLabel(frame, text="⚙️  Configuration",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", pady=(0, 10))

        # — Connexion API —
        api_box = ctk.CTkFrame(frame)
        api_box.pack(fill="x")
        ctk.CTkLabel(api_box, text="Connexion à l'instance Pod (token personnel ou de service)",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=3,
                                                           padx=12, pady=(12, 4), sticky="w")

        ctk.CTkLabel(api_box, text="URL :", width=110, anchor="e").grid(row=1, column=0, padx=8, pady=8)
        self.url_entry = ctk.CTkEntry(api_box, width=430)
        self.url_entry.insert(0, self.config_data.get("url", ""))
        self.url_entry.grid(row=1, column=1, padx=8, pady=8, sticky="ew")

        ctk.CTkLabel(api_box, text="Token :", width=110, anchor="e").grid(row=2, column=0, padx=8, pady=8)
        self.token_entry = ctk.CTkEntry(api_box, width=430, show="*")
        if self.token:
            self.token_entry.insert(0, self.token)
        self.token_entry.grid(row=2, column=1, padx=8, pady=8, sticky="ew")

        self.show_token = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(api_box, text="Afficher", variable=self.show_token,
                        command=lambda: self.token_entry.configure(
                            show="" if self.show_token.get() else "*")).grid(row=2, column=2, padx=4)

        btn_row = ctk.CTkFrame(api_box, fg_color="transparent")
        btn_row.grid(row=3, column=1, columnspan=2, padx=8, pady=10, sticky="w")
        ctk.CTkButton(btn_row, text="🔌  Tester & se connecter", fg_color="#16a34a",
                      hover_color="#15803d", command=self._connect).pack(side="left")
        ctk.CTkButton(btn_row, text="🚪  Oublier le token / Se déconnecter", width=260,
                      fg_color="gray35", hover_color="#7f1d1d",
                      command=self._forget_token).pack(side="left", padx=10)
        api_box.columnconfigure(1, weight=1)

        self.config_msg = ctk.CTkLabel(frame, text="", font=ctk.CTkFont(size=12))
        self.config_msg.pack(anchor="w", pady=4)

        ctk.CTkFrame(frame, height=1, fg_color="gray30").pack(fill="x", pady=8)

        # — Agent déposant —
        agent_box = ctk.CTkFrame(frame)
        agent_box.pack(fill="x")
        ctk.CTkLabel(agent_box, text="Agent déposant (propriétaire des vidéos)",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=3,
                                                           padx=12, pady=(12, 2), sticky="w")
        ctk.CTkLabel(agent_box, text="Les vidéos déposées appartiendront à ce compte Pod.",
                     text_color="gray70", font=ctk.CTkFont(size=11)).grid(
            row=1, column=0, columnspan=3, padx=12, pady=(0, 6), sticky="w")

        self.agent_filter = ctk.CTkEntry(agent_box, width=300,
                                         placeholder_text="🔍 nom / identifiant…")
        self.agent_filter.grid(row=2, column=0, columnspan=2, padx=8, pady=8, sticky="ew")
        self.agent_filter.bind("<KeyRelease>", lambda e: self._render_users())
        ctk.CTkButton(agent_box, text="🔄  Recharger", width=130,
                      command=lambda: self._run(self._load_all_users)).grid(row=2, column=2, padx=8, pady=8)

        self.users_count_lbl = ctk.CTkLabel(agent_box, text="", text_color="gray",
                                            font=ctk.CTkFont(size=11))
        self.users_count_lbl.grid(row=3, column=0, columnspan=3, padx=12, sticky="w")

        self.agent_results = ctk.CTkScrollableFrame(agent_box, height=220)
        self.agent_results.grid(row=4, column=0, columnspan=3, padx=12, pady=(0, 10), sticky="ew")
        agent_box.columnconfigure(1, weight=1)

        # — Aide token —
        help_box = ctk.CTkFrame(frame, fg_color="gray18", corner_radius=8)
        help_box.pack(fill="x", pady=8)
        ctk.CTkLabel(help_box, text="ℹ️  Obtenir le token",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            help_box,
            text="Le token est fourni par le service informatique, ou créé par un "
                 "administrateur dans  <URL>/admin/authtoken/  → « Add token ».\n"
                 "⚠️ Le token hérite des droits du compte associé. Il est stocké chiffré "
                 "dans le coffre-fort de votre système (Keychain / Credential Manager), "
                 "par poste — jamais dans l'application.",
            justify="left", text_color="gray70", wraplength=820).pack(anchor="w", padx=14, pady=(0, 12))

    def _forget_token(self):
        """Efface le token de ce poste et se déconnecte."""
        cfg.clear_token()
        self.token = ""
        self.api = None
        self.all_users = []
        if hasattr(self, "token_entry"):
            self.token_entry.delete(0, "end")
        if hasattr(self, "agent_results"):
            self._render_users()
        if hasattr(self, "users_count_lbl"):
            self.users_count_lbl.configure(text="")
        self._set_status(False)
        self.config_msg.configure(
            text="🚪  Token effacé de ce poste. Saisissez-le à nouveau pour vous reconnecter.",
            text_color="#f59e0b")
        self._log("Token effacé du poste — déconnexion.")

    def _connect(self):
        """Lit URL + token saisis et lance la connexion en arrière-plan."""
        url = self.url_entry.get().strip()
        token = self.token_entry.get().strip()
        if not url or not token:
            self.config_msg.configure(text="URL et token requis.", text_color="#ef4444")
            return
        self.config_msg.configure(text="⏳  Connexion…", text_color="gray")
        self._run(self._do_connect, url, token)

    def _do_connect(self, url, token):
        """(Thread) Teste la connexion à l'instance puis bascule l'UI selon le résultat."""
        try:
            api = PodAPI(url, token)
            count = api.test_connection()
            self._ui(self._on_connected, api, url, token, count)
        except Exception as e:
            self._ui(self.config_msg.configure, text=f"❌  Échec : {e}", text_color="#ef4444")
            self._ui(self._set_status, False)
            # Assistant de première utilisation : remonter l'erreur dans sa fenêtre.
            if self._post_connect_err:
                self._ui(self._post_connect_err, str(e))

    def _on_connected(self, api, url, token, count):
        """Connexion réussie : mémorise le client, enregistre le token, charge types et comptes."""
        self.api = api
        self.token = token
        self.config_data["url"] = url
        cfg.save_token(token)
        cfg.save_config(self.config_data)
        self._set_status(True)
        self.config_msg.configure(text=f"✅  Connecté — {count} vidéo(s) accessibles.",
                                  text_color="#22c55e")
        self._run(self._load_types)
        self._run(self._load_all_users)
        self._run(self._resolve_vehicle_owner)   # URL Pod de DEPOT (pour la vérif post-504)
        # Assistant de première utilisation : signaler la réussite (ferme l'étape 1).
        if self._post_connect_ok:
            cb = self._post_connect_ok
            self._post_connect_ok = None
            self._post_connect_err = None
            cb()

    def _resolve_vehicle_owner(self):
        """(Thread) Résout l'URL Pod du compte véhicule DEPOT (correspondance
        EXACTE de l'identifiant), pour reconnaître après un 504 la vidéo qu'il
        vient de créer. Aucun repli sur un autre compte."""
        uname = (self.vehicle_username or "").strip()
        if not (self.api and uname):
            return
        try:
            found = None
            for u in (self.api.search_users(uname) or []):
                if (u.get("username", "") or "").strip().lower() == uname.lower():
                    found = u
                    break
            self.vehicle_owner_url = found["url"] if (found and found.get("url")) else ""
            if not self.vehicle_owner_url:
                self._ui(self._log,
                         f"⚠️ Compte véhicule « {uname} » non résolu — récupération après 504 moins précise.")
        except Exception as e:
            self._ui(self._log, f"⚠️ Résolution du compte véhicule impossible : {e}")

    def _auto_connect(self):
        """(Thread) Reconnexion automatique au démarrage si un token est déjà enregistré."""
        try:
            api = PodAPI(self.config_data["url"], self.token)
            count = api.test_connection()
            self._ui(self._on_auto_ok, api, count)
        except Exception:
            self._ui(self._set_status, False)

    def _on_auto_ok(self, api, count):
        """Reconnexion auto réussie : active l'état connecté et charge types et comptes."""
        self.api = api
        self._set_status(True)
        u = self.config_data.get("agent_username", "")
        if u:
            self.agent_lbl.configure(text=f"Dépôt au nom de :\n{u}")
        self._refresh_owner_status()
        self._run(self._load_types)
        self._run(self._load_all_users)
        self._run(self._resolve_vehicle_owner)

    # ── Assistant de première utilisation ────────────────────────────────

    def _first_run_wizard(self):
        """Assistant de PREMIÈRE UTILISATION (aucun token enregistré sur le poste).

        But : guider un enseignant non informaticien en deux étapes simples.
          • Étape 1 (cette fenêtre) : coller le token et se connecter. L'adresse
            de l'instance est déjà renseignée (modifiable si vraiment nécessaire).
          • Étape 2 : le choix du compte déposant s'ouvre automatiquement après la
            connexion (sauf si le compte est détecté avec certitude).
        Un lien « Configurer manuellement » ferme l'assistant et bascule sur
        l'onglet Configuration, pour les cas particuliers.
        """
        win = ctk.CTkToplevel(self)
        win.title("Bienvenue — première utilisation")
        win.geometry("540x470")
        win.resizable(False, False)
        _focus_toplevel(win, self)

        # — Logo (réutilise le mécanisme de la fenêtre À propos) —
        if HAS_PIL:
            try:
                logo_path = resource_path(os.path.join("assets", "logo_ut.png"))
                if os.path.exists(logo_path):
                    pil = PILImage.open(logo_path)
                    W = 150
                    H = round(W * pil.height / pil.width)
                    img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(W, H))
                    win._wiz_img = img   # référence pour éviter le ramasse-miettes
                    card = ctk.CTkFrame(win, fg_color="white", corner_radius=8)
                    card.pack(padx=20, pady=(16, 4))
                    ctk.CTkLabel(card, image=img, text="").pack(padx=10, pady=8)
            except Exception:
                pass

        # — Titre + intro —
        ctk.CTkLabel(win, text="Bienvenue dans Pod Téléverseur",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(4, 0))
        ctk.CTkLabel(win, text="Étape 1 sur 2 — Connexion",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#3b82f6").pack(pady=(2, 0))
        ctk.CTkLabel(win, text="Collez le token fourni par le service informatique,\n"
                              "puis cliquez sur « Se connecter ».",
                     justify="center", text_color="gray80",
                     font=ctk.CTkFont(size=12)).pack(pady=(2, 10))

        form = ctk.CTkFrame(win, fg_color="transparent")
        form.pack(fill="x", padx=24)

        # — Adresse de l'instance (pré-remplie, discrète) —
        ctk.CTkLabel(form, text="Adresse (déjà renseignée) :",
                     text_color="gray60", font=ctk.CTkFont(size=11)).pack(anchor="w")
        url_entry = ctk.CTkEntry(form)
        url_entry.insert(0, self.config_data.get("url", "https://videos.utoulouse.fr"))
        url_entry.pack(fill="x", pady=(0, 8))

        # — Token (champ principal, masqué + case « Afficher ») —
        ctk.CTkLabel(form, text="Token :",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
        token_entry = ctk.CTkEntry(form, show="*", placeholder_text="collez le token ici")
        token_entry.pack(fill="x", pady=(0, 2))
        show_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(form, text="Afficher le token", variable=show_var,
                        font=ctk.CTkFont(size=11),
                        command=lambda: token_entry.configure(show="" if show_var.get() else "*")
                        ).pack(anchor="w", pady=(0, 6))

        # — Message d'état / d'erreur —
        msg = ctk.CTkLabel(win, text="", font=ctk.CTkFont(size=12), wraplength=480)
        msg.pack(pady=(2, 6))

        # — Logique de connexion (réutilise le flux existant via les hooks) —
        def do_connect():
            url = url_entry.get().strip()
            token = token_entry.get().strip()
            if not url or not token:
                msg.configure(text="Merci de coller le token avant de continuer.",
                              text_color="#ef4444")
                return
            msg.configure(text="⏳  Connexion…", text_color="gray")

            def on_ok():
                # Connexion réussie → on ferme l'étape 1. L'étape 2 (choix du
                # compte déposant) s'ouvrira automatiquement quand la liste des
                # comptes sera chargée (via _after_detection).
                try:
                    win.destroy()
                except Exception:
                    pass
                self._show_tab("upload")

            def on_err(e):
                msg.configure(text=f"❌  Échec : {e}\nVérifiez le token et réessayez.",
                              text_color="#ef4444")

            self._post_connect_ok = on_ok
            self._post_connect_err = on_err
            # Tenir l'onglet Configuration cohérent avec ce qui est saisi ici.
            if hasattr(self, "url_entry"):
                self.url_entry.delete(0, "end"); self.url_entry.insert(0, url)
            if hasattr(self, "token_entry"):
                self.token_entry.delete(0, "end"); self.token_entry.insert(0, token)
            self._run(self._do_connect, url, token)

        def manual():
            # Sortie de secours : annuler l'assistant et aller dans Configuration.
            self._post_connect_ok = None
            self._post_connect_err = None
            try:
                win.destroy()
            except Exception:
                pass
            self._show_tab("config")

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=24, pady=(4, 12))
        ctk.CTkButton(btns, text="Se connecter", height=40,
                      fg_color="#16a34a", hover_color="#15803d",
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=do_connect).pack(fill="x")
        ctk.CTkButton(btns, text="Configurer manuellement", height=30,
                      fg_color="transparent", text_color="gray60",
                      hover_color=("gray80", "gray25"),
                      font=ctk.CTkFont(size=11), command=manual).pack(fill="x", pady=(6, 0))

        # La croix de fermeture équivaut à « Configurer manuellement ».
        win.protocol("WM_DELETE_WINDOW", manual)
        # Entrée = se connecter (confort).
        token_entry.bind("<Return>", lambda e: do_connect())

    def _set_status(self, ok: bool):
        """Met à jour l'indicateur de connexion (pastille + libellé) de la barre latérale."""
        self.status_dot.configure(text="🟢" if ok else "🔴")
        self.status_lbl.configure(text="Connecté" if ok else "Non connecté",
                                  text_color="#22c55e" if ok else "#ef4444")

    def _load_types(self):
        """(Thread) Charge les types de vidéo et les sites (champ requis à l'upload)."""
        try:
            self.types = self.api.get_types()
            self.type_map = {t.get("title", f"type-{t.get('id')}"): t.get("url", "")
                             for t in self.types}
            titles = list(self.type_map.keys()) or ["(aucun type)"]
            self._ui(self.type_combo.configure, values=titles)
            self._ui(self.type_combo.set, titles[0])
        except Exception as e:
            self._ui(self._log, f"Impossible de charger les types : {e}")
        # Sites (champ requis à l'upload sur instance multi-établissements)
        try:
            sites = self.api.get_sites()
            self.site_urls = [s.get("url", "") for s in sites if s.get("url")]
            if self.site_urls:
                names = ", ".join(s.get("name", s.get("domain", "?")) for s in sites)
                self._ui(self._log, f"Site(s) détecté(s) : {names}")
            else:
                self._ui(self._log, "⚠️ Aucun site retourné par /rest/sites/ — l'upload pourrait échouer.")
        except Exception as e:
            self._ui(self._log, f"Impossible de charger les sites : {e}")

    def _load_all_users(self):
        """(Thread) Charge tous les comptes Pod (paginé) et rafraîchit les vues qui en dépendent."""
        if not self.api:
            self._ui(self.users_count_lbl.configure,
                     text="Connectez-vous d'abord.", text_color="#f59e0b")
            return
        self._ui(self.users_count_lbl.configure,
                 text="⏳  Chargement de la liste des utilisateurs…", text_color="gray")
        self._ui(self._log, "Chargement des utilisateurs (/rest/users/)…")
        try:
            users = self.api.get_all_users()
            users.sort(key=lambda u: (u.get("username") or "").lower())
            self.all_users = users
            self._ui(self._render_users)
            # Présélection : pré-remplir le filtre avec le propriétaire enregistré
            ag = self.config_data.get("agent_username", "")
            if ag:
                self._ui(self._preselect_agent, ag)
            elif not self.config_data.get("owner_prompt_seen"):
                # 1ʳᵉ connexion sans compte enregistré et fenêtre jamais montrée :
                # on tente la détection automatique (Piste 1), sinon on ouvrira la
                # fenêtre « Choisissez le compte déposant ». Une seule fois : ensuite
                # l'utilisateur passe par l'onglet Configuration.
                self._detect_token_owner()
            if users:
                self._ui(self.users_count_lbl.configure,
                         text=f"✅  {len(users)} utilisateur(s) chargé(s). Filtrez puis cliquez pour choisir.",
                         text_color="#22c55e")
                self._ui(self._log, f"Utilisateurs chargés : {len(users)}.")
            else:
                self._ui(self.users_count_lbl.configure,
                         text="⚠️  Aucun utilisateur renvoyé. Le compte du token n'a peut-être "
                              "pas le droit de lister les utilisateurs (compte superutilisateur requis).",
                         text_color="#f59e0b")
                self._ui(self._log, "⚠️ /rest/users/ a renvoyé 0 utilisateur — vérifiez les droits du token "
                                    "(ou lancez verifier.py).")
        except Exception as e:
            self._ui(self.users_count_lbl.configure, text=f"❌  Erreur : {e}", text_color="#ef4444")
            self._ui(self._log, f"❌ Erreur chargement utilisateurs : {e}")

    def _user_label(self, u: dict) -> str:
        """Libellé lisible d'un compte : « identifiant — Prénom Nom »."""
        return f"{u.get('username','?')} — {u.get('first_name','')} {u.get('last_name','')}".strip()

    def _preselect_agent(self, username: str):
        """Présélection : pré-remplit le filtre avec le propriétaire enregistré.
        La liste reste entièrement utilisable : effacer le filtre permet de
        choisir un autre compte (le support dépose sur différents comptes)."""
        if hasattr(self, "agent_filter") and not self.agent_filter.get().strip():
            self.agent_filter.insert(0, username)
            self._render_users()
        self._refresh_owner_status()

    def _render_users(self):
        """Affiche la liste filtrée des comptes pour choisir l'agent déposant."""
        flt = self.agent_filter.get().strip().lower() if hasattr(self, "agent_filter") else ""
        for w in self.agent_results.winfo_children():
            w.destroy()

        if not self.all_users:
            ctk.CTkLabel(self.agent_results,
                         text="Liste non chargée. Cliquez sur « Recharger ».",
                         text_color="gray").pack(pady=10)
            return

        matches = [u for u in self.all_users if not flt or flt in self._user_label(u).lower()]
        CAP = 300  # éviter de créer des milliers de boutons (Tk gèlerait)
        current_username = self.config_data.get("agent_username", "")

        for u in matches[:CAP]:
            is_current = (u.get("username", "") == current_username)
            label = ("✅  " if is_current else "      ") + self._user_label(u)
            ctk.CTkButton(self.agent_results, text=label, anchor="w",
                          fg_color=("gray75", "gray30") if is_current else "transparent",
                          text_color=("gray10", "gray90"), hover_color=("gray75", "gray28"),
                          height=28, font=ctk.CTkFont(size=12),
                          command=lambda uu=u: self._pick_agent(uu)).pack(fill="x", pady=1)

        if len(matches) > CAP:
            ctk.CTkLabel(self.agent_results,
                         text=f"… +{len(matches) - CAP} autres. Affinez le filtre.",
                         text_color="gray").pack(pady=4)
        elif not matches:
            ctk.CTkLabel(self.agent_results,
                         text="Aucun résultat ne correspond au filtre.",
                         text_color="gray").pack(pady=8)

    def _pick_agent(self, user: dict):
        """Enregistre le compte choisi comme propriétaire par défaut des dépôts."""
        self.config_data["agent_username"] = user.get("username", "")
        self.config_data["agent_owner_url"] = user.get("url", "")
        cfg.save_config(self.config_data)
        self.agent_lbl.configure(text=f"Dépôt au nom de :\n{user.get('username','')}")
        self.config_msg.configure(
            text=f"✅  Propriétaire des vidéos : {user.get('username','')}", text_color="#22c55e")
        if hasattr(self, "agent_results"):
            self._render_users()   # met à jour la coche ✅
        self._refresh_owner_status()   # met à jour l'état dans l'onglet Téléversement

    # ── Détection automatique du propriétaire du token ───────────────────

    # ── Détection / choix du compte déposant ─────────────────────────────

    def _detect_token_owner(self):
        """(Thread) Détecte le propriétaire du token, puis enchaîne sur le thread
        principal (attribution automatique ou fenêtre de choix).

        S'appuie sur PodAPI.whoami(), SÛRE par construction : elle ne renvoie un
        compte que s'il est le seul candidat possible (sinon None). On délègue la
        suite à _after_detection() qui décide quoi faire selon le résultat.
        """
        if not self.api:
            return
        try:
            me = self.api.whoami()      # None si token admin/staff multi-comptes
        except Exception:
            me = None
        self._ui(self._after_detection, me)

    def _after_detection(self, me):
        """(Thread principal Tk) Suite de la détection du propriétaire du token.

        • Piste 1 (fiable, token personnel ne voyant qu'un compte) → on attribue
          automatiquement le compte déposant : zéro clic pour l'enseignant.
        • Tous les autres cas (token admin/staff, ou Piste 2 « probable ») → on
          OUVRE la fenêtre de choix du compte déposant, en pré-remplissant la
          suggestion éventuelle. C'est la solution déterministe : l'utilisateur
          choisit explicitement, aucune mésattribution possible.
        """
        if me and me.get("_detection") == "piste1" and me.get("url"):
            self._apply_detected_owner(me)     # attribution automatique
            return

        # On note que la fenêtre a été présentée, pour ne pas la rouvrir à chaque
        # connexion. L'utilisateur pourra toujours changer le compte plus tard
        # depuis l'onglet Configuration.
        self.config_data["owner_prompt_seen"] = True
        cfg.save_config(self.config_data)

        suggestion = me.get("username", "") if me else ""
        if suggestion:
            self._log(f"Compte probablement propriétaire du token : {suggestion} "
                      f"(pré-rempli dans la fenêtre de choix, à confirmer).")
        self._prompt_pick_owner(suggestion)

    def _apply_detected_owner(self, me: dict):
        """Attribue automatiquement le compte déposant (cas Piste 1, fiable).

        Appelé uniquement quand whoami() est certain de l'identité (le token ne
        voit qu'un seul compte). On enregistre le compte, on met à jour le bandeau
        et on pré-remplit le filtre de l'onglet Configuration.
        """
        username = me.get("username", "")
        url = me.get("url", "")
        self.config_data["agent_username"] = username
        self.config_data["agent_owner_url"] = url
        cfg.save_config(self.config_data)
        self.agent_lbl.configure(text=f"Dépôt au nom de :\n{username}  (détecté)")
        if hasattr(self, "agent_filter"):
            self.agent_filter.delete(0, "end")
            self.agent_filter.insert(0, username)
            self._render_users()
        self._refresh_owner_status()
        self._log(f"Propriétaire du token détecté automatiquement : {username}.")

    def _prompt_pick_owner(self, suggestion: str = ""):
        """Ouvre la fenêtre « Choisissez le compte déposant » (mono-sélection).

        S'affiche après la 1ʳᵉ connexion quand le compte déposant n'a pas pu être
        déterminé automatiquement. L'utilisateur clique sur un compte : il devient
        le propriétaire par défaut des vidéos (modifiable ensuite via l'onglet
        Configuration). Le paramètre `suggestion` pré-remplit le filtre.
        """
        def on_chosen(user: dict):
            # Réutilise la logique existante : enregistre le compte + coche ✅.
            self._pick_agent(user)
            self._log(f"Compte déposant choisi : {user.get('username','')}.")
            self._show_tab("upload")   # on enchaîne directement sur le téléversement

        OwnerPicker(
            self,
            on_done=lambda *_: None,          # inutilisé en mode mono-sélection
            single=True,
            on_single=on_chosen,
            title="Choisissez le compte déposant",
            intro=("Au nom de quel compte les vidéos seront-elles déposées ?\n"
                   "Cliquez sur le compte concerné. Vous pourrez le changer\n"
                   "à tout moment depuis l'onglet « Configuration »."),
            prefilter=suggestion,
        )

    def _build_tab_log(self):
        """Construit l'onglet Journal (zone de texte horodatée + bouton Effacer)."""
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.tabs["log"] = frame
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(top, text="📋  Journal", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")
        ctk.CTkButton(top, text="🗑 Effacer", width=100, fg_color="gray35",
                      hover_color="gray28", command=self._clear_log).pack(side="right")
        self.log_box = ctk.CTkTextbox(frame, font=ctk.CTkFont(family="Consolas", size=11))
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")
        self._log("Application démarrée.")

    def _log(self, msg: str):
        """Ajoute une ligne horodatée au journal."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ts}]  {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        """Vide le journal."""
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ═════════════════════════════════════════════════════════════════════
    #  FENÊTRE « À PROPOS »
    # ═════════════════════════════════════════════════════════════════════

    def _show_about(self):
        """Ouvre une petite fenêtre d'information sur l'application.

        Les informations affichées proviennent des métadonnées du module
        (__version__, __author__, etc.) définies en haut de ce fichier :
        une seule source de vérité à mettre à jour pour changer la version."""
        win = ctk.CTkToplevel(self)
        win.title("À propos")
        # Hauteur portée de 520 à 620 px : l'ajout des mentions légales
        # (copyright + licence, cette dernière tenant sur plusieurs lignes)
        # faisait dépasser le contenu hors de la fenêtre.
        win.geometry("460x620")
        win.resizable(False, False)
        _focus_toplevel(win, self)   # amène la fenêtre au premier plan (modale)

        # — En-tête : logo (si présent) sur bandeau blanc —
        if HAS_PIL:
            try:
                logo_path = resource_path(os.path.join("assets", "logo_ut.png"))
                if os.path.exists(logo_path):
                    pil = PILImage.open(logo_path)
                    W = 200
                    H = round(W * pil.height / pil.width)
                    about_img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(W, H))
                    card = ctk.CTkFrame(win, fg_color="white", corner_radius=8)
                    card.pack(padx=20, pady=(20, 8))
                    # On garde une référence sur la fenêtre pour éviter que l'image
                    # soit récupérée par le ramasse-miettes (sinon elle disparaît).
                    win._about_img = about_img
                    ctk.CTkLabel(card, image=about_img, text="").pack(padx=12, pady=12)
            except Exception:
                pass

        # — Nom + version —
        ctk.CTkLabel(win, text="Pod Téléverseur",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(6, 0))
        ctk.CTkLabel(win, text=f"version {__version__}",
                     font=ctk.CTkFont(size=12), text_color="gray70").pack(pady=(0, 10))

        # — Description courte —
        ctk.CTkLabel(
            win,
            text="Téléversement par lot de vidéos vers l'instance\n"
                 "Esup-Pod de l'Université de Toulouse.",
            justify="center", text_color="gray80",
            font=ctk.CTkFont(size=12)).pack(pady=(0, 12))

        # — Bloc « Développé par » : les trois auteurs, un par ligne —
        dev = ctk.CTkFrame(win, fg_color="gray18", corner_radius=8)
        dev.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(dev, text="Développé par",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(pady=(8, 2))
        # __author__ contient les auteurs séparés par des virgules : on les
        # affiche un par ligne pour une lecture claire.
        for nom in [a.strip() for a in __author__.split(",") if a.strip()]:
            ctk.CTkLabel(dev, text=nom, font=ctk.CTkFont(size=12),
                         text_color="gray85").pack(pady=0)
        ctk.CTkLabel(dev, text="", height=4).pack()   # petite marge basse

        # — Informations (lignes « étiquette : valeur ») —
        info = ctk.CTkFrame(win, fg_color="gray18", corner_radius=8)
        info.pack(fill="x", padx=20)
        lignes = [
            ("Établissement", __institution__),
            ("Contact",  __contact__),
            ("Instance", "videos.utoulouse.fr"),
            ("Copyright", __copyright__),
            ("Licence",  __license__),
        ]
        for i, (cle, val) in enumerate(lignes):
            ctk.CTkLabel(info, text=f"{cle} :", anchor="e", width=110,
                         font=ctk.CTkFont(size=11, weight="bold")).grid(
                row=i, column=0, padx=(12, 6), pady=4, sticky="e")
            ctk.CTkLabel(info, text=val, anchor="w",
                         font=ctk.CTkFont(size=11), text_color="gray80",
                         wraplength=270, justify="left").grid(
                row=i, column=1, padx=(0, 12), pady=4, sticky="w")
        info.columnconfigure(1, weight=1)

        # — Bouton Fermer —
        ctk.CTkButton(win, text="Fermer", width=120,
                      command=win.destroy).pack(pady=16)

    # ═════════════════════════════════════════════════════════════════════
    #  FENÊTRE « AIDE »
    # ═════════════════════════════════════════════════════════════════════

    def _show_help(self):
        """Ouvre une fenêtre d'aide expliquant, section par section, chaque
        fonction de l'application.

        Le contenu est défini dans une liste `sections` de tuples (titre, texte) :
        pour ajouter ou modifier une rubrique, il suffit d'éditer cette liste —
        la mise en page (titre en gras + paragraphe) est générée automatiquement.
        La fenêtre est défilable (CTkScrollableFrame) pour s'adapter à la longueur
        du texte sans dépasser l'écran.
        """
        win = ctk.CTkToplevel(self)
        win.title("Aide — Pod Téléverseur")
        win.geometry("640x640")
        _focus_toplevel(win, self)

        # Titre de la fenêtre
        ctk.CTkLabel(win, text="❓  Aide — Pod Téléverseur",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(14, 2))
        ctk.CTkLabel(win, text="Guide des fonctions, de la connexion au dépôt des vidéos.",
                     text_color="gray70", font=ctk.CTkFont(size=12)).pack(pady=(0, 8))

        # Zone défilable qui contiendra toutes les rubriques
        body = ctk.CTkScrollableFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # ── Contenu de l'aide : (titre de section, texte explicatif) ──────────
        # Chaque texte est volontairement rédigé simplement, pour des utilisateurs
        # non informaticiens (enseignants).
        sections = [
            ("1. Premiers pas — se connecter",
             "À la toute première utilisation, un assistant s'ouvre "
             "automatiquement : collez le token fourni par le service informatique "
             "(l'adresse de l'instance est déjà renseignée) et cliquez sur "
             "« Se connecter ». L'assistant enchaîne ensuite sur le choix du compte "
             "déposant.\n\n"
             "Par la suite, la connexion est automatique au lancement. Vous pouvez "
             "toujours revoir ces réglages dans l'onglet « Configuration ».\n\n"
             "Le token remplace l'identifiant et le mot de passe : il donne les mêmes "
             "droits que le compte auquel il est rattaché."),

            ("2. Choisir le compte déposant",
             "Les vidéos doivent être déposées au nom d'un compte (leur futur "
             "propriétaire). À la première connexion :\n"
             "• si l'application reconnaît votre compte avec certitude, elle le "
             "sélectionne automatiquement ;\n"
             "• sinon, une fenêtre « Choisissez le compte déposant » s'ouvre : "
             "cliquez sur le compte concerné.\n\n"
             "Ce choix est mémorisé sur ce poste. Vous pouvez le changer à tout "
             "moment dans l'onglet « Configuration » (champ de recherche des comptes), "
             "ce qui est utile si vous déposez pour plusieurs enseignants."),

            ("3. Ajouter des vidéos",
             "Dans l'onglet « Téléversement », trois façons d'ajouter des fichiers :\n"
             "• « Ajouter des fichiers » : sélection manuelle ;\n"
             "• « Ajouter un dossier » : ajoute toutes les vidéos qu'il contient ;\n"
             "• Glisser-déposer : faites glisser fichiers ou dossiers directement "
             "sur la liste.\n\n"
             "Les doublons sont automatiquement ignorés. Chaque vidéo apparaît dans "
             "la liste avec un titre modifiable — corrigez-le avant l'envoi si besoin. "
             "Le bouton « Retirer » enlève une vidéo de la liste (sans la supprimer "
             "de votre disque)."),

            ("4. Réglages communs au lot",
             "Avant de lancer l'envoi, vous définissez des réglages appliqués à "
             "toutes les vidéos du lot :\n"
             "• Type de vidéo (capsule d'enseignement, tutoriel, etc.) ;\n"
             "• Visibilité : « Brouillon/Privé » (la vidéo reste invisible au public) "
             "ou « Public » ;\n"
             "• « Lancer l'encodage après le téléversement » (cochée par défaut) : "
             "l'application demande l'encodage automatiquement une fois la vidéo "
             "envoyée. Sans encodage, la vidéo n'est pas lisible en ligne ;\n"
             "• Propriétaires additionnels : d'autres comptes Pod autorisés à "
             "modifier les vidéos (facultatif)."),

            ("5. Propriétaire des vidéos (obligatoire)",
             "Vous devez choisir explicitement le compte PROPRIÉTAIRE des vidéos "
             "avant tout envoi, via le bouton « 🎯 Choisir le propriétaire… ». "
             "L'état affiché à côté indique :\n"
             "• « ⚠️ à définir avant l'envoi » (orange) tant qu'aucun compte n'est "
             "choisi ;\n"
             "• « ✅ [nom] » (vert) une fois le compte défini.\n\n"
             "Si vous lancez l'envoi sans avoir choisi de propriétaire, "
             "l'application NE téléverse RIEN et ouvre le sélecteur : ce blocage "
             "est volontaire, pour éviter tout dépôt au mauvais nom. Le compte du "
             "token est présélectionné, donc le choix se fait en un clic. Ce "
             "propriétaire s'applique à tout le lot."),

            ("6. Lancer le téléversement",
             "Cliquez sur « Lancer le téléversement ». Une barre de progression "
             "indique l'avancement du fichier en cours et du lot global. Chaque "
             "vidéo passe par : envoi → (si la case est cochée) lancement de "
             "l'encodage. L'état de chaque vidéo s'affiche en face de son titre.\n\n"
             "Les gros fichiers sont gérés automatiquement (voir la rubrique "
             "suivante) : vous n'avez rien de particulier à faire. Évitez de fermer "
             "l'application pendant un envoi en cours."),

            ("7. Gros fichiers (plus de 150 Mo)",
             "Au-delà de 500 Mo, l'application bascule automatiquement sur un envoi "
             "par petits morceaux, plus robuste pour les gros fichiers. C'est "
             "totalement transparent : vous déposez comme d'habitude, la vidéo finit "
             "bien au nom du propriétaire que vous avez choisi.\n\n"
             "Sur un très gros fichier, la finalisation peut prendre plusieurs "
             "minutes côté serveur. Il se peut que l'application affiche "
             "« ⏳ Finalisation côté serveur… vérification » : c'est NORMAL. "
             "Laissez-la travailler (jusqu'à une trentaine de minutes pour les "
             "fichiers les plus lourds) — elle reprend automatiquement la main dès "
             "que la vidéo est prête, puis lance l'encodage. Ne relancez pas l'envoi "
             "pendant ce temps.\n\n"
             "Si un message rouge « NON réattribuée » apparaît, la vidéo a bien été "
             "envoyée mais n'a pas pu être remise à son propriétaire : signalez-le au "
             "support, qui pourra corriger le propriétaire."),

            ("8. En cas d'échec réseau (relance)",
             "Sur les gros fichiers, l'envoi peut échouer à cause d'une coupure "
             "réseau passagère — ce n'est pas un défaut de l'application. Deux "
             "protections existent :\n"
             "• Relance automatique : chaque vidéo est réessayée jusqu'à 3 fois "
             "(le statut affiche « ⟳ essai 2 »). Ne vous inquiétez donc pas d'un "
             "échec momentané, l'application retente seule.\n"
             "• Bouton « 🔄 Relancer les échecs » : s'il reste des vidéos en échec "
             "après le lot, ce bouton apparaît avec leur nombre. Il ne retente que "
             "les échecs (les vidéos déjà réussies ne sont pas renvoyées) et "
             "disparaît quand tout est passé.\n\n"
             "Si une même vidéo échoue à chaque fois, c'est probablement une limite "
             "plus dure (taille, réseau de l'établissement) : signalez-le au "
             "support."),

            ("9. Journal",
             "L'onglet « Journal » conserve l'historique horodaté des opérations "
             "(connexions, envois, encodages, erreurs). En cas de problème, c'est la "
             "première chose à consulter. Le bouton « Effacer » vide l'affichage "
             "(sans effet sur les vidéos déjà déposées)."),

            ("10. Sécurité du token",
             "Votre token est stocké dans le coffre-fort sécurisé de votre système "
             "(Gestionnaire d'identifiants Windows / Trousseau macOS), jamais en clair "
             "ni dans l'application. Il reste sur ce poste : copier le programme sur un "
             "autre ordinateur n'emporte aucun identifiant.\n\n"
             "Le bouton « Oublier le token / Se déconnecter » (onglet Configuration) "
             "efface le token de ce poste."),

            ("11. macOS : « l'application est endommagée »",
             "L'application N'EST PAS endommagée : macOS affiche ce message pour "
             "toute application diffusée hors de l'App Store.\n\n"
             "Marche à suivre, dans cet ordre :\n"
             "1. Ouvrez le .dmg et glissez l'application dans le dossier "
             "Applications (ou sur le Bureau).\n"
             "2. Éjectez le .dmg — indispensable : tant que l'application est "
             "dedans, elle est en lecture seule et rien ne peut être corrigé.\n"
             "3. Ouvrez le Terminal (⌘+Espace, tapez « Terminal ») et saisissez :\n"
             "       xattr -cr\n"
             "   puis un ESPACE, puis glissez l'application dans la fenêtre du "
             "Terminal (le chemin s'écrit tout seul) et appuyez sur Entrée.\n"
             "4. Relancez l'application.\n\n"
             "Si le message persiste, la signature du paquet a été abîmée pendant "
             "le transfert. Réparez-la de la même façon avec :\n"
             "       codesign --force --deep --sign -\n\n"
             "À noter : transférer l'application par messagerie (Telegram, "
             "WhatsApp…) casse souvent sa signature. Téléchargez-la toujours "
             "depuis la page Moodle."),

            ("12. Problèmes courants",
             "• « 0 utilisateur » lors du chargement des comptes : le token n'a pas le "
             "droit de lister les utilisateurs. Le dépôt reste possible, mais la "
             "recherche de comptes est limitée — voyez avec le service informatique.\n"
             "• Erreur de connexion : vérifiez l'adresse de l'instance et la validité "
             "du token.\n"
             "• La vidéo n'est pas lisible après l'envoi : vérifiez que la case "
             "d'encodage était cochée ; l'encodage peut prendre du temps côté serveur.\n\n"
             "Pour tout problème persistant : support-pod@utoulouse.fr."),
        ]

        # Rendu automatique des sections (titre en gras + paragraphe justifié).
        for titre, texte in sections:
            bloc = ctk.CTkFrame(body, fg_color="gray18", corner_radius=8)
            bloc.pack(fill="x", pady=6)
            ctk.CTkLabel(bloc, text=titre, anchor="w",
                         font=ctk.CTkFont(size=14, weight="bold")).pack(
                fill="x", padx=12, pady=(10, 2))
            ctk.CTkLabel(bloc, text=texte, anchor="w", justify="left",
                         wraplength=560, text_color="gray85",
                         font=ctk.CTkFont(size=12)).pack(fill="x", padx=12, pady=(0, 12))

        # Bouton Fermer
        ctk.CTkButton(win, text="Fermer", width=120,
                      command=win.destroy).pack(pady=(0, 14))


# ════════════════════════════════════════════════════════════════════════════
#  FENÊTRE : sélection de propriétaires additionnels
# ════════════════════════════════════════════════════════════════════════════

def _focus_toplevel(win, master=None):
    """Amène une fenêtre secondaire au premier plan, lui donne le focus et la
    rend modale (focus capturé jusqu'à fermeture). Corrige le cas où une
    CTkToplevel s'ouvre derrière la fenêtre principale.
    Les appels sont légèrement différés (after) car la fenêtre n'est pas encore
    dessinée à l'instant de sa création."""
    try:
        if master is not None:
            win.transient(master)          # la fenêtre reste au-dessus de son parent
    except Exception:
        pass
    win.lift()
    win.attributes("-topmost", True)        # passe au-dessus, le temps de s'afficher
    # On retire 'topmost' juste après (sinon elle resterait au-dessus de TOUTES
    # les applications), puis on capture le focus.
    win.after(150, lambda: (win.attributes("-topmost", False), win.focus_force()))
    win.after(200, lambda: win.grab_set())  # modale : bloque la fenêtre principale


class OwnerPicker(ctk.CTkToplevel):
    """Sélecteur multi-utilisateurs : même système que l'agent (liste + filtre + clic)."""

    def __init__(self, master: App, on_done, title="Propriétaires additionnels",
                 preselected: dict | None = None, single: bool = False, on_single=None,
                 intro: str = "", prefilter: str = ""):
        # Paramètres ajoutés :
        #   • intro     : texte d'introduction personnalisé (sinon texte par défaut).
        #   • prefilter : valeur pré-remplie dans le champ de filtre (ex. suggestion
        #                 issue de la détection automatique du propriétaire du token).
        super().__init__(master)
        self.master_app = master
        self.on_done = on_done
        self.single = single
        self.on_single = on_single
        self.title(title)
        self.geometry("500x560")
        _focus_toplevel(self, master)
        self.selected: dict[str, str] = dict(preselected or {})   # url → libellé

        # Texte d'introduction : personnalisé si fourni, sinon valeur par défaut
        # adaptée au mode (sélection unique ou multiple).
        if not intro:
            intro = ("Cliquez sur un utilisateur pour le choisir." if single else
                     "Cochez les comptes Pod à ajouter comme propriétaires\n"
                     "additionnels. Filtrez la liste puis cliquez pour (dé)cocher.")
        ctk.CTkLabel(self, text=intro, justify="left").pack(padx=14, pady=(14, 8), anchor="w")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=14)
        self.filter = ctk.CTkEntry(bar, placeholder_text="🔍 nom / identifiant…")
        self.filter.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.filter.bind("<KeyRelease>", lambda e: self._render())
        ctk.CTkButton(bar, text="🔄", width=40, command=self._reload).pack(side="left")
        # Pré-remplissage éventuel du filtre (suggestion de détection).
        if prefilter:
            self.filter.insert(0, prefilter)

        self.count_lbl = ctk.CTkLabel(self, text="", text_color="gray", font=ctk.CTkFont(size=11))
        self.count_lbl.pack(anchor="w", padx=14, pady=(4, 0))

        self.listbox = ctk.CTkScrollableFrame(self, height=320)
        self.listbox.pack(fill="both", expand=True, padx=14, pady=8)

        self.chosen_lbl = ctk.CTkLabel(self, text="Sélection : aucun", text_color="gray",
                                       wraplength=460, justify="left")
        # Le récapitulatif de sélection n'a de sens qu'en mode multiple.
        if not self.single:
            self.chosen_lbl.pack(padx=14, anchor="w")

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=10)
        if self.single:
            # En sélection unique, un clic sur un compte valide directement :
            # le bouton « Valider » est inutile, on ne garde qu'« Annuler ».
            ctk.CTkButton(btns, text="Annuler", fg_color="gray35", hover_color="gray28",
                          command=self.destroy).pack(side="right")
        else:
            ctk.CTkButton(btns, text="Valider", fg_color="#16a34a", hover_color="#15803d",
                          command=self._validate).pack(side="right")
            ctk.CTkButton(btns, text="Annuler", fg_color="gray35", hover_color="gray28",
                          command=self.destroy).pack(side="right", padx=8)

        self.after(80, self._init_list)

    def _init_list(self):
        """Affiche la liste si les comptes sont déjà chargés, sinon déclenche un chargement."""
        if self.master_app.all_users:
            self._render()
            self._update_chosen()
        else:
            self.count_lbl.configure(text="⏳  Chargement des utilisateurs…")
            self._reload()

    def _reload(self):
        """(Thread) Charge la liste des comptes si nécessaire, puis rafraîchit l'affichage."""
        def work():
            try:
                if not self.master_app.all_users:
                    users = self.master_app.api.get_all_users()
                    users.sort(key=lambda u: (u.get("username") or "").lower())
                    self.master_app.all_users = users
                self.after(0, self._render)
                self.after(0, self._update_chosen)
            except Exception as e:
                self.after(0, lambda: self.count_lbl.configure(text=f"Erreur : {e}", text_color="#ef4444"))
        threading.Thread(target=work, daemon=True).start()

    def _label(self, u: dict) -> str:
        """Libellé lisible d'un compte."""
        return f"{u.get('username','?')} — {u.get('first_name','')} {u.get('last_name','')}".strip()

    def _render(self):
        """Affiche la liste filtrée (cases à cocher)."""
        flt = self.filter.get().strip().lower()
        for w in self.listbox.winfo_children():
            w.destroy()
        users = self.master_app.all_users
        if not users:
            ctk.CTkLabel(self.listbox, text="Liste non disponible.", text_color="gray").pack(pady=10)
            return
        matches = [u for u in users if not flt or flt in self._label(u).lower()]
        CAP = 300
        for u in matches[:CAP]:
            url = u.get("url", "")
            sel = url in self.selected
            if self.single:
                prefix = "   "
            else:
                prefix = "☑  " if sel else "☐  "
            ctk.CTkButton(self.listbox, text=prefix + self._label(u), anchor="w",
                          fg_color=("gray75", "gray30") if (sel and not self.single) else "transparent",
                          text_color=("gray10", "gray90"), hover_color=("gray75", "gray28"),
                          height=28, font=ctk.CTkFont(size=12),
                          command=lambda uu=u: self._toggle(uu)).pack(fill="x", pady=1)
        self.count_lbl.configure(text=f"{len(matches)} affiché(s) sur {len(users)} — "
                                      f"{len(self.selected)} sélectionné(s)", text_color="gray")
        if len(matches) > CAP:
            ctk.CTkLabel(self.listbox, text=f"… affinez le filtre ({len(matches) - CAP} de plus)",
                         text_color="gray").pack(pady=4)
        elif not matches:
            ctk.CTkLabel(self.listbox, text="Aucun résultat.", text_color="gray").pack(pady=8)

    def _toggle(self, u: dict):
        """Coche/décoche un compte (ou valide directement en mode sélection unique)."""
        if self.single:
            if self.on_single:
                self.on_single(u)
            self.destroy()
            return
        url = u.get("url", "")
        if not url:
            return
        if url in self.selected:
            del self.selected[url]
        else:
            self.selected[url] = self._label(u)
        self._render()
        self._update_chosen()

    def _update_chosen(self):
        """Met à jour le libellé récapitulant la sélection courante."""
        if self.selected:
            self.chosen_lbl.configure(text="Sélection : " + ", ".join(self.selected.values()),
                                      text_color="#22c55e")
        else:
            self.chosen_lbl.configure(text="Sélection : aucun", text_color="gray")

    def _validate(self):
        """Renvoie la sélection à l'appelant (on_done) puis ferme la fenêtre."""
        self.on_done(list(self.selected.keys()), list(self.selected.values()))
        self.destroy()


# ════════════════════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()
