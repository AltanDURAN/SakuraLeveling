#!/usr/bin/env bash
# Script de déploiement à exécuter SUR le VPS (pas en local).
# Usage : ssh ubuntu@151.80.233.231, puis :
#   cd /home/ubuntu/SakuraLeveling && bash scripts/deploy_vps.sh

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
cp "$DB_FILE" "lita_v2_backup_$(date +%Y%m%d_%H%M%S).db"
ls -lh lita_v2_backup_*.db | tail -3

echo "==> 2. Pull origin/$BRANCH"
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"
echo "    HEAD : $(git rev-parse --short HEAD) — $(git log -1 --pretty=%s)"

echo "==> 3. Alembic upgrade head"
.venv/bin/alembic current
.venv/bin/alembic upgrade head
.venv/bin/alembic current

echo "==> 4. Seed contenu (idempotent)"
.venv/bin/python -m app.infrastructure.db.seeders.seed_content

echo "==> 5. Restart services"
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
