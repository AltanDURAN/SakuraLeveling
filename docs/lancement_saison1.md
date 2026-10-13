# Lancement de la Saison 1 — checklist

À dérouler dans l'ordre le jour de l'ouverture. Chaque étape dit comment la vérifier.

## J-7 : la bêta fermée est terminée

- [ ] Les must have de la roadmap sont cochés.
- [ ] `.venv/bin/python -m pytest` : tout passe.
- [ ] `.venv/bin/python -m scripts.simulate_season` : le niveau 100 tombe entre ~250 et ~365 jours à 30 min/jour, avec la cadence de combat **mesurée en bêta** (`--cycle`).
- [ ] Les contenus lus au démarrage sont à jour sur `beta` : `skill_tree.json`, `artisans.json`, `farm_zones.json`, `events.json`, `rank_trials.json`.
- [ ] Gardiens d'épreuve, monstres et boss recalibrés **après** le remplissage de l'arbre :
      `scripts/restat_mobs.py`, `scripts/restat_bosses.py`, `scripts/calibrate_rank_trials.py`.
- [ ] `tuto.txt`, `/help` et `/demarrer` relus.

## J-1 : sauvegardes

- [ ] Sauvegarde hors serveur récente : `scripts/backup_db_offsite.sh` (ou `scp sakura-vps:~/sakura-backups/lita_v2_latest.db ./`).
- [ ] La sauvegarde quotidienne tourne (`ls ~/sakura-backups/` sur le VPS, fichier du jour présent).

## Jour J : mise à jour et remise à zéro

Sur la machine de dev :

```bash
git checkout beta && git merge main && git push origin beta && git checkout main
```

Sur le VPS (`ssh sakura-vps`) :

```bash
cd /home/ubuntu/SakuraLeveling
sudo systemctl stop sakura-bot                    # personne ne joue pendant le reset
bash scripts/deploy_vps.sh                         # backup + pull + migrations + seed (redémarre le bot)
sudo systemctl stop sakura-bot                    # on le ré-arrête pour le reset
.venv/bin/python -m scripts.season_reset           # APERÇU : relire les chiffres
.venv/bin/python -m scripts.season_reset --confirm "SAISON 1"
sudo systemctl start sakura-bot
sudo systemctl restart sakura-webapp
sudo journalctl -u sakura-bot -n 50 --no-pager     # « Cogs chargés : 22/22 (0 échec) »
```

Vérifications :

- [ ] Le script affiche le chemin de la sauvegarde `lita_v2_avant_reset_<date>.db` : noter ce chemin.
- [ ] Dans l'admin web, **Actions rapides** → journal : la commande `reset_rank_roles` passe en « done » dans les secondes qui suivent le démarrage du bot (sinon : le bot n'a pas « Gérer les rôles », ou son rôle est sous les rôles de rang).
- [ ] Un compte de test : `/demarrer` → rôle Rang F, `/profil` niveau 1, 0 or.
- [ ] Un monstre apparaît dans la Clairière sinistre ; un combat se termine avec récompenses.
- [ ] `/arbre`, `/stats`, `/forgeron`, `/marchand`, `/quetes` répondent.

## Si quelque chose tourne mal (retour arrière)

```bash
sudo systemctl stop sakura-bot
cp lita_v2_avant_reset_<date>.db lita_v2.db       # la sauvegarde notée plus haut
git checkout <commit précédent> && sudo systemctl start sakura-bot
```

Les rôles Discord ne reviennent pas tout seuls : `/admin set_rank` joueur par joueur si besoin.

## Après l'ouverture

- [ ] Annonce dans le salon général (règles de la saison, `/demarrer`).
- [ ] Surveiller `journalctl -u sakura-bot -f` la première heure.
- [ ] Mesurer la cadence réelle des combats et relancer le simulateur avec `--cycle`.
