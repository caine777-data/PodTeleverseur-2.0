# macOS — « Pod Téléverseur est endommagé et ne peut pas être ouvert »

## Ce que ça veut dire

**L'application n'est pas endommagée.** macOS affiche ce message trompeur quand
une application diffusée hors de l'App Store n'a pas de signature valide, ou
quand sa signature a été abîmée pendant le transfert.

## Marche à suivre (l'ordre compte)

Un `.dmg` est en **lecture seule** : il faut d'abord en sortir l'application.

1. Ouvrir le `.dmg`, **glisser Pod Téléverseur dans Applications** (ou sur le
   Bureau, ce qui évite le mot de passe administrateur).
2. **Éjecter le `.dmg`** (clic droit sur son icône → Éjecter).
3. Ouvrir le **Terminal** (⌘ + Espace, taper « Terminal », Entrée).
4. Taper ceci **avec un espace à la fin**, sans valider :
   ```
   xattr -cr 
   ```
   puis **glisser l'application** depuis le Finder dans la fenêtre du Terminal
   (le chemin s'écrit tout seul), et appuyer sur Entrée.
5. Lancer l'application.

**Si le message revient**, la signature est cassée : même méthode avec
```
codesign --force --deep --sign - 
```

## Corrections apportées à la compilation

Deux défauts produisaient ce message ; tous deux sont corrigés :

1. **Aucune signature.** Sur Apple Silicon, macOS exige que tout exécutable
   porte une signature valide, même « ad hoc » (anonyme). Le paquet est
   désormais signé, avec vérification bloquante en cas d'échec.
2. **Archive fabriquée avec `zip`.** Cette commande ne préserve ni les liens
   symboliques internes d'un paquet `.app` ni ses attributs étendus : la
   signature est cassée à la décompression. `ditto`, l'outil prévu par Apple,
   la remplace pour l'archive et pour la préparation du DMG.

Les prochaines versions compilées ne devraient plus provoquer ce message.

## Recommandations de diffusion

- **Diffuser le `.dmg`**, pas l'archive `.zip`.
- **Ne pas transmettre l'application par messagerie** (Telegram, WhatsApp…) :
  ces services recompressent les fichiers et cassent la signature. Passer par un
  lien de téléchargement (page Moodle).

## Limite connue : Mac Intel

Les exécutables macOS sont produits par les serveurs GitHub, en **Apple
Silicon** : l'application est donc **arm64 uniquement** et ne fonctionne pas sur
un Mac Intel. Le message y serait différent (« ne peut pas être ouvert sur ce
type de Mac ») et aucune commande n'y changerait rien.
