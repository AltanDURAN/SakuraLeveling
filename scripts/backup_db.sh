#!/usr/bin/env bash
# Sauvegarde de la base SQLite, à lancer SUR le serveur (cron quotidien).
#
# Utilise `sqlite3 .backup` (copie cohérente même si le bot écrit pendant la
# sauvegarde, contrairement à un simple cp). Garde les N dernières + une copie
# "latest" facile à récupérer (scp) depuis ta machine.
#
# Cron conseillé (crontab -e) :
#   0 3 * * *  /home/ubuntu/SakuraLeveling/scripts/backup_db.sh >> /home/ubuntu/sakura-backups/backup.log 2>&1
#
# Récupérer la dernière sauvegarde sur ta machine :
#   scp sakura-vps:~/sakura-backups/lita_v2_latest.db ./

set -euo pipefail

REPO_DIR="/home/ubuntu/SakuraLeveling"
DB_FILE="$REPO_DIR/lita_v2.db"
BACKUP_DIR="/home/ubuntu/sakura-backups"
KEEP=14   # nombre de sauvegardes horodatées à conserver

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_FILE" ]; then
    echo "$(date -u +%FT%TZ) ERREUR : $DB_FILE introuvable" >&2
    exit 1
fi

STAMP=$(date -u +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/lita_v2_$STAMP.db"

# .backup = snapshot cohérent (lock court), sûr même bot en marche.
sqlite3 "$DB_FILE" ".backup '$DEST'"
cp -f "$DEST" "$BACKUP_DIR/lita_v2_latest.db"

# Rotation : on ne garde que les KEEP plus récentes (hors latest).
ls -1t "$BACKUP_DIR"/lita_v2_2*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "$(date -u +%FT%TZ) OK : $DEST ($(du -h "$DEST" | cut -f1))"
