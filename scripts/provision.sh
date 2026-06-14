#!/usr/bin/env bash
# Provisioning PREMIER BOOT : transforme une VM Ubuntu vierge (Oracle Always
# Free, ou n'importe quel Ubuntu 22.04/24.04) en bot SakuraLeveling qui tourne.
#
# Idempotent : ré-exécutable sans casse. Pour les MISES À JOUR ensuite, utilise
# scripts/deploy_vps.sh.
#
# Usage sur la VM fraîche (user ubuntu) :
#   sudo apt-get update -y && sudo apt-get install -y git
#   git clone https://github.com/AltanDURAN/SakuraLeveling.git ~/SakuraLeveling
#   cd ~/SakuraLeveling && git checkout beta
#   bash scripts/provision.sh
#
# Le script s'arrête après avoir créé un .env SQUELETTE si .env est absent :
# tu le remplis (token Discord, IDs…), puis tu relances provision.sh.

set -euo pipefail

REPO_DIR="/home/ubuntu/SakuraLeveling"
BRANCH="beta"
PY=python3

cd "$REPO_DIR"

echo "==> 1. Dépendances système (apt)"
sudo apt-get update -y
# python venv + libs natives pour Pillow/cairosvg + police emoji couleur.
sudo apt-get install -y \
    python3 python3-venv python3-dev build-essential \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev \
    libjpeg-dev zlib1g-dev libfreetype6-dev \
    fonts-noto-color-emoji \
    sqlite3 git

echo "==> 2. Virtualenv + dépendances Python"
if [ ! -d .venv ]; then
    "$PY" -m venv .venv
fi
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -e . --quiet
echo "    deps installées."

echo "==> 3. Fichier .env"
if [ ! -f .env ]; then
    SECRET=$(.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))")
    cat > .env <<EOF
# --- Bot Discord ---
DISCORD_TOKEN=METTRE_TON_TOKEN_ICI
DATABASE_URL=sqlite:///lita_v2.db
ENV=production
DEBUG=false
BETA_CHANNEL_ID=METTRE_ID
ENCOUNTER_CHANNEL_ID=METTRE_ID
BOSS_CHANNEL_ID=
ADMIN_DISCORD_IDS=METTRE_TON_DISCORD_ID

# --- Webapp (arbre public + admin OAuth) ---
WEBAPP_BASE_URL=http://CHANGER_IP_PUBLIQUE:8001
DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
OAUTH_REDIRECT_URI=http://CHANGER_IP_PUBLIQUE:8001/admin/auth/callback
# Généré automatiquement — ne pas remettre la valeur par défaut publique.
ADMIN_SESSION_SECRET=$SECRET
EOF
    echo ""
    echo "  ⚠️  .env SQUELETTE créé (ADMIN_SESSION_SECRET déjà généré)."
    echo "      Remplis DISCORD_TOKEN, BETA_CHANNEL_ID, ENCOUNTER_CHANNEL_ID,"
    echo "      ADMIN_DISCORD_IDS, puis relance : bash scripts/provision.sh"
    exit 0
fi

if grep -q "METTRE_TON_TOKEN_ICI" .env; then
    echo "  ⚠️  .env existe mais DISCORD_TOKEN n'est pas renseigné. Édite .env puis relance."
    exit 1
fi
echo "    .env présent et renseigné."

echo "==> 4. Base de données (migrations + seed)"
.venv/bin/alembic upgrade head
.venv/bin/python -m app.infrastructure.db.seeders.seed_content

echo "==> 5. Installation des services systemd"
sudo cp deploy/sakura-bot.service /etc/systemd/system/sakura-bot.service
sudo cp deploy/sakura-webapp.service /etc/systemd/system/sakura-webapp.service
sudo systemctl daemon-reload
sudo systemctl enable sakura-bot sakura-webapp
sudo systemctl restart sakura-bot sakura-webapp
sleep 3

echo "==> 6. Ouverture du port webapp 8001 (firewall LOCAL Ubuntu)"
# Les images Ubuntu d'Oracle ont des règles iptables qui DROP tout sauf SSH.
# On autorise le 8001 entrant (le bot lui n'a besoin que de sortant).
if sudo iptables -C INPUT -p tcp --dport 8001 -j ACCEPT 2>/dev/null; then
    echo "    règle 8001 déjà présente."
else
    sudo iptables -I INPUT 6 -p tcp --dport 8001 -j ACCEPT || true
    # Persiste la règle si netfilter-persistent est dispo.
    sudo netfilter-persistent save 2>/dev/null || \
        echo "    (installe iptables-persistent pour persister la règle au reboot)"
fi
echo "    ⚠️  N'oublie pas la SECURITY LIST / NSG côté console Oracle : "
echo "       ingress TCP 8001 depuis 0.0.0.0/0 (sinon la webapp reste injoignable)."

echo "==> 7. Statut"
sudo systemctl --no-pager status sakura-bot -n 5 || true
echo ""
echo "==> Provisioning terminé. Logs live : journalctl -u sakura-bot -f"
