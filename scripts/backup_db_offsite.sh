#!/usr/bin/env bash
# Sauvegarde HORS-VPS de la base SQLite vers un repo GitHub PRIVÉ.
#
# Complète backup_db.sh (qui fait la sauvegarde LOCALE). Ici on pousse la
# dernière sauvegarde cohérente vers un repo privé dédié → la progression des
# joueurs survit même à une perte totale du VPS.
#
# Prérequis (une seule fois) :
#   1. Clé ~/.ssh/github_backup + alias `Host github-backup` dans ~/.ssh/config
#      (mis en place par l'assistant).
#   2. Repo GitHub PRIVÉ (ex: sakura-db-backups) créé côté GitHub.
#   3. La clé publique ~/.ssh/github_backup.pub ajoutée à ce repo en
#      *Deploy key* avec accès WRITE.
#
# Cron (chaîné après le backup local) :
#   0 3 * * *  .../scripts/backup_db.sh >> ~/sakura-backups/backup.log 2>&1 && \
#              .../scripts/backup_db_offsite.sh >> ~/sakura-backups/backup_offsite.log 2>&1
#
# RESTAURATION (si le VPS est perdu) :
#   git clone git@github-backup:AltanDURAN/sakura-db-backups.git
#   cp sakura-db-backups/lita_v2_latest.db  <nouveau_vps>/SakuraLeveling/lita_v2.db
#   (ou une sauvegarde datée lita_v2_AAAAMMJJ_HHMMSS.db pour un point antérieur)

set -uo pipefail

LOCAL_DB="/home/ubuntu/sakura-backups/lita_v2_latest.db"
REPO_DIR="/home/ubuntu/sakura-db-backups-repo"
REMOTE="${SAKURA_BACKUP_REMOTE:-git@github-backup:AltanDURAN/sakura-db-backups.git}"
BRANCH="main"
KEEP=30   # nombre de sauvegardes datées conservées côté repo

ts() { date -u +%FT%TZ; }

if [ ! -f "$LOCAL_DB" ]; then
    echo "$(ts) ERREUR : $LOCAL_DB introuvable (backup_db.sh a-t-il tourné ?)" >&2
    exit 1
fi

# Init/clone paresseux du repo de backup.
if [ ! -d "$REPO_DIR/.git" ]; then
    rm -rf "$REPO_DIR"
    if git clone "$REMOTE" "$REPO_DIR" 2>/dev/null; then
        echo "$(ts) repo de backup cloné"
    else
        echo "$(ts) clone impossible (repo pas encore créé ou clé pas ajoutée) — init local"
        mkdir -p "$REPO_DIR"
        cd "$REPO_DIR" || exit 1
        git init -q -b "$BRANCH" 2>/dev/null || { git init -q && git checkout -qb "$BRANCH"; }
        git remote add origin "$REMOTE"
    fi
fi

cd "$REPO_DIR" || exit 1
git config user.email "backup@sakura.local"
git config user.name "sakura-backup"

# Se resynchroniser si le repo distant a déjà des commits.
git pull -q origin "$BRANCH" 2>/dev/null || true

STAMP=$(date -u +%Y%m%d_%H%M%S)
cp -f "$LOCAL_DB" "$REPO_DIR/lita_v2_$STAMP.db"
cp -f "$REPO_DIR/lita_v2_$STAMP.db" "$REPO_DIR/lita_v2_latest.db"

# Rotation : garde les KEEP sauvegardes datées les plus récentes.
ls -1t "$REPO_DIR"/lita_v2_2*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

git add -A
if ! git commit -q -m "db backup $STAMP"; then
    echo "$(ts) rien à committer"
    exit 0
fi

if git push -q -u origin "$BRANCH" 2>/dev/null; then
    echo "$(ts) OK : sauvegarde poussée hors-VPS ($STAMP)"
else
    echo "$(ts) ÉCHEC push hors-VPS (vérifie repo privé + deploy key write). Le commit local est conservé et sera repoussé au prochain run." >&2
    exit 1
fi
