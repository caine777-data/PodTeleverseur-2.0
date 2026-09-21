# Mise en place des mises à jour — Pod Téléverseur

À faire **une seule fois**. Ensuite, chaque publication met à jour les postes
installés sans aucune intervention manuelle.

## Principe

```
Dépôt PRIVÉ  PodTeleverseur-2.0          Dépôt PUBLIC  podteleverseur-releases
  code source                               version.json   ← lu par l'application
  workflow de compilation  ──publie──►      Releases       ← page « Télécharger »
```

Le code reste privé. Seuls les exécutables et le petit fichier `version.json`
sont publics : un enseignant doit pouvoir télécharger sans compte GitHub.

## Étape 1 — Créer le dépôt public

Sur GitHub, compte `caine777-data` :

- **New repository** → nom : `podteleverseur-releases`
- **Public**
- Cocher **Add a README file** — ⚠️ indispensable : le workflow clone ce dépôt,
  et un dépôt totalement vide ne se clone pas.

## Étape 2 — Créer le jeton d'écriture

Le jeton automatique de GitHub Actions n'a aucun droit en dehors du dépôt où il
s'exécute. Il en faut un autre pour écrire sur le dépôt public.

GitHub → photo de profil → **Settings** → **Developer settings** →
**Personal access tokens** → **Fine-grained tokens** → **Generate new token** :

- Nom : `podteleverseur-releases`
- Expiration : 1 an (noter la date : à l'échéance, la notification cessera
  silencieusement)
- Repository access : **Only select repositories** → `podteleverseur-releases`
- Permissions → Repository permissions → **Contents : Read and write**

Copier le jeton affiché — il ne sera plus visible ensuite.

> Le même jeton peut servir à PodAdmin si le dépôt `podadmin-releases` est ajouté
> à sa liste de dépôts autorisés. Sinon, en créer un second.

## Étape 3 — Enregistrer le jeton dans le dépôt PRIVÉ

Dans le dépôt **du code** (et non le public) : **Settings** → **Secrets and
variables** → **Actions** → **New repository secret** :

- Name : `RELEASES_TOKEN`
- Secret : le jeton copié à l'étape 2

## Étape 4 — Première publication

Onglet **Actions** → **Run workflow** :

- **version** : écrire `OUI` — ⚠️ champ VIDE = compilation d'essai, rien n'est
  publié. C'est le piège le plus fréquent.
- **notes** : la phrase affichée dans le bandeau (facultatif)

Le numéro est lu dans `__version__.py` : ce qui est saisi dans le formulaire ne
sert qu'à déclencher la publication.

## Étape 5 — Vérifier

1. Le dépôt public contient un `version.json` à la bonne version, et une Release
   avec quatre fichiers.
2. Ouvrir dans un navigateur :
   `https://raw.githubusercontent.com/caine777-data/podteleverseur-releases/main/version.json`
3. Lancer une version **antérieure** du Téléverseur : le bandeau doit apparaître
   dans les deux secondes. Onglet Journal : une ligne « Mise à jour — … »
   confirme que la vérification a eu lieu.

⚠️ Une version **égale ou plus récente** n'affiche aucun bandeau : c'est
normal. Pour tester, il faut une version plus ancienne sous la main.

## En cas de problème

| Symptôme | Cause probable |
|---|---|
| Aucune Release créée | champ `version` laissé vide |
| Release créée, pas de `version.json` | secret `RELEASES_TOKEN` absent ou mal nommé |
| Échec « 403 » | jeton sans droit *Contents : Read and write* sur le dépôt public |
| Échec au clonage | dépôt public créé sans README |
| Bandeau jamais affiché | version installée ≥ version publiée ; voir le Journal |
