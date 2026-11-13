#!/usr/bin/env bash
# Sauvegarde HORS-VPS de la base SQLite vers un dépôt GitHub PRIVÉ.
#
# Complète backup_db.sh (sauvegarde LOCALE, chaque nuit). Ici la dernière
# sauvegarde locale part vers un dépôt privé : la progression des joueurs
# survit à une perte totale du serveur (c'est arrivé à l'ancien VPS).
#
# Version du 13/11/2026 — pourquoi elle a changé :
#   - avant, la base entière (non compressée) était commitée chaque nuit dans
#     la branche `main` : l'historique grossissait sans fin, et GitHub refuse
#     un fichier de plus de 100 Mo — la base y arrive en quelques mois de
#     saison (~330 Mo après un an à 50 joueurs). La sauvegarde serait tombée
#     en panne en silence.
#   - désormais : fichier COMPRESSÉ (et découpé au-delà de 90 Mo), 7 jours +
#     4 dimanches gardés, dans la branche `sauvegardes` réécrite chaque nuit
#     (un seul commit : la taille du dépôt reste bornée). L'ancienne branche
#     `main` n'est plus touchée : son historique reste là.
#   - la sauvegarde est VÉRIFIÉE avant de partir, et un témoin
#     (~/sakura-backups/offsite_ok) dit quand la dernière copie a réussi : la
#     Surveillance du site alerte les admins s'il vieillit (règle « backup »).
#
# Prérequis (une seule fois, déjà en place sur le VPS) :
#   1. Clé ~/.ssh/github_backup + alias `Host github-backup` dans ~/.ssh/config.
#   2. Dépôt GitHub PRIVÉ (sakura-db-backups).
#   3. La clé publique ajoutée à ce dépôt en « Deploy key » avec accès en écriture.
#
# Cron (chaîné après la sauvegarde locale) :
#   0 3 * * *  .../scripts/backup_db.sh >> ~/sakura-backups/backup.log 2>&1 && \
#              .../scripts/backup_db_offsite.sh >> ~/sakura-backups/backup_offsite.log 2>&1
#
# RESTAURATION (serveur perdu) — testée le 13/11/2026 :
#   git clone --branch sauvegardes --depth 1 git@github-backup:AltanDURAN/sakura-db-backups.git
#   cd sakura-db-backups/jours/<la plus récente>
#   cat lita_v2.db.gz* | gunzip > lita_v2.db          # marche avec ou sans découpage
#   sqlite3 lita_v2.db "PRAGMA integrity_check;"      # doit répondre « ok »
#   # puis : bot et site arrêtés, copier lita_v2.db dans SakuraLeveling/

set -uo pipefail

LOCAL_DB="${SAKURA_BACKUP_SOURCE:-/home/ubuntu/sakura-backups/lita_v2_latest.db}"
REPO_DIR="${SAKURA_BACKUP_REPO_DIR:-/home/ubuntu/sakura-db-backups-repo}"
REMOTE="${SAKURA_BACKUP_REMOTE:-git@github-backup:AltanDURAN/sakura-db-backups.git}"
MARKER="${SAKURA_BACKUP_MARKER:-/home/ubuntu/sakura-backups/offsite_ok}"
BRANCH="sauvegardes"
KEEP_DAILY=7      # sauvegardes quotidiennes gardées
KEEP_WEEKLY=4     # sauvegardes du dimanche gardées
CHUNK_MB="${SAKURA_BACKUP_CHUNK_MB:-90}"   # GitHub refuse un fichier de plus de 100 Mo

ts() { date -u +%FT%TZ; }
fail() { echo "$(ts) ÉCHEC : $*" >&2; exit 1; }

[ -f "$LOCAL_DB" ] || fail "$LOCAL_DB introuvable (backup_db.sh a-t-il tourné ?)"

# 1. Une sauvegarde illisible ne vaut rien : on la vérifie AVANT de l'envoyer.
CHECK=$(sqlite3 "$LOCAL_DB" "PRAGMA quick_check;" 2>&1 | head -1)
[ "$CHECK" = "ok" ] || fail "la sauvegarde locale est abîmée (quick_check : $CHECK)"

# 2. Le dépôt local des sauvegardes (cloné, ou créé s'il n'existe pas encore).
if [ ! -d "$REPO_DIR/.git" ]; then
    rm -rf "$REPO_DIR"
    if ! git clone -q "$REMOTE" "$REPO_DIR" 2>/dev/null; then
        mkdir -p "$REPO_DIR" && cd "$REPO_DIR" || fail "impossible de créer $REPO_DIR"
        git init -q && git remote add origin "$REMOTE"
    fi
fi
cd "$REPO_DIR" || fail "impossible d'entrer dans $REPO_DIR"
git config user.email "backup@sakura.local"
git config user.name "sakura-backup"

# 3. Sur la branche des sauvegardes (reprise du dépôt distant si elle existe déjà).
if ! git rev-parse --verify -q "$BRANCH" >/dev/null; then
    if git fetch -q origin "$BRANCH" 2>/dev/null; then
        git checkout -q -B "$BRANCH" FETCH_HEAD
    else
        git checkout -q --orphan "$BRANCH"
        git rm -rq --cached . 2>/dev/null || true
        # Les anciennes copies non compressées de la branche `main` ne suivent
        # pas : elles restent dans l'historique de `main`, sur GitHub.
        find . -maxdepth 1 -name 'lita_v2_*.db' -delete
    fi
else
    git checkout -q "$BRANCH" 2>/dev/null || true
fi

# 4. La sauvegarde du jour, compressée, découpée si elle dépasse la limite.
STAMP=$(date -u +%Y%m%d_%H%M%S)
store() {    # store <dossier>
    mkdir -p "$1"
    gzip -6 -c "$LOCAL_DB" > "$1/lita_v2.db.gz" || fail "compression impossible"
    if [ "$(stat -c %s "$1/lita_v2.db.gz")" -gt $((CHUNK_MB * 1024 * 1024)) ]; then
        split -b "${CHUNK_MB}m" -d "$1/lita_v2.db.gz" "$1/lita_v2.db.gz.part-" && rm -f "$1/lita_v2.db.gz"
    fi
}
store "jours/$STAMP"
if [ "$(date -u +%u)" = "7" ]; then
    mkdir -p "dimanches/$STAMP" && cp -f "jours/$STAMP"/* "dimanches/$STAMP/"
fi

# 5. Rotation : les plus récentes seulement.
rotate() {   # rotate <dossier> <nombre à garder>
    [ -d "$1" ] || return 0
    ls -1d "$1"/*/ 2>/dev/null | sort | head -n "-$2" | xargs -r rm -rf
}
rotate jours "$KEEP_DAILY"
rotate dimanches "$KEEP_WEEKLY"

cat > LISEZMOI.md <<EOF
# Sauvegardes de la base SakuraLeveling

Dernière sauvegarde : $STAMP (UTC). $KEEP_DAILY jours dans \`jours/\`, $KEEP_WEEKLY dimanches dans \`dimanches/\`.

Restaurer :

    cd jours/<la plus récente>
    cat lita_v2.db.gz* | gunzip > lita_v2.db
    sqlite3 lita_v2.db "PRAGMA integrity_check;"     # doit répondre « ok »

Cette branche est réécrite chaque nuit (un seul commit). Les sauvegardes d'avant
le 13/11/2026 sont dans l'historique de la branche \`main\`.
EOF

# 6. UN seul commit, poussé à la place du précédent : la taille reste bornée.
git checkout -q --orphan nuit 2>/dev/null || fail "branche temporaire impossible"
git add -A
git commit -q -m "sauvegardes au $STAMP" || fail "commit impossible"
git branch -q -M "$BRANCH"
if git push -q --force origin "$BRANCH" 2>/dev/null; then
    git reflog expire --expire=now --all 2>/dev/null
    git gc -q --prune=now 2>/dev/null
    date -u +%FT%TZ > "$MARKER"
    SIZE=$(du -sh "jours/$STAMP" | cut -f1)
    echo "$(ts) OK : sauvegarde poussée hors-VPS ($STAMP, $SIZE compressée)"
else
    fail "push hors-VPS refusé (dépôt privé et clé de déploiement en écriture ?). Le commit local est gardé, il repartira à la prochaine nuit."
fi
