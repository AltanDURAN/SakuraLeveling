# Lancement de la Saison 1 — checklist

À dérouler dans l'ordre. Chaque étape dit comment la vérifier. Le lancement se fait depuis Discord : c'est `/admin lancer_saison`, et personne d'autre que toi ne doit le lancer.

## J-7 : la bêta est terminée

- [ ] `.venv/bin/python -m pytest` : tout passe.
- [ ] `.venv/bin/python -m scripts.simulate_season --cycle <mesure>` : le niveau 100 tombe entre ~250 et ~365 jours à 30 min/jour, avec la cadence de combat **mesurée en bêta** (site admin › Surveillance › Progression).
- [ ] Rythme relu dans Monde › Rythme (temps pour rejoindre, délai entre deux combats). Les heures calmes restent désactivées (0 → 0) : ceux qui jouent la nuit doivent pouvoir farmer.
- [ ] Après tout changement du moteur, de l'arbre ou des niveaux, contenus recalibrés : `scripts/restat_mobs.py`, `scripts/restat_bosses.py`, `scripts/calibrate_rank_trials.py`, `scripts/build_tower.py`.
- [ ] `tuto.txt`, `/help` et `/demarrer` relus.
- [ ] Serveur Discord prêt : annonces, mode Communauté, salons bêta cachés, bot renommé. Le règlement est posté par le bot (texte : `app/infrastructure/content/rules.json`, à relire).
- [ ] Images : monstres, décors, boss, arène, portrait de Hana.

## J-1 : déploiement et sauvegardes

Sur la machine de dev :

```bash
git checkout beta && git merge main && git push origin beta && git checkout main
ssh sakura-vps "cd /home/ubuntu/SakuraLeveling && bash scripts/deploy_vps.sh"
```

- [ ] Le déploiement finit sans erreur, le journal affiche tous les cogs chargés.
- [ ] Sauvegarde hors serveur récente : `scripts/backup_db_offsite.sh` (ou `scp sakura-vps:~/sakura-backups/lita_v2_latest.db ./`).
- [ ] La sauvegarde quotidienne tourne (`ls ~/sakura-backups/` sur le VPS, fichier du jour présent).
- [ ] Répétition sur une copie : `scripts/season_reset.py` en aperçu donne les bons chiffres.

## Jour J : le lancement

Depuis Discord, dans n'importe quel salon :

1. `/admin lancer_saison numero:1` (ajoute `annonce:` pour personnaliser le message).
2. Lis l'aperçu, clique, puis tape **SAISON 1** dans la fenêtre.

Le bot fait tout dans cet ordre, et s'arrête sans rien toucher si la sauvegarde échoue :

- commandes des joueurs fermées (les admins passent), attente de celles en cours ;
- sauvegarde `lita_v2_avant_saison_1_<date>.db` ;
- combats annulés, boss arrêté, messages d'événements retirés ;
- remise à zéro de tous les joueurs et des tables de saison ;
- tout le monde repart du règlement, toi compris : rangs et Aventurier retirés à chaque membre, règlement à réaccepter, tutoriel à refaire ou passer ;
- première photo pour la Surveillance ;
- réouverture des commandes et annonce dans le salon d'accueil, le seul que tout le monde voit encore (avec le règlement).

Vérifications :

- [ ] Le bot affiche le chemin de la sauvegarde : note-le.
- [ ] Un compte de test ne voit que l'accueil et le règlement. Il accepte le règlement : Rang F, le tutoriel s'ouvre. `/tuto` (la Tour, puis une zone), puis fin ou « Passer » : Aventurier, le général s'ouvre. `/profil` : niveau 1, 0 or, Rang F.
- [ ] Un monstre apparaît dans la Clairière sinistre ; le bouton Lancer démarre le combat ; le récapitulatif s'affiche, avec le niveau gagné.
- [ ] `/arbre`, `/stats`, `/forgeron`, `/marchand`, `/quetes` répondent.

Recours sans le bot (s'il ne répond plus) : `.venv/bin/python -m scripts.season_reset`, puis `--saison 1 --confirm "SAISON 1"`, bot arrêté.

## Si quelque chose tourne mal (retour arrière)

```bash
sudo systemctl stop sakura-bot sakura-webapp           # le site a aussi la base ouverte
rm -f lita_v2.db-wal lita_v2.db-shm                     # journal WAL de la base remplacée
cp lita_v2_avant_saison_1_<date>.db lita_v2.db          # la sauvegarde notée plus haut
git checkout <commit précédent> && sudo systemctl start sakura-bot sakura-webapp
```

Les rôles Discord reviennent tout seuls au démarrage : le bot rend à chacun ce que dit la base restaurée (règlement accepté → rang gagné, tutoriel fini ou passé → Aventurier).

## Après l'ouverture

- [ ] Surveiller `journalctl -u sakura-bot -f` la première heure, et Surveillance › Vue d'ensemble chaque jour.
- [ ] Le premier raid arrive le lundi où au moins quatre joueurs actifs ont atteint le niveau 15 (`/boss moi` le rappelle aux joueurs).
- [ ] Mesurer la cadence réelle des combats et relancer le simulateur avec `--cycle`.
- [ ] Pendant la saison, un déploiement annule les combats en attente (une note s'affiche) : préférer les heures creuses.

## La durée de la saison

Une saison dure un an, puis tout repart à zéro sans tableau d'honneur. La saison 2 se lance de la même façon, un an après : `/admin lancer_saison numero:2`.

## Ouvrir la Faille du Néant

Elle s'annonce quand les premiers joueurs atteignent le niveau 80. Le bot te prévient deux fois par MP : 21 jours avant au rythme du joueur le plus rapide (« Fin du contenu dans N jours »), puis quand un joueur y arrive.

Ça peut venir vite. Niveau 80 simulé selon le temps de jeu, du joueur qui clique sur Lancer à celui qui attend la fin du compte à rebours :

| Temps de jeu | Niveau 80 |
|---|---|
| 8 h par jour | J11 à J20 |
| 4 h par jour | J21 à J38 |
| 2 h par jour | J40 à J70 |
| 1 h par jour | J73 à J125 |
| 30 min par jour | J132 à J209 |

Le simulateur compte seulement l'XP : il ignore les défaites, l'équipement et les épreuves de rang, donc un vrai joueur ira moins vite. Prépare quand même les images dès le premier mois.

1. Crée le salon de la zone et ajoute son identifiant à `COMMAND_CHANNELS` (dans le `.env` du VPS et dans `scripts/deploy_beta.sh`). Ne règle pas ses permissions à la main : `/admin acces` s'en charge à l'étape 5.
2. Prépare les images : les 7 monstres de la famille `abyssal`, leurs 7 pièces et le décor.
3. Regarde l'aperçu : `.venv/bin/python -m scripts.open_zones S=<id du salon>`.
4. Applique : la même commande avec `--write`. Elle ouvre la zone, recalibre les élites et active le cor de chasse. Essayé le 07/11/2026 sur une copie : tous les tests passent.
5. Lance `pytest`, commite et déploie : le seed et le redémarrage du bot appliquent tout. Puis `/admin acces` : l'aperçu doit montrer le salon de la zone passer au « Rang S et plus » ; applique.
6. Règle le décor de la zone depuis l'admin, puis annonce l'ouverture.
