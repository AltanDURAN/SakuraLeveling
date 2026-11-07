#!/usr/bin/env bash
# Sécurise le VPS (audit d'ouverture, 07/11/2026 : 14 298 tentatives de mot de
# passe en 48 h). À lancer SUR le VPS, sans danger à relancer :
#
#   bash scripts/harden_vps.sh           # applique, avec retour arrière automatique
#   bash scripts/harden_vps.sh --confirm # à lancer depuis une NOUVELLE connexion :
#                                        # annule le retour arrière
#
# - SSH : plus de mot de passe. Root reste possible par clé (le déploiement de
#   l'autre bot du serveur passe par là) ; `ubuntu` a sudo sans mot de passe.
# - ufw : seuls 22, 80 et 443 sont ouverts.
# - fail2ban : bannit une heure après 5 échecs.
#
# Filet de sécurité : sans --confirm dans les 5 minutes, SSH et ufw reviennent
# tout seuls à leur état d'avant.

set -euo pipefail

SSH_CONF=/etc/ssh/sshd_config.d/00-sakura-hardening.conf
ROLLBACK_UNIT=sakura-hardening-rollback

if [ "${1:-}" = "--confirm" ]; then
    sudo systemctl stop "$ROLLBACK_UNIT.timer" 2>/dev/null || true
    echo "Retour arrière annulé : la sécurisation est définitive."
    exit 0
fi

echo "==> 1. Paquets"
sudo apt-get update -y >/dev/null
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban ufw >/dev/null

echo "==> 2. Retour arrière dans 5 minutes"
sudo systemctl stop "$ROLLBACK_UNIT.timer" 2>/dev/null || true
sudo systemd-run --on-active=5min --unit="$ROLLBACK_UNIT" \
    /bin/sh -c "rm -f $SSH_CONF; systemctl reload ssh; ufw --force disable"

echo "==> 3. SSH sans mot de passe"
sudo tee "$SSH_CONF" >/dev/null <<'CONF'
# Lu avant 50-cloud-init.conf : le premier réglage gagne.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 3
CONF
sudo sshd -t
sudo systemctl reload ssh

echo "==> 4. Pare-feu"
sudo ufw default deny incoming >/dev/null
sudo ufw default allow outgoing >/dev/null
sudo ufw allow 22/tcp >/dev/null
sudo ufw allow 80/tcp >/dev/null
sudo ufw allow 443/tcp >/dev/null
sudo ufw --force enable >/dev/null

echo "==> 5. fail2ban"
sudo tee /etc/fail2ban/jail.d/sakura.local >/dev/null <<'CONF'
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
CONF
sudo systemctl enable --now fail2ban >/dev/null
sudo systemctl restart fail2ban

echo
sudo sshd -T | grep -E "^(passwordauthentication|permitrootlogin|maxauthtries) "
sudo ufw status | sed -n 1,8p
echo
echo "⚠️ Ouvre une NOUVELLE connexion et lance : bash scripts/harden_vps.sh --confirm"
