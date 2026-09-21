"""
Source UNIQUE de la version de Pod Téléverseur.
===============================================
La version était définie dans l'en-tête de CHAQUE fichier. Lors de la
publication 2.1.0, elle a été mise à jour dans `config.py` mais pas dans
`app.py` — or c'est `app.py` qui fait foi pour l'application.

Conséquence, découverte en portant la vérification de mise à jour :
l'application se serait crue éternellement en 2.0.0, et aurait signalé en
permanence une « nouvelle version »… vers elle-même.

Tous les modules importent désormais la version d'ici. Le workflow de
compilation la lit aussi dans ce fichier : il n'y a plus qu'un seul endroit à
modifier.

Le fichier `version.txt` (métadonnées de l'exécutable Windows) reste à mettre à
jour lors d'une publication : il ne peut pas importer de code Python. Un test
vérifie qu'il concorde.
"""

__version__ = "2.2.0"

# Décomposition (entiers), pour les métadonnées Windows :
# (majeur, mineur, correctif, build).
VERSION_TUPLE = tuple(int(x) for x in __version__.split(".")) + (0,)
