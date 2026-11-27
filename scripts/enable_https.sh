#!/usr/bin/env bash
# Passe le site en HTTPS. À lancer SUR le VPS :
#
#   bash scripts/enable_https.sh ton-domaine.fr
#
# Depuis le 28/11/2026, le site est sur l'adresse gratuite
# sakura.87.106.125.165.sslip.io (décision de l'auteur, en attendant un vrai
# domaine). Relancer le script avec le nouveau domaine suffit pour en changer :
# l'ancien nom est remplacé, et tout ce qui arrive en HTTP (adresse IP comprise)
# est renvoyé vers le nouveau.
#
# Avant : le domaine pointe vers l'IP du VPS (enregistrement A), et les ports 80
# et 443 sont ouverts chez IONOS. Après, à faire à la main dans le Discord
# Developer Portal (OAuth2 → Redirects) : ajouter https://<domaine>/admin/auth/callback.

set -euo pipefail

DOMAIN="${1:?Usage : bash scripts/enable_https.sh ton-domaine.fr}"
ENV_FILE=/home/ubuntu/SakuraLeveling/.env
SITE=/etc/nginx/sites-available/sakura-webapp

echo "==> 1. Le domaine pointe-t-il ici ?"
HERE=$(curl -s4 https://ifconfig.me)
THERE=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1 {print $1}')
if [ "$HERE" != "$THERE" ]; then
    echo "❌ $DOMAIN pointe vers ${THERE:-rien}, le VPS est $HERE. Corrige le DNS et relance."
    exit 1
fi

echo "==> 2. Certificat"
sudo apt-get update -y >/dev/null
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y certbot python3-certbot-nginx >/dev/null
sudo cp "$SITE" "/home/ubuntu/sakura-webapp.nginx.avant_https"
sudo sed -i -E "s/server_name [^;]+;/server_name $DOMAIN;/" "$SITE"
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect
# Certbot répond 404 à toute autre adresse (l'IP nue, un ancien nom) : on les renvoie ici,
# pour que les vieux liens postés sur Discord marchent encore.
sudo sed -i -E "s|return 404; # managed by Certbot|return 301 https://$DOMAIN\$request_uri;|; s|return 301 https://[^\$]+\\\$request_uri;|return 301 https://$DOMAIN\$request_uri;|" "$SITE"
sudo nginx -t
sudo systemctl reload nginx

echo "==> 3. Adresses du site"
cp "$ENV_FILE" "$ENV_FILE.avant_https"
chmod 600 "$ENV_FILE.avant_https"
set_env() {
    if grep -q "^$1=" "$ENV_FILE"; then
        sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"
    else
        echo "$1=$2" >> "$ENV_FILE"
    fi
}
set_env WEBAPP_BASE_URL "https://$DOMAIN"
set_env OAUTH_REDIRECT_URI "https://$DOMAIN/admin/auth/callback"
set_env ADMIN_COOKIE_SECURE 1

sudo systemctl restart sakura-webapp sakura-bot
echo
echo "✅ https://$DOMAIN est en ligne, le renouvellement du certificat est automatique."
echo "⚠️ Reste à ajouter https://$DOMAIN/admin/auth/callback dans le Discord Developer Portal."
