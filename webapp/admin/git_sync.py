"""Versionnage git des éditions de contenu faites via l'admin (Phase 2).

Quand activé (`settings.content_git_push = true`, donc CONTENT_GIT_PUSH=1 dans
.env + une clé de déploiement avec accès write configurée sur le VPS), commite
et pousse les JSON de contenu édités vers `beta`. Désactivé par défaut : tant
que ce n'est pas le cas, c'est un no-op (les JSON sont quand même écrits en
local par content_sync, donc reseed-safe).

Best-effort : ne lève jamais — un échec git n'impacte pas l'action admin.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.infrastructure.config.settings import settings

_logger = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(_REPO_ROOT), *args],
        capture_output=True, text=True, timeout=45,
    )


def push_content(paths: list[str], message: str) -> bool:
    """Commite les `paths` (relatifs au repo) et pousse sur beta. No-op si
    le push de contenu n'est pas activé."""
    if not getattr(settings, "content_git_push", False):
        return False
    try:
        _git("add", *paths)
        commit = _git("commit", "-m", message)
        out = (commit.stdout + commit.stderr).lower()
        if commit.returncode != 0 and "nothing to commit" not in out:
            _logger.warning("git commit: %s", (commit.stdout + commit.stderr).strip())
        # Se resynchroniser avant de pousser (évite un reject si beta a bougé).
        _git("pull", "--rebase", "origin", "beta")
        push = _git("push", "origin", "HEAD:beta")
        if push.returncode != 0:
            _logger.warning("git push contenu échoué : %s", push.stderr.strip())
            return False
        _logger.info("Contenu poussé sur beta : %s", message)
        return True
    except Exception:
        _logger.warning("git_sync.push_content exception", exc_info=True)
        return False
