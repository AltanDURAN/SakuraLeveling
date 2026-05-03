#!/bin/bash
# Expose le webapp SakuraLeveling sur Internet via nginx + systemd.
#
# Usage sur le VPS (en tant qu'utilisateur ubuntu, avec sudo dispo) :
#   bash scripts/setup_webapp_public.sh
#
# Idempotent : peut être re-lancé sans risque. Conservera la config nginx
# existante si elle est déjà identique.
#
# Après exécution, le skill tree est accessible à :
#     http://<IP_DU_VPS>/skill/<discord_id>
#
# Pour ajouter HTTPS + nom de domaine plus tard :
#     sudo certbot --nginx -d ton-domaine.com

set -euo pipefail

PROJECT_DIR="/home/ubuntu/SakuraLeveling"
WEBAPP_SERVICE="sakura-webapp"
NGINX_SITE_NAME="sakura-webapp"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
step() { echo -e "\n${BLUE}━━━ $1 ━━━${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
err()  { echo -e "${RED}✗ $1${NC}"; }

trap 'err "Échec à la ligne $LINENO. Investigue les logs ci-dessus."; exit 1' ERR

cd "$PROJECT_DIR"

step "1/6 — Vérifs"
[[ -f deploy/sakura-webapp.service ]] || { err "deploy/sakura-webapp.service introuvable"; exit 1; }
[[ -f deploy/nginx-sakura-webapp.conf ]] || { err "deploy/nginx-sakura-webapp.conf introuvable"; exit 1; }
[[ -d .venv ]] || { err ".venv absent — lance d'abord scripts/deploy_beta.sh"; exit 1; }
ok "Fichiers de déploiement présents"

step "2/6 — Install nginx"
if ! command -v nginx >/dev/null; then
    sudo apt update -qq -o Acquire::ForceIPv4=true
    sudo apt install -y nginx
    ok "nginx installé"
else
    ok "nginx déjà installé : $(nginx -v 2>&1)"
fi

step "3/6 — Service systemd sakura-webapp"
sudo cp deploy/sakura-webapp.service /etc/systemd/system/sakura-webapp.service
sudo systemctl daemon-reload
sudo systemctl enable sakura-webapp.service >/dev/null
sudo systemctl restart sakura-webapp.service
sleep 2
if sudo systemctl is-active --quiet sakura-webapp.service; then
    ok "$WEBAPP_SERVICE actif"
else
    err "$WEBAPP_SERVICE n'a pas démarré ! Logs :"
    sudo journalctl -u sakura-webapp -n 30 --no-pager
    exit 1
fi

step "4/6 — Config nginx (reverse proxy)"
sudo cp deploy/nginx-sakura-webapp.conf "/etc/nginx/sites-available/$NGINX_SITE_NAME"
# Activer le site
sudo ln -sf "/etc/nginx/sites-available/$NGINX_SITE_NAME" "/etc/nginx/sites-enabled/$NGINX_SITE_NAME"
# Désactiver le default qui peut entrer en conflit (catch-all sur port 80)
if [[ -L /etc/nginx/sites-enabled/default ]]; then
    sudo rm /etc/nginx/sites-enabled/default
    warn "Site nginx 'default' désactivé (conflit catch-all)"
fi
# Test de la conf avant reload
if sudo nginx -t 2>&1 | grep -q "syntax is ok"; then
    sudo systemctl reload nginx
    ok "nginx rechargé avec la nouvelle config"
else
    err "Config nginx invalide :"
    sudo nginx -t
    exit 1
fi

step "5/6 — Firewall (port 80)"
if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
    if ! sudo ufw status | grep -q "80/tcp"; then
        sudo ufw allow 80/tcp
        ok "ufw : port 80/tcp ouvert"
    else
        ok "ufw : port 80/tcp déjà ouvert"
    fi
else
    warn "ufw inactif ou absent — vérifie manuellement que le port 80 est ouvert au niveau OVH/iptables"
fi

step "6/6 — Smoke test"
sleep 1
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/ || echo "000")
if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "404" ]]; then
    # 200 = page d'accueil, 404 = pas de route / mais nginx → uvicorn fonctionne
    ok "Webapp répond derrière nginx (HTTP $HTTP_CODE)"
else
    err "Webapp ne répond pas correctement (HTTP $HTTP_CODE)"
    sudo journalctl -u sakura-webapp -n 20 --no-pager
    exit 1
fi

echo
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Webapp publié avec succès${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo
echo "Accès depuis Internet :"
PUBLIC_IP=$(curl -s -4 ifconfig.me 2>/dev/null || echo "<IP_DU_VPS>")
echo "  http://$PUBLIC_IP/"
echo "  http://$PUBLIC_IP/skill/<discord_id>"
echo
echo "Logs en temps réel :"
echo "  sudo journalctl -u sakura-webapp -f"
echo "  sudo tail -f /var/log/nginx/sakura-webapp.access.log"
echo
echo "Pour ajouter un nom de domaine + HTTPS :"
echo "  1. Pointe ton domaine vers $PUBLIC_IP (DNS A record)"
echo "  2. sudo apt install -y certbot python3-certbot-nginx"
echo "  3. Édite /etc/nginx/sites-available/$NGINX_SITE_NAME : remplace 'server_name _;' par 'server_name ton-domaine.com;'"
echo "  4. sudo systemctl reload nginx"
echo "  5. sudo certbot --nginx -d ton-domaine.com"
