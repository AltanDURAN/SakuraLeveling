"""Invalidation des caches module-level des loaders de contenu.

Les loaders (skill_tree, sets, titres, boss, quêtes, compétences, family drops)
mettent le JSON en cache au premier accès. Après une édition de contenu via
l'admin web, on doit vider ces caches pour que le rendu de la webapp (et un
éventuel re-render) reflète immédiatement la modif — sinon il faut redémarrer.

Best-effort : un loader absent/erroné n'interrompt pas la requête admin.
"""

from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


def invalidate_content_caches() -> None:
    """Vide tous les caches de loaders de contenu (best-effort)."""
    # (module, nom_de_fonction) — la plupart exposent clear_cache(), le skill
    # tree expose reset_cache().
    targets = [
        ("app.infrastructure.skill_tree.skill_tree_loader", "reset_cache"),
        ("app.infrastructure.sets.set_loader", "clear_cache"),
        ("app.infrastructure.titles.title_loader", "clear_cache"),
        ("app.infrastructure.world_boss.boss_definition_loader", "clear_cache"),
        ("app.infrastructure.elements.element_skill_loader", "clear_cache"),
        ("app.infrastructure.loot.family_drop_loader", "clear_cache"),
        ("app.infrastructure.daily_quests.quest_loader", "clear_cache"),
        ("app.infrastructure.weekly_quests.quest_loader", "clear_cache"),
    ]
    import importlib

    for module_path, fn_name in targets:
        try:
            module = importlib.import_module(module_path)
            getattr(module, fn_name)()
        except Exception as exc:  # noqa: BLE001 - best-effort
            _logger.warning("invalidate cache %s.%s a échoué : %s", module_path, fn_name, exc)
