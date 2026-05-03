#!/bin/bash
# Script de déploiement de la branche `beta` sur le VPS.
#
# À exécuter sur le VPS (en tant qu'utilisateur ubuntu, avec sudo dispo) :
#   bash deploy_beta.sh
#
# Idempotent : peut être re-lancé sans risque. Chaque étape échoue proprement
# (set -e) et logge ce qu'elle fait. Backup de la DB systématique avant les
# migrations.

set -euo pipefail

# ----- Configuration -----
PROJECT_DIR="/home/ubuntu/SakuraLeveling"
SERVICE_NAME="sakura-bot"
PYTHON_BIN="python3.12"
BOSS_CHANNEL_ID="1500256259687972915"  # ID prod/beta fourni par le user

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

step() { echo -e "\n${BLUE}━━━ $1 ━━━${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
err()  { echo -e "${RED}✗ $1${NC}"; }

trap 'err "Échec à la ligne $LINENO. Le bot N''A PAS été redémarré. Investigue puis relance le script."; exit 1' ERR

cd "$PROJECT_DIR"

# ----- 1. Vérifs préalables -----
step "1/10 — Vérifs préalables"
if [[ ! -d .git ]]; then
    err "Pas un repo git. Vérifie PROJECT_DIR=$PROJECT_DIR"
    exit 1
fi
if ! command -v sudo >/dev/null; then
    err "sudo manquant"
    exit 1
fi
ok "Répertoire de travail : $(pwd)"
ok "Branche actuelle : $(git rev-parse --abbrev-ref HEAD)"

# ----- 2. Vérifie / installe Python 3.12 -----
step "2/10 — Python 3.12"
# On bypass le PPA deadsnakes (Launchpad bloqué côté OVH sur certains VPS)
# en utilisant `uv` qui télécharge des binaires Python pré-compilés depuis
# le CDN astral.sh — pas de dépendance à Launchpad.
if ! command -v "$PYTHON_BIN" >/dev/null; then
    if ! command -v uv >/dev/null; then
        warn "uv absent — installation"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # uv s'installe dans ~/.local/bin
        export PATH="$HOME/.local/bin:$PATH"
    fi
    warn "$PYTHON_BIN absent — installation via uv"
    uv python install 3.12
    # Localise le binaire python3.12 installé par uv
    UV_PYTHON_DIR=$(uv python find 3.12 2>/dev/null || true)
    if [[ -n "$UV_PYTHON_DIR" ]]; then
        # Crée un symlink dans /usr/local/bin pour que python3.12 soit accessible
        sudo ln -sf "$UV_PYTHON_DIR" /usr/local/bin/python3.12
    fi
    ok "Python 3.12 installé via uv"
fi
ok "$($PYTHON_BIN --version)"

# Vérifie que libcairo2 est dispo (runtime pour cairosvg → world boss & skill
# tree). On installe UNIQUEMENT le runtime (pas le -dev) pour éviter de tirer
# libglib2.0-dev qui veut des libpcre*-dev depuis des PPA potentiellement
# bloqués (Launchpad timeout sur certains VPS OVH).
if ! dpkg -l libcairo2 2>/dev/null | grep -q "^ii"; then
    warn "libcairo2 absent — installation"
    # Désactive temporairement les PPA tiers qui pourraient timeout vers
    # ppa.launchpadcontent.net (PPA ondrej/php notamment).
    DISABLED_PPAS=()
    for ppa in /etc/apt/sources.list.d/*ondrej* /etc/apt/sources.list.d/*deadsnakes*; do
        if [[ -f "$ppa" && "$ppa" != *.disabled ]]; then
            sudo mv "$ppa" "${ppa}.disabled"
            DISABLED_PPAS+=("$ppa")
        fi
    done
    sudo apt update -qq -o Acquire::ForceIPv4=true || true
    sudo apt install -y libcairo2
    # Réactive les PPA pour ne pas perturber tes autres usages
    for ppa in "${DISABLED_PPAS[@]}"; do
        sudo mv "${ppa}.disabled" "$ppa" 2>/dev/null || true
    done
fi

# ----- 3. Stop le bot -----
step "3/10 — Stop $SERVICE_NAME"
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    sudo systemctl stop "$SERVICE_NAME"
    sleep 2
    ok "$SERVICE_NAME stoppé"
else
    warn "$SERVICE_NAME n'était pas actif"
fi

# ----- 4. Backup DB -----
step "4/10 — Backup DB"
BACKUP_NAME="lita_v2_backup_pre_deploy_$(date +%Y%m%d_%H%M%S).db"
if [[ -f lita_v2.db ]]; then
    cp lita_v2.db "$BACKUP_NAME"
    SIZE=$(du -h "$BACKUP_NAME" | cut -f1)
    ok "DB sauvegardée : $BACKUP_NAME ($SIZE)"
else
    warn "lita_v2.db introuvable — pas de backup (première installation ?)"
fi

# ----- 5. Pull beta -----
step "5/10 — Pull origin/beta"
git fetch origin
git checkout beta
git reset --hard origin/beta
ok "Branche beta à jour : $(git log -1 --oneline)"

# ----- 6. (Re-)create venv si nécessaire -----
step "6/10 — Virtualenv"
NEED_RECREATE=false
if [[ ! -d .venv ]]; then
    NEED_RECREATE=true
    warn "venv absent → création"
elif ! .venv/bin/python --version 2>/dev/null | grep -q "3.12"; then
    NEED_RECREATE=true
    warn "venv pas en 3.12 → recréation"
fi

if [[ "$NEED_RECREATE" == true ]]; then
    if [[ -d .venv ]]; then
        mv .venv ".venv_old_$(date +%H%M%S)"
        ok "Ancien venv mis de côté"
    fi
    "$PYTHON_BIN" -m venv .venv
    .venv/bin/pip install --upgrade pip --quiet
    ok "venv (re)créé en $($PYTHON_BIN --version)"
fi

# ----- 7. Install deps -----
step "7/10 — Installation des dépendances"
.venv/bin/pip install -e . --quiet
.venv/bin/python -c "import discord, sqlalchemy, alembic, fastapi, cairosvg, jinja2; print('OK')" || {
    err "Au moins une dépendance manque ou échoue à l'import"
    exit 1
}
ok "Toutes les dépendances importables"

# ----- 8. Update .env -----
step "8/10 — Mise à jour du .env"
if [[ ! -f .env ]]; then
    err ".env introuvable — préexistait pas, abort"
    exit 1
fi

if grep -q "^BOSS_CHANNEL_ID=" .env; then
    if grep -q "^BOSS_CHANNEL_ID=$BOSS_CHANNEL_ID$" .env; then
        ok "BOSS_CHANNEL_ID déjà configuré"
    else
        sed -i "s/^BOSS_CHANNEL_ID=.*/BOSS_CHANNEL_ID=$BOSS_CHANNEL_ID/" .env
        ok "BOSS_CHANNEL_ID mis à jour → $BOSS_CHANNEL_ID"
    fi
else
    echo "BOSS_CHANNEL_ID=$BOSS_CHANNEL_ID" >> .env
    ok "BOSS_CHANNEL_ID ajouté → $BOSS_CHANNEL_ID"
fi

# ----- 9. Migrations + seed -----
step "9/10 — Migrations Alembic + seed"
CURRENT_REV=$(.venv/bin/alembic current 2>/dev/null | grep -oE '[a-f0-9]{12}' | head -1 || echo "none")
echo "  Révision actuelle : $CURRENT_REV"
.venv/bin/alembic upgrade head
HEAD_REV=$(.venv/bin/alembic current 2>/dev/null | grep -oE '[a-f0-9]{12}' | head -1)
ok "Migrations appliquées jusqu'à : $HEAD_REV"

.venv/bin/python -m app.infrastructure.db.seeders.seed_content 2>&1 | tail -3
ok "Seed terminé"

# ----- 10. Restart bot + check -----
step "10/10 — Restart $SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"
sleep 3
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "$SERVICE_NAME actif"
else
    err "$SERVICE_NAME n'a pas démarré ! Logs :"
    sudo journalctl -u "$SERVICE_NAME" -n 50 --no-pager
    exit 1
fi

echo
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Déploiement terminé avec succès${NC}"
echo -e "${GREEN}════════════════════════════════════════════════${NC}"
echo
echo "Pour suivre les logs en temps réel :"
echo "  sudo journalctl -u $SERVICE_NAME -f"
echo
echo "Backup DB conservé : $BACKUP_NAME"
echo "Pour rollback en cas de souci :"
echo "  sudo systemctl stop $SERVICE_NAME"
echo "  cp $BACKUP_NAME lita_v2.db"
echo "  git reset --hard cbe602b"
echo "  sudo systemctl start $SERVICE_NAME"
