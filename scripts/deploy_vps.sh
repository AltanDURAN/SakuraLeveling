#!/usr/bin/env bash
# Script de déploiement à exécuter SUR le VPS (pas en local).
# Usage : ssh sakura-vps "cd /home/ubuntu/SakuraLeveling && bash scripts/deploy_vps.sh"

set -euo pipefail

REPO_DIR="/home/ubuntu/SakuraLeveling"
DB_FILE="lita_v2.db"
BRANCH="beta"

cd "$REPO_DIR"

echo "==> 0. Vérifier la présence de NotoColorEmoji (pour la bannière /profile)"
if [ ! -f /usr/share/fonts/truetype/noto/NotoColorEmoji.ttf ]; then
    echo "    Installation de fonts-noto-color-emoji…"
    sudo apt-get update -y >/dev/null
    sudo apt-get install -y fonts-noto-color-emoji
else
    echo "    NotoColorEmoji déjà présent."
fi

echo "==> 1. Backup DB"
# `.backup` et PAS `cp` : la base est en WAL, les écritures récentes vivent
# dans lita_v2.db-wal tant qu'elles ne sont pas reportées — un cp du seul .db
# donnait une sauvegarde périmée (constaté le 25/10/2026 : fichier du 24, WAL
# de 1,3 Mo). `.backup` prend un instantané cohérent, bot en marche compris.
sqlite3 "$DB_FILE" ".backup 'lita_v2_backup_$(date +%Y%m%d_%H%M%S).db'"
ls -lh lita_v2_backup_*.db | tail -3
# Rotation : les 10 sauvegardes de déploiement les plus récentes suffisent
# (la sauvegarde QUOTIDIENNE vit à part, dans ~/sakura-backups, + hors site).
# Les sauvegardes nommées à la main (ex. lita_v2_backup_saison1_*) sont gardées.
ls -1t lita_v2_backup_2*.db 2>/dev/null | tail -n +11 | xargs -r rm -f

echo "==> 2. Pull origin/$BRANCH"
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "    HEAD : $(git rev-parse --short HEAD) — $(git log -1 --pretty=%s)"

echo "==> 2.5. Sync deps (requirements.lock → .venv)"
# Versions EXACTES, testées sous le Python du VPS (3.12) : `pip install -e .`
# seul ne met jamais à jour un paquet déjà installé (`>=` dans pyproject), la
# prod avait dérivé (Pillow, aiohttp… 88 failles connues fin octobre 2026).
# Mettre à jour : cf. « Dépendances » dans CLAUDE.md. Un échec ARRÊTE le
# déploiement avant le redémarrage : le bot garde son ancien processus.
.venv/bin/pip install --quiet -r requirements.lock
.venv/bin/pip install --quiet --no-deps -e .
.venv/bin/pip check

echo "==> 3. Alembic upgrade head"
.venv/bin/alembic current
.venv/bin/alembic upgrade head
.venv/bin/alembic current

echo "==> 4. Seed contenu (idempotent)"
.venv/bin/python -m app.infrastructure.db.seeders.seed_content

echo "==> 5. Restart services"
# Les unités systemd suivent le dépôt (réglages mémoire, adresse d'écoute).
sudo install -m 644 deploy/sakura-bot.service deploy/sakura-webapp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart sakura-bot
# Note historique : on filtrait via `systemctl list-unit-files | grep`
# mais la sortie de systemctl est tronquée selon la largeur du tty
# (en SSH non-interactif, "sakura-webapp.service" devient "sakura-...service")
# donc le grep ratait le match. On utilise maintenant `cat`, qui se base
# directement sur la présence du fichier d'unit et n'est pas affecté.
if sudo systemctl cat sakura-webapp.service >/dev/null 2>&1; then
    sudo systemctl restart sakura-webapp
    echo "    sakura-webapp restarted"
else
    echo "    sakura-webapp.service absent, skip"
fi
sleep 3

echo "==> 6. Statut bot"
sudo systemctl status sakura-bot --no-pager -n 5 || true

echo "==> 7. Derniers logs"
sudo journalctl -u sakura-bot -n 40 --no-pager

echo "==> Déploiement terminé."
