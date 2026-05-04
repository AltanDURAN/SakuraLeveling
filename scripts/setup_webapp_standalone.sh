#!/bin/bash
# Expose le webapp SakuraLeveling sur Internet en mode standalone (port 8080).
# Aucune modification du nginx existant — convient quand le port 80 est déjà
# pris par un autre service (Pterodactyl, panel, autre vhost).
#
# Usage sur le VPS :
#   bash scripts/setup_webapp_standalone.sh
#
# Idempotent : peut être re-lancé sans risque.
#
# Après exécution, le skill tree est accessible à :
#     http://<IP_DU_VPS>:8080/skill/<discord_id>

set -euo pipefail

PROJECT_DIR="/home/ubuntu/SakuraLeveling"
WEBAPP_SERVICE="sakura-webapp"
# 8001 plutôt que 8080 (occupé par Pterodactyl Wings sur certains VPS).
# Doit correspondre au --port du fichier deploy/sakura-webapp.service.
WEBAPP_PORT="8001"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
step() { echo -e "\n${BLUE}━━━ $1 ━━━${NC}"; }
ok()   { echo -e "${GREEN}✓ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
err()  { echo -e "${RED}✗ $1${NC}"; }

trap 'err "Échec à la ligne $LINENO. Investigue les logs ci-dessus."; exit 1' ERR

cd "$PROJECT_DIR"

step "1/5 — Vérifs"
[[ -f deploy/sakura-webapp.service ]] || { err "deploy/sakura-webapp.service introuvable"; exit 1; }
[[ -d .venv ]] || { err ".venv absent — lance d'abord scripts/deploy_beta.sh"; exit 1; }
ok "Fichiers présents"

# Vérifie qu'aucun service important n'utilise déjà le port 8080
if sudo ss -tulpn 2>/dev/null | grep -E ":${WEBAPP_PORT}\b" | grep -v sakura-webapp >/dev/null; then
    warn "Le port $WEBAPP_PORT semble déjà occupé par un autre service :"
    sudo ss -tulpn | grep -E ":${WEBAPP_PORT}\b"
    err "Modifie WEBAPP_PORT dans ce script (ligne 14) et relance."
    exit 1
fi
ok "Port $WEBAPP_PORT libre"

step "2/5 — Service systemd sakura-webapp"
sudo cp deploy/sakura-webapp.service /etc/systemd/system/sakura-webapp.service
sudo systemctl daemon-reload
sudo systemctl enable sakura-webapp.service >/dev/null
sudo systemctl restart sakura-webapp.service
sleep 2
if sudo systemctl is-active --quiet sakura-webapp.service; then
    ok "$WEBAPP_SERVICE actif sur 0.0.0.0:$WEBAPP_PORT"
else
    err "$WEBAPP_SERVICE n'a pas démarré ! Logs :"
    sudo journalctl -u sakura-webapp -n 30 --no-pager
    exit 1
fi

step "3/5 — Firewall (port $WEBAPP_PORT)"
if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
    if ! sudo ufw status | grep -q "${WEBAPP_PORT}/tcp"; then
        sudo ufw allow "${WEBAPP_PORT}/tcp" comment "SakuraLeveling webapp"
        ok "ufw : port $WEBAPP_PORT/tcp ouvert"
    else
        ok "ufw : port $WEBAPP_PORT/tcp déjà ouvert"
    fi
else
    warn "ufw inactif ou absent — vérifie manuellement le firewall (OVH IP filtering, iptables, etc.)"
fi

step "4/5 — Smoke test local"
sleep 1
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${WEBAPP_PORT}/" || echo "000")
if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "404" ]]; then
    ok "Webapp répond sur 127.0.0.1:$WEBAPP_PORT (HTTP $HTTP_CODE)"
else
    err "Webapp ne répond pas correctement (HTTP $HTTP_CODE)"
    sudo journalctl -u sakura-webapp -n 20 --no-pager
    exit 1
fi

step "5/5 — Smoke test public"
PUBLIC_IP=$(curl -s -4 ifconfig.me 2>/dev/null || echo "")
if [[ -n "$PUBLIC_IP" ]]; then
    PUBLIC_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://${PUBLIC_IP}:${WEBAPP_PORT}/" || echo "000")
    if [[ "$PUBLIC_CODE" == "200" || "$PUBLIC_CODE" == "404" ]]; then
        ok "Webapp accessible publiquement sur http://${PUBLIC_IP}:${WEBAPP_PORT}/"
    else
        warn "Webapp local OK mais pas accessible publiquement (HTTP $PUBLIC_CODE)"
        warn "  → Vérifier le firewall OVH (manager OVH → ton VPS → IP filtering)"
    fi
fi

echo
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Webapp publié en standalone sur le port $WEBAPP_PORT${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo
PUBLIC_IP=${PUBLIC_IP:-"<IP_DU_VPS>"}
echo "Accès public :"
echo "  http://${PUBLIC_IP}:${WEBAPP_PORT}/"
echo "  http://${PUBLIC_IP}:${WEBAPP_PORT}/skill/<discord_id>"
echo
echo "À mettre dans le .env du bot :"
echo "  WEBAPP_BASE_URL=http://${PUBLIC_IP}:${WEBAPP_PORT}/"
echo "Puis redémarre le bot :"
echo "  sudo systemctl restart sakura-bot"
echo
echo "Logs en temps réel :"
echo "  sudo journalctl -u sakura-webapp -f"
echo
echo "Quand tu auras un sous-domaine (ex sakura.rammohan.fr) :"
echo "  1. Pointe le DNS A record vers ${PUBLIC_IP}"
echo "  2. Crée un vhost nginx (reverse proxy vers 127.0.0.1:${WEBAPP_PORT}) — je peux te générer la conf"
echo "  3. certbot --nginx -d sakura.rammohan.fr pour HTTPS"
echo "  4. Modifie cette unité pour bind sur 127.0.0.1 (sécurité : ne plus exposer le port direct)"
