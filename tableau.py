"""
Composants de liste repris de PodAdmin (1.12 et 1.13) : tableau natif stylé,
filtres en pastilles, rangée qui passe à la ligne.

Le tableau est un ttk.Treeview et non un bouton CustomTkinter par ligne :
Tk dessine des milliers de lignes sans ralentir, là où reconstruire des
boutons prenait plusieurs secondes à chaque filtrage.

Dépend de CustomTkinter et des couleurs de theme.py ; aucune logique métier.
"""
from __future__ import annotations

import tkinter.font as tkfont
from tkinter import ttk

import customtkinter as ctk

from theme import (C_CHAMP, C_CHAMP_SURV, C_MULTI, S_CARTE, S_FILET, S_LIGNE, S_PUCE,
                   S_SELECTION, T_CHAMP)

# Pastille active : le bleu de la sélection, texte foncé sur clair et
# inversement (contraste supérieur à 7:1 dans les deux modes).
C_FILTRE_ACTIF = ("#dbeafe", "#1e3a8a")
T_FILTRE_ACTIF = ("#1e3a8a", "#dbeafe")
# Lien d'action discret (« Effacer les filtres »).
T_LIEN = ("#1d4ed8", "#93c5fd")

# Hauteur d'une ligne de tableau, en pixels avant mise à l'échelle.
HAUTEUR_LIGNE = 28

# Tableaux à restyler quand le thème change. Un tableau détruit entre-temps
# en est retiré au stylage suivant.
_TABLEAUX: set = set()


# --- Tableau natif ---

def styler_tableaux(racine) -> None:
    """Couleurs et police de TOUS les tableaux selon le thème courant.

    Un Treeview n'accepte que des couleurs SIMPLES, pas les couples (clair,
    sombre) de CustomTkinter : on choisit la teinte du mode actif, et le
    changement de thème doit rappeler cette fonction. Le thème ttk « clam »
    est le seul qui respecte les couleurs sur Windows ET sur macOS (« aqua »
    les ignore)."""
    sombre = ctk.get_appearance_mode().lower() == "dark"

    def c(paire):
        return paire[1] if sombre else paire[0]

    style = ttk.Style(racine)
    if style.theme_use() != "clam":
        style.theme_use("clam")
    echelle = ctk.ScalingTracker.get_widget_scaling(racine)
    police = tkfont.nametofont("TkDefaultFont").copy()
    police.configure(size=-round(13 * echelle))          # négatif = pixels
    gras = police.copy()
    gras.configure(weight="bold")
    # Gardées sur la fonction : Tk ne tient qu'une référence faible aux polices.
    styler_tableaux.polices = (police, gras)
    fond, texte = c(S_CARTE), c(("gray10", "gray90"))
    style.configure("Pod.Treeview", background=fond, fieldbackground=fond, foreground=texte,
                    rowheight=round(HAUTEUR_LIGNE * echelle), font=police,
                    borderwidth=0, relief="flat")
    style.layout("Pod.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure("Pod.Treeview.Heading", background=c(S_PUCE), foreground=texte,
                    font=gras, relief="flat", borderwidth=0)
    style.map("Pod.Treeview.Heading", background=[("active", c(S_SELECTION))])
    for arbre in list(_TABLEAUX):
        try:
            arbre.tag_configure("pair", background=fond)
            arbre.tag_configure("alt", background=c(S_LIGNE))
            arbre.tag_configure("courante", background=c(S_SELECTION))
            arbre.tag_configure("multi", background=c(C_MULTI))
        except Exception:
            _TABLEAUX.discard(arbre)                      # détruit entre-temps


def enregistrer_tableau(arbre) -> None:
    """Inscrit un Treeview parmi les tableaux stylés, et le teinte aussitôt."""
    _TABLEAUX.add(arbre)
    styler_tableaux(arbre)


# --- Filtres en pastilles ---
#
# Remplacent les menus déroulants : chaque menu s'élargissait pour afficher
# la valeur choisie, et un nom de chaîne long poussait les autres hors de la
# fenêtre. Une pastille ne prend que la place de son nom ; active, elle passe
# en bleu, montre son choix (abrégé) et se retire d'un clic sur ✕.

def abreger(texte: str, maxi: int = 22) -> str:
    """Raccourcit un libellé trop long pour une pastille (« Faculté de san… »)."""
    texte = str(texte)
    return texte if len(texte) <= maxi else texte[: maxi - 1].rstrip() + "…"


class PastilleFiltre(ctk.CTkButton):
    """Filtre compact : « Statut ▾ » au repos, « Statut : Brouillon ✕ » actif.

    Garde l'interface d'un CTkOptionMenu dont le code se sert (get, set,
    configure(values=…), cget("values")) : le filtrage n'a pas à changer. La
    PREMIÈRE valeur est la valeur neutre (« Tous statuts », « Toutes
    chaînes »…) ; la pastille est active dès que la valeur choisie en diffère."""

    def __init__(self, master, nom: str, valeurs, command=None, **kw):
        self.nom = nom
        self._valeurs = list(valeurs)
        self._valeur = self._valeurs[0]
        self._rappel = command
        self._x_clic = 0
        super().__init__(master, text="", width=0, height=28, corner_radius=14,
                         border_width=1, font=ctk.CTkFont(size=12), command=self._clic, **kw)
        # Position du clic, pour distinguer le ✕ du reste de la pastille : la
        # commande d'un bouton ne reçoit pas l'événement.
        self.bind("<Button-1>", self._noter_clic, add="+")
        self._menu = None
        self._maj()

    # Interface d'un menu déroulant
    def get(self) -> str:
        return self._valeur

    def set(self, valeur) -> None:
        """Choisit une valeur SANS prévenir (comme CTkOptionMenu.set)."""
        self._valeur = valeur
        self._maj()

    def configure(self, require_redraw=False, **kw):
        if "values" in kw:
            self._valeurs = list(kw.pop("values")) or [self._valeurs[0]]
            if self._valeur not in self._valeurs:
                self._valeur = self._valeurs[0]
            self._menu = None                             # reconstruit à la prochaine ouverture
            self._maj()
        if kw:
            super().configure(require_redraw, **kw)

    def cget(self, cle):
        if cle == "values":
            return list(self._valeurs)
        return super().cget(cle)

    def est_active(self) -> bool:
        return self._valeur != self._valeurs[0]

    def effacer(self) -> None:
        """Revient à la valeur neutre, et prévient."""
        if self.est_active():
            self.set(self._valeurs[0])
            if self._rappel:
                self._rappel(self._valeur)

    # Aspect et gestes
    def _maj(self) -> None:
        if self.est_active():
            super().configure(text=f"{self.nom} : {abreger(self._valeur)}  ✕",
                              fg_color=C_FILTRE_ACTIF, hover_color=C_FILTRE_ACTIF,
                              border_color=C_FILTRE_ACTIF, text_color=T_FILTRE_ACTIF,
                              font=ctk.CTkFont(size=12, weight="bold"))
        else:
            super().configure(text=f"{self.nom}  ▾", fg_color=C_CHAMP,
                              hover_color=C_CHAMP_SURV, border_color=S_FILET,
                              text_color=T_CHAMP, font=ctk.CTkFont(size=12))

    def _noter_clic(self, evt) -> None:
        self._x_clic = evt.x_root - self.winfo_rootx()

    def _clic(self) -> None:
        # Le ✕ occupe les 30 derniers pixels d'une pastille active.
        zone_croix = round(30 * ctk.ScalingTracker.get_widget_scaling(self))
        if self.est_active() and self._x_clic >= self.winfo_width() - zone_croix:
            self.effacer()
        else:
            self.ouvrir()

    def ouvrir(self) -> None:
        """Ouvre la liste des choix sous la pastille (celle de CustomTkinter,
        comme les menus déroulants : même aspect, même défilement)."""
        from customtkinter.windows.widgets.core_widget_classes import DropdownMenu

        if self._menu is None:
            self._menu = DropdownMenu(self, values=self._valeurs, command=self._choisir,
                                      fg_color=C_CHAMP, hover_color=C_CHAMP_SURV,
                                      text_color=T_CHAMP, font=ctk.CTkFont(size=12))
        self._menu.open(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())

    def _choisir(self, valeur) -> None:
        self.set(valeur)
        if self._rappel:
            self._rappel(valeur)


class RangeeFluide(ctk.CTkFrame):
    """Rangée qui passe à la ligne quand ses éléments ne tiennent plus.

    Chaque ligne est un cadre intérieur ; les éléments, enfants de la rangée,
    y sont rangés par `pack(in_=…)`. Une grille ne convenait pas : ses colonnes
    sont communes à toutes les lignes, une pastille large aurait élargi la
    colonne entière."""

    ECART = 6

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self.elements: list = []
        self._lignes: list = []
        self._prevu = None
        self.bind("<Configure>", lambda e: self.reorganiser_plus_tard())

    def ajouter(self, widget) -> None:
        self.elements.append(widget)
        self.reorganiser_plus_tard()

    def reorganiser_plus_tard(self) -> None:
        """Regroupe les demandes : une seule réorganisation par passage."""
        if self._prevu is None:
            self._prevu = self.after_idle(self.reorganiser)

    def reorganiser(self) -> None:
        self._prevu = None
        # Une pastille qui vient de changer de texte n'a pas encore sa nouvelle
        # taille : sans ce calcul préalable, la largeur lue serait l'ancienne
        # et la dernière pastille déborderait au lieu de passer à la ligne.
        self.update_idletasks()
        largeur = self.winfo_width()
        if largeur <= 1:
            largeur = 10**6                               # pas encore affichée : une seule ligne
        ligne, x, rangs = 0, 0, []
        for w in self.elements:
            besoin = w.winfo_reqwidth() + self.ECART
            if x and x + besoin > largeur:
                ligne, x = ligne + 1, 0
            rangs.append(ligne)
            x += besoin
        nb = (max(rangs) + 1) if rangs else 0
        while len(self._lignes) < nb:
            self._lignes.append(ctk.CTkFrame(self, fg_color="transparent"))
        for i, cadre in enumerate(self._lignes):
            if i < nb:
                cadre.pack(fill="x", pady=(0 if i == 0 else self.ECART, 0))
            else:
                cadre.pack_forget()
        for w, rang in zip(self.elements, rangs):
            w.pack_forget()
            w.pack(in_=self._lignes[rang], side="left", padx=(0, self.ECART))
            w.lift()                                      # créé avant le cadre : sinon caché dessous

    def nombre_de_lignes(self) -> int:
        return sum(1 for c in self._lignes if c.winfo_manager())
