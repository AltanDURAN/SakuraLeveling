"""Aucun composant ni vue ne doit écraser un attribut INTERNE de discord.py.

Depuis discord.py 2.6, chaque Item a un `_parent` (conteneur) que le dispatch
interroge avant chaque callback. Nos boutons y rangeaient leur vue : tous les
clics échouaient en silence (« l'interaction a échoué »). Ce test compare les
`self.<attr> = …` de nos sous-classes aux attributs que discord.py pose lui-même.
"""

import importlib
import inspect
import re
from pathlib import Path

import discord


def _internal_names() -> set[str]:
    names: set[str] = set()
    samples = [
        discord.ui.Button(), discord.ui.Select(options=[discord.SelectOption(label="x")]),
        discord.ui.TextInput(label="x"), discord.ui.View(), discord.ui.Modal(title="x"),
    ]
    for obj in samples:
        names |= set(vars(obj))
    for cls in (discord.ui.Item, discord.ui.Button, discord.ui.Select, discord.ui.View,
                discord.ui.Modal, discord.ui.TextInput):
        for klass in cls.__mro__:
            names |= set(getattr(klass, "__slots__", ()) or ())
            names |= {n for n, v in vars(klass).items() if isinstance(v, property)}
    # Ce que discord.py nous laisse volontairement écrire.
    return names - {"label", "emoji", "style", "disabled", "url", "row", "placeholder",
                    "options", "min_values", "max_values", "custom_id", "value",
                    "default", "required", "timeout", "title", "id", "sku_id",
                    "channel_types", "default_values"}


_ROOT = Path(__file__).resolve().parents[2]


def _bot_classes():
    # Fichiers plutôt que pkgutil : app/bot n'a pas d'__init__.py (paquets
    # namespace), walk_packages ne descendrait pas dans views/ ni cogs/.
    for path in sorted((_ROOT / "app" / "bot").rglob("*.py")):
        rel = path.relative_to(_ROOT).with_suffix("")
        if rel.name in {"main", "__main__", "__init__"}:
            continue  # point d'entrée : l'importer lance le bot
        module = importlib.import_module(".".join(rel.parts))
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(
                cls, (discord.ui.Item, discord.ui.View, discord.ui.Modal),
            ):
                yield cls


def test_aucun_attribut_interne_ecrase():
    internal = _internal_names()
    assert "_parent" in internal  # garde-fou : la détection fonctionne
    offenders = []
    classes = list(_bot_classes())
    assert len(classes) > 30  # garde-fou : on inspecte bien les vues du bot
    for cls in classes:
        source = inspect.getsource(cls)
        for name in set(re.findall(r"self\.(\w+)\s*=(?!=)", source)):
            if name in internal:
                offenders.append(f"{cls.__module__}.{cls.__name__}.{name}")
    assert not offenders, offenders
