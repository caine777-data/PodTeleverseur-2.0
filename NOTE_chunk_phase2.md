# Pod Téléverseur — Ajout : chunk pour les gros fichiers (Phase 2)

## Ce qui a été ajouté
- **Compte véhicule DEPOT embarqué** (config.py) : identifiant + mot de passe
  d'un compte LOCAL sans privilège, utilisé UNIQUEMENT pour ouvrir la session web
  du chunké. Les enseignants ne le voient ni ne le saisissent.
- **Téléversement > 500 Mo** : bascule automatique en chunké via DEPOT, puis la
  vidéo est RÉATTRIBUÉE au propriétaire choisi par l'enseignant, via SON token
  is_staff (métadonnées + encodage ensuite). ≤ 500 Mo : chemin token inchangé.
- **Garde-fou réattribution** : si le PATCH owner échoue, statut rouge
  « ⚠️ NON réattribuée » + log détaillé (jamais de fausse attribution silencieuse).
- **Récupération après 504** : attente/sondage jusqu'à 30 min que la vidéo
  apparaisse côté serveur, puis réattribution + métadonnées + encodage.
- pod_chunked.py (moteur), pod_api.get_video_by_slug() : ajoutés.

## ⚠️ SÉCURITÉ — À LIRE
Le mot de passe de DEPOT est maintenant **écrit en clair dans config.py**.
- **Le dépôt GitHub DOIT être PRIVÉ.** Un dépôt public exposerait le mot de passe
  bien plus facilement qu'un exe.
- DEPOT doit rester **local et sans aucun privilège** (ni superuser, ni staff) :
  au pire, une fuite permet de déposer une vidéo en son nom, rien de plus.
- Le mot de passe qui a transité en clair pendant la mise au point devrait être
  **changé** (puis reporté ici et recompilé).
- Toute rotation du mot de passe impose de **recompiler et redistribuer** l'appli.

## À tester sur l'instance
1. Petit fichier (< 500 Mo) → chemin habituel, propriétaire choisi.
2. Gros fichier (> 500 Mo) avec un token enseignant is_staff → vérifier côté web
   que la vidéo appartient bien au propriétaire choisi (pas à DEPOT), encodage lancé.
3. Cas 504 : reprise automatique après quelques minutes.
