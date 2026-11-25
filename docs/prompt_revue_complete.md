# Mission : revue complète et grand bond en avant de SakuraLeveling

Tu disposes du modèle le plus puissant et de l'effort maximal : je veux en profiter pour faire progresser le projet le plus loin possible, sur tous les plans. Prends le temps qu'il faut : la profondeur et la justesse comptent plus que la vitesse. Ne te contente pas de constater : corrige, mesure, prouve.

## 1. Contexte (lis tout avant d'agir)

- **Le projet** : SakuraLeveling, bot Discord RPG en Python 3.12 (couches bot / application / domain / infrastructure), SQLite en WAL, site d'administration FastAPI + Jinja + Alpine. Il est déployé depuis la branche `beta` sur un VPS IONOS (2 vCPU, 2 Go de RAM, Ubuntu 24.04, systemd, nginx).
- **Taille** : environ 70 000 lignes de Python hors tests (bot 27 k, application 11 k, domaine 12 k, infrastructure 9 k, site 10 k), 23 000 lignes de tests (environ 1 440 tests), 39 cogs, 59 gabarits, 84 migrations, 24 fichiers de contenu JSON.
- **La mémoire du projet** :
  - `CLAUDE.md` (chargé automatiquement, environ 700 lignes : invariants, systèmes, décisions datées) et ta mémoire de projet (`MEMORY.md` et ses fiches). Lis-les **en entier**.
  - Puis `tuto.txt`, `docs/` (audits d'août et de novembre 2026 — celui d'octobre est résumé dans la mémoire —, `lancement_saison1.md`) et le `git log` des dernières semaines.
  - Ne refais pas ce qui est fait : pars des audits précédents et de ce qu'ils ont laissé ouvert.
- **Le calendrier** :
  - bêta avec 5 testeurs le 21/11/2026 ;
  - lancement de la saison 1 le mardi 01/12/2026 à 20 h (`/admin lancer_saison`), puis les fêtes de décembre ;
  - une saison dure un an.
  - Regarde la date du jour et adapte-toi (règle 1).
- **Moi** :
  - développeur solo, je parle français, tutoie-moi ;
  - autorisation permanente pour les migrations, les déploiements (`scripts/deploy_vps.sh`), le push sur `beta` et le `.env` (cf. mémoire) ;
  - j'aime voir le rendu final (aperçus fidèles, pages visuelles) et du spectaculaire pour ce qui est rare.

## 2. Ce que je veux

Une revue à 360° du projet et le maximum d'améliorations concrètes, sur tous ces plans :
- structure, architecture et qualité du code ;
- performance et ressources, fiabilité, sécurité ;
- base de données, tests, exploitation ;
- expérience des joueurs : parcours, commandes, messages, visuels ;
- game design et économie, communauté ;
- expérience d'administration : site et commandes ;
- contenu et documentation ;
- le présent (sommes-nous prêts pour le lancement ?) et l'avenir (feuille de route, évolutivité).

La grille du § 6 est un point de départ : enrichis-la de tout critère pertinent.

## 3. Règles (non négociables)

1. **Selon la date** :
   - **Avant le 01/12 à 20 h, mode « pré-lancement »** : la stabilité passe en premier.
     - Corrections et améliorations sûres : déployées sur `beta`.
     - Tout chantier lourd (refonte d'architecture, changement de moteur, migration massive) : sur une branche `chantier/<nom>`, sans déploiement, en attendant mon accord.
   - **Après, mode « saison en cours »** : de vrais joueurs jouent.
     - Aucune perte ni altération de leurs données.
     - Migrations réversibles, répétées d'abord sur une copie de la vraie base du VPS.
     - Changements visibles annoncés.
2. **Mes décisions sont actées, les invariants aussi.** Ce que `CLAUDE.md` et la mémoire disent « décidé par l'auteur » ne se remet pas en cause de ton propre chef. Exemples : heures calmes désactivées, carte mythique non fabricable, saison d'un an, pas de mode Communauté avant la fin de la bêta. Si une décision te semble mauvaise, argumente dans le rapport, chiffres à l'appui, sans la changer. Les invariants métier de `CLAUDE.md` (« non négociables ») doivent rester vrais après toute refonte.
3. **Secret** : rien, nulle part côté joueur, ne doit révéler que le cadeau de Noël dépend de l'aide à la petite fille.
4. **Rien ne disparaît sans mon accord** : ni fonctionnalité, ni commande, ni page, ni donnée, ni réglage. Une simplification peut fusionner ou déplacer, jamais faire perdre quelque chose.
5. **Ce que tu fais seul et ce que tu me demandes** :
   - **Tu fais seul** :
     - bugs, failles ;
     - performances, à comportement de jeu identique ;
     - dette technique, code mort (prouvé mort) ;
     - tests, documentation, cohérence des textes ;
     - polissage de l'interface qui suit le standard du site, accessibilité, messages d'erreur ;
     - outillage, images manquantes en ébauche.
   - **Tu me demandes** :
     - tout ce qui change une règle, un équilibrage, une économie, un taux, une récompense ou un prix ;
     - renommer ou supprimer une commande joueur ;
     - une migration qui modifie des données de joueurs ;
     - une refonte d'architecture lourde ;
     - une nouvelle dépendance importante ou un service payant ;
     - tout ce qu'un joueur percevrait comme un changement de règle.
6. **Sécurité** :
   - jamais le token Discord ni un secret dans un commit, un journal ou un message ;
   - sauvegarde de la base avant toute migration ou seed (`sqlite3 .backup`, pas `cp`) ;
   - jamais `alembic stamp` à l'aveugle ;
   - ne jamais importer `app.bot.main` (il lance le bot) ;
   - ne démarre pas de bot en local avec le token du bot de production ;
   - le bot du VPS est en ligne avec de vrais joueurs : rien qui poste sur Discord (apparition, annonce, MP) sans mon accord.
7. **Git et déploiement** (cf. `CLAUDE.md`) :
   - `git pull` avant de travailler et `git fetch` avant de pousser : le site pousse du contenu sur `beta`.
   - Commits thématiques sur `main`, tests verts.
   - Puis fusion dans `beta`, push, `deploy_vps.sh`, et vérification sur le VPS : journal, cogs chargés, pages du site. `deploy_vps.sh` ne redémarre que le bot : après un changement du site, `sudo systemctl restart sakura-webapp`.
   - `tuto.txt`, `CLAUDE.md` et `docs/sakura_content.xlsx` (régénéré par `scripts/export_content_spreadsheet.py`) mis à jour dans le même commit que ce qu'ils décrivent.
   - `?v=` des CSS/JS changé à chaque modification.
8. **Preuves** :
   - chaque constat a sa preuve (fichier:ligne, mesure, capture, requête) ;
   - chaque optimisation a son avant/après chiffré ;
   - chaque correction a son test ;
   - un doute appelle une vérification, pas une hypothèse ;
   - ne me pose pas une question dont la réponse est dans `CLAUDE.md`, la mémoire ou le code.

## 4. Méthode

Tiens une liste de tâches à jour. Écris tes constats au fil de l'eau dans le fichier du rapport (§ 5) : le contexte peut être résumé en cours de route, le fichier non.

**Phase 0 — Cartographie et mesures de référence.**
- Suite de tests complète : durée, tests lents.
- Base de démonstration (`python -m scripts.monitoring_demo --db <fichier>`) et site local.
- Carte des dépendances entre couches, plus gros fichiers et plus grosses fonctions, points chauds.
- Mesures de référence, aussi sur le VPS en lecture seule :
  - latence de la boucle asyncio ;
  - temps de réponse des commandes principales ;
  - temps et mémoire des rendus (bannière, vidéos de combat et d'assaut, cartes) ;
  - nombre de requêtes SQL par commande ;
  - temps des pages du site ;
  - mémoire du bot au repos et en pointe.

**Phase 1 — Audit à 360°** avec la grille du § 6.
- Pour chaque constat :
  - identifiant ;
  - domaine ;
  - gravité (critique / haute / moyenne / basse) ;
  - preuve ;
  - impact (joueurs, admin, exploitation) ;
  - effort ;
  - risque ;
  - recommandation ;
  - « décision requise ? ».
- Classe les constats par impact, effort et risque, et signale ce qui compte pour le lancement.

**Phase 2 — Corrections autonomes.**
- Par lots thématiques, chacun testé, déployé et vérifié.
- Commence par le critique et par ce qui sert le lancement.

**Phase 3 — Décisions.**
- Regroupe tes questions à la fin de l'audit : outil de questions, 4 au plus par appel, ta recommandation en premier, chiffres à l'appui.
- D'ici là, avance sur tout ce qui n'en dépend pas.
- Pour un gros changement : objectif, recommandation, options, coût, risque, puis mon « go ».

**Phase 4 — Grands chantiers validés.**
- Sur une branche si nécessaire.
- Répétés sur une copie de la vraie base, avec un plan de retour arrière.

**Phase 5 — Vision.**
- Feuille de route : présent → lancement → saison 1 → V2 (arbre des classes, Faille du Néant, pièces des world boss, métiers, compétences actives…).
- Plan de remboursement de la dette technique et plan d'évolutivité.

**Itère.**
- Après chaque lot, réaudite ce que tu as touché.
- Quand tu crois avoir fini, refais un tour complet de la grille.
- Tu n'as fini que quand :
  - la suite de tests passe ;
  - le site s'affiche sans erreur JavaScript (clair, sombre, téléphone) ;
  - les gains sont mesurés ;
  - le rapport est à jour ;
  - ce qui reste est listé avec sa raison.
- Si tu dois t'arrêter avant (contexte, durée), arrête-toi sur un état propre : tests verts, rapport à jour, liste de ce qui reste.

**Vérifier ce que voient les joueurs et les admins.**
- Côté Discord : regarde les rendus d'images, vérifie les embeds construits par le vrai code, teste les cogs avec de faux objets Discord.
- Côté site : pilote Chrome (CDP) sur la base de démo, en clair, en sombre et à 390 px de large.

**Sous-agents** *(paragraphe optionnel : supprime-le si tu ne veux pas)*.
- Tu as mon accord pour paralléliser l'audit avec des sous-agents, un par domaine, en lecture seule.
- Vérifie toi-même chaque constat avant de modifier le code.
- Une seule session modifie le code à la fois, ou alors des worktrees isolés.

**Mémoire.** Mets à jour la mémoire de projet avec ce qui ne se déduit pas du code : décisions, état, points en attente.

## 5. Livrables

1. **Le rapport d'audit**, publié comme les précédents :
   - une page (Artifact) avec le plan à cocher et les décisions ;
   - `docs/audit_<année>-<mois>.md` ;
   - un bandeau « archivée » sur l'ancienne page d'audit, qui renvoie vers la nouvelle.
2. **Les corrections**, en commits thématiques déployés.
3. **Les questions de décision**, groupées.
4. **La feuille de route** (présent et avenir), dans le rapport.
5. **Un bilan final** :
   - ce qui a changé, par domaine ;
   - les gains mesurés (avant → après) ;
   - ce qui reste et pourquoi ;
   - les risques ;
   - les liens.

## 6. Grille d'audit (point de départ, à enrichir)

**A. Architecture et structure**
- Respect des quatre couches (le domaine n'importe ni l'infrastructure ni le bot ; l'application n'importe pas le bot), dépendances circulaires, imports paresseux qui masquent des cycles.
- Taille et responsabilités des fichiers (`party_combat_service.py` ≈ 2 000 lignes, `admin_cog.py`, `world_boss_cog.py`, `encounter_service.py`, `profile_banner.py`…), fonctions trop longues, « objets à tout faire ».
- Duplication de règles entre le bot, le site et les scripts (stats, embeds, calculs), sources de vérité uniques.
- Cohérence des conventions : noms, dataclasses ou dicts, dépôts, cas d'usage, services, typage, valeurs magiques ou constantes nommées.
- Configuration (`settings.py`, `.env`, contenu JSON ou base), chargeurs et caches (tous relus quand le fichier change ?), état global mutable.
- Frontière entre les deux processus (bot et site) : imports croisés, rendu partagé.
- Code legacy non câblé (quêtes legacy, `GatherResourceUseCase`, tables obsolètes) : documenter, ou retirer avec mon accord.
- Gestion des erreurs (exceptions avalées, `except Exception` muets, messages montrés à l'utilisateur), journalisation structurée.

**B. Asynchrone, concurrence et fiabilité**
- Appels bloquants dans la boucle asyncio (SQLAlchemy, Pillow, fichiers, HTTP) : mesurer la latence de la boucle, déporter ce qui doit l'être.
- Courses et doubles actions (double clic, deux joueurs, deux boucles), atomicité, verrous SQLite (`database is locked`), idempotence des récompenses et des boucles.
- Tâches de fond : fréquences, chevauchements, reprise et rattrapage après un redémarrage, arrêt propre.
- Interactions Discord : `defer` avant 3 s, jetons expirés après 15 min, vues persistantes après redémarrage, messages supprimés ou introuvables.
- Résilience : Discord indisponible, limites de débit, base illisible, fichier de contenu cassé, disque plein, image absente.

**C. Performance et ressources**
- Temps de réponse de chaque commande (fixer un objectif), requêtes N+1, index manquants, `EXPLAIN QUERY PLAN` sur les requêtes chaudes.
- Rendus Pillow (bannière, cartes, calendrier, panneaux des PNJ, GIF de combat et d'assaut) : temps, mémoire, caches, poids des fichiers, file `video_slot`.
- Mémoire du bot sur 2 Go (pics pendant les vidéos, fuites, `MALLOC_*`), CPU, temps de démarrage et de synchronisation des commandes.
- Site admin : temps et nombre de requêtes des pages lourdes (Surveillance, Objets, Monstres, Cartes, Fêtes), poids des images servies.
- Poids des assets (PNG de plusieurs Mo, WebP possible ?), nettoyage des fichiers générés.
- Capacité : combien de joueurs, de combats simultanés, de vidéos par heure avant saturation ? Que faire au-delà ?

**D. Base de données et migrations**
- Schéma comparé aux modèles : contraintes (unicité, clés étrangères, NOT NULL), index, dates naïves ou avec fuseau.
- Chaîne Alembic (84 migrations) : rejouable de zéro ? à condenser pour une nouvelle saison ? migrations réversibles ?
- Croissance des tables (`game_events`, photos quotidiennes, participations) : purge, rétention, VACUUM, taille du fichier.
- Intégrité des données (orphelins, incohérences inventaire / équipement / or) et scripts de vérification.
- SQLite tient-il une saison ? Limites d'écriture concurrente, plan et coût d'une éventuelle bascule.

**E. Sécurité et vie privée**
- Site admin en HTTP sans domaine (OAuth et cookies en clair) : risques et mesures en attendant HTTPS.
- Authentification, sessions, CSRF, contrôle d'accès de chaque route (JSON et envois de fichiers compris), accès aux objets d'autrui (IDOR).
- Envois de fichiers (taille, type, chemin, images piégées), injections dans les gabarits (`|safe`, JSON dans les attributs), XSS.
- Secrets (`.env`, historique git, journaux), dépendances vulnérables (`pip-audit`), mises à jour système, SSH, pare-feu.
- Abus côté jeu : multi-comptes, transferts d'or, brocante, échanges, doubles récompenses, scripts. Ce que la Surveillance attrape et ce qu'elle rate.
- Données personnelles : ce qu'on garde, combien de temps, où.

**F. Tests et qualité**
- Couverture réelle par couche et zones non testées (cogs, vues, boucles de fond, routes du site), tests lents, tests fragiles.
- Tests d'équilibrage (monstres, boss, épreuves, défis, tour, cartes) : toujours pertinents ?
- Outillage : ruff (lint et formatage), mypy ou pyright, pre-commit, intégration continue (GitHub Actions) qui lance les tests à chaque push.
- Tests de bout en bout du parcours joueur (faux Discord) et du site (Chrome).

**G. Exploitation**
- Déploiement : durée, coupure de service, retour arrière en une commande, vérifications automatiques après déploiement.
- Sauvegardes : fréquence, rétention, **copie automatique hors du VPS** (l'ancien VPS est mort avec ses données), restauration testée et chronométrée.
- Supervision : bot hors ligne, erreurs, mémoire, disque. Ce qui manque à côté des alertes en MP existantes.
- Journaux : volume, rotation, lisibilité, niveaux.
- Procédures écrites (incident, restauration, lancement de saison, ouverture de zone, rotation des secrets) ; coûts (VPS, quotas Cloudflare).

**H. Parcours joueur**
- Arrivée → accueil → règlement → tutoriel → premiers combats → premier niveau → première pièce → première fusion → épreuve de rang → nouvelle zone → raid → fin de partie → fin de saison : la friction à chaque étape, le temps nécessaire, les abandons probables, la clarté de « que faire maintenant ? ».
- Les 5 premières minutes, la première heure, le premier jour, la première semaine : qu'est-ce qui accroche ?
- Récompenses ressenties, moments « waou », rythme, frustrations (défaites, attentes, verrous).
- Le joueur occasionnel et l'acharné, et le nouveau venu en cours de saison.
- Notifications (MP, rappels, mentions) : utiles ou envahissantes ?

**I. Commandes**
- Pour chacune (tableau de `CLAUDE.md`) : nom, paramètres, autocomplétion, aide, réponse publique ou privée, temps de réponse, erreurs, salon autorisé, rendu sur téléphone.
- Redondances, commandes peu utilisées (cf. Surveillance), regroupements possibles, cohérence des noms.
- Limites Discord : 100 commandes globales, 25 options ou sous-commandes, taille des embeds, poids des fichiers.
- Cohérence entre `/help`, `tuto.txt`, les guides épinglés et le code.

**J. Messages et visuels côté joueur**
- Embeds : couleurs, titres, pieds de page, longueur, emojis (pièce d'or), ton RP, qualité du français, cohérence d'une commande à l'autre.
- Images générées : direction artistique commune, lisibilité sur téléphone et en thème clair de Discord, contrastes, daltonisme, polices, poids.
- Vidéos de combat et d'assaut : lisibilité, durée, poids, ressenti.
- Images manquantes (ébauches restantes, objets, monstres, décors, boss) et leur chaîne de production.
- Accessibilité : texte alternatif, aucune information portée par la seule couleur.

**K. Game design et économie** (constater, mesurer, proposer — ne rien changer seul)
- Sources et puits d'or sur la saison (`scripts/simulate_season.py`), inflation, concentration, prix de la brocante.
- Progression réelle ou voulue, temps passé par zone, murs de difficulté.
- Chaque rôle (DPS, tank, soutien, généraliste) viable partout ?
- Rétention : boucles quotidiennes et hebdomadaires, objectifs de long terme, contenu de fin de saison (Faille du Néant au niveau 80).
- Équité entre nouveau venu et ancien, solo et groupe ; abus possibles des règles.
- Cartes, offrande, tour, défis, records, raid : chacun tient-il son rôle ?

**L. Communauté et social**
- Jeu en groupe (combats, raid), échanges, brocante, classements, records, annonces, salons et rôles, événements.
- Ce qui crée de l'interaction entre joueurs, ce qui en manque ; modération et règlement.

**M. Administration**
- Site (standardisé le 12/11/2026, cf. `CLAUDE.md`) : temps des tâches fréquentes, nombre de clics, aperçus fidèles partout où ça compte, recherche, actions en lot, historique et annulation des modifications de contenu (git), validation avant écriture, usage au téléphone.
- Commandes admin du bot : complètes ? dangereuses ? confirmées ?
- Surveillance et alertes : utiles, bruyantes, manquantes ? Un tableau de bord du lancement ?
- Chaîne du contenu : images, ébauches, scripts de calibrage, ouverture de zone, préparation de la saison suivante.

**N. Contenu**
- Complétude : zones, monstres, pièces, passifs, titres, cartes, quêtes, PNJ, textes.
- Cohérence des noms et des textes, fautes.
- Cohérence entre le contenu, le code, `tuto.txt` et le tableur.

**O. Documentation et maintenabilité**
- `CLAUDE.md` : exact, à jour, trop long ? Faut-il le restructurer (index, un fichier par système) pour qu'il reste utile ?
- Documentation de reprise pour un autre développeur, scripts documentés, conventions écrites.

**P. Présent : prêts pour le lancement ?**
- Checklists du 21/11 et du 01/12 (`docs/lancement_saison1.md`).
- Répétition complète du lancement sur une copie de la vraie base.
- Charge attendue, plan B.
- Points laissés à l'auteur : VPS 4 Go, domaine et HTTPS, annonces…

**Q. Avenir**
- V1.5 / V2 (arbre des classes, Faille du Néant, pièces des world boss, métiers, compétences actives, quêtes legacy) : ordre et prérequis techniques.
- Évolutivité : plusieurs serveurs Discord, beaucoup plus de joueurs, base de données, rendu des vidéos, files de travail.
- Saisons suivantes : outillage du reset, contenu de saison, nouveautés.
- Architecture cible à 6-12 mois, et le chemin pour y aller par petites étapes sûres.
