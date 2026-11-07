# Lancement de la Saison 1 — checklist

À dérouler dans l'ordre. Chaque étape dit comment la vérifier. Le lancement se fait depuis Discord : c'est `/admin lancer_saison`, et personne d'autre que toi ne doit le lancer.

## J-7 : la bêta est terminée

- [ ] `.venv/bin/python -m pytest` : tout passe.
- [ ] `.venv/bin/python -m scripts.simulate_season --cycle <mesure>` : le niveau 100 tombe entre ~250 et ~365 jours à 30 min/jour, avec la cadence de combat **mesurée en bêta** (site admin › Surveillance › Progression).
- [ ] Rythme relu dans Monde › Rythme (temps pour rejoindre, délai entre deux combats, heures calmes).
- [ ] Après tout changement du moteur, de l'arbre ou des niveaux, contenus recalibrés : `scripts/restat_mobs.py`, `scripts/restat_bosses.py`, `scripts/calibrate_rank_trials.py`, `scripts/build_tower.py`.
- [ ] `tuto.txt`, `/help` et `/demarrer` relus.
- [ ] Serveur Discord prêt : règlement, annonces, mode Communauté, salons bêta cachés, bot renommé.
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
- sauvegarde `lita_v2_avant_reset_<date>.db` ;
- combats annulés, boss arrêté, messages d'événements retirés ;
- remise à zéro de tous les joueurs et des tables de saison ;
- tout le monde au Rang F, première photo pour la Surveillance ;
- réouverture des commandes et annonce dans le général.

Vérifications :

- [ ] Le bot affiche le chemin de la sauvegarde : note-le.
- [ ] Un compte de test : `/tuto` (la Tour, puis une zone), `/profil` niveau 1, 0 or, Rang F.
- [ ] Un monstre apparaît dans la Clairière sinistre ; le bouton Lancer démarre le combat ; le récapitulatif s'affiche, avec le niveau gagné.
- [ ] `/arbre`, `/stats`, `/forgeron`, `/marchand`, `/quetes` répondent.

Recours sans le bot (s'il ne répond plus) : `.venv/bin/python -m scripts.season_reset`, puis `--saison 1 --confirm "SAISON 1"`, bot arrêté.

## Si quelque chose tourne mal (retour arrière)

```bash
sudo systemctl stop sakura-bot
cp lita_v2_avant_reset_<date>.db lita_v2.db       # la sauvegarde notée plus haut
git checkout <commit précédent> && sudo systemctl start sakura-bot
```

Les rôles Discord ne reviennent pas tout seuls : `/admin set_rank` joueur par joueur si besoin.

## Après l'ouverture

- [ ] Surveiller `journalctl -u sakura-bot -f` la première heure, et Surveillance › Vue d'ensemble chaque jour.
- [ ] Le premier raid arrive le lundi où au moins quatre joueurs actifs ont atteint le niveau 15 (`/boss moi` le rappelle aux joueurs).
- [ ] Mesurer la cadence réelle des combats et relancer le simulateur avec `--cycle`.
- [ ] Pendant la saison, un déploiement annule les combats en attente (une note s'affiche) : préférer les heures creuses.
