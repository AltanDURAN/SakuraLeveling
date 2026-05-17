"""Helpers d'écriture atomique pour les JSON de `app/infrastructure/content/`.

Tous les fichiers concernés (classes, titles, daily_quests, weekly_quests,
boss_definitions, sets, skill_tree, crafts) sont consultés au démarrage
puis CACHED par leurs loaders respectifs (module-level). Une modification
côté webapp est visible immédiatement par le webapp (qui relit le disque
à chaque requête), mais **le bot Discord ne la verra qu'après un restart**.

L'écriture est atomique via tmp file + rename pour éviter de laisser un
JSON tronqué si le process est tué pendant l'écriture.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONTENT_DIR = Path(__file__).resolve().parents[2] / "app" / "infrastructure" / "content"


def content_path(filename: str) -> Path:
    return CONTENT_DIR / filename


def load_json(filename: str, default: Any = None) -> Any:
    path = content_path(filename)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(filename: str, data: Any) -> None:
    """Écrit le JSON via tmp + rename. Crée un .bak avant écrasement."""
    path = content_path(filename)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        backup.write_bytes(path.read_bytes())
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def append_to_list(filename: str, entry: dict) -> None:
    """Pour les JSON qui sont des listes (classes.json, titles.json, etc)."""
    data = load_json(filename, default=[])
    if not isinstance(data, list):
        raise ValueError(f"{filename} n'est pas une liste JSON")
    data.append(entry)
    atomic_write_json(filename, data)


def upsert_to_dict(filename: str, key: str, entry: Any) -> None:
    """Pour les JSON dict (sets.json par ex)."""
    data = load_json(filename, default={})
    if not isinstance(data, dict):
        raise ValueError(f"{filename} n'est pas un dict JSON")
    data[key] = entry
    atomic_write_json(filename, data)


def add_skill_node(code: str, node: dict) -> None:
    """skill_tree.json a un shape spécifique : {root, skills: {code: node}}."""
    data = load_json("skill_tree.json", default={"root": "aventurier", "skills": {}})
    if "skills" not in data:
        data["skills"] = {}
    if code in data["skills"]:
        raise ValueError(f"Skill `{code}` existe déjà")
    data["skills"][code] = node
    atomic_write_json("skill_tree.json", data)


def update_skill_node(code: str, node: dict) -> None:
    """Remplace un nœud existant. Code et node doivent matcher."""
    data = load_json("skill_tree.json", default={"skills": {}})
    if code not in (data.get("skills") or {}):
        raise ValueError(f"Skill `{code}` introuvable")
    data["skills"][code] = node
    atomic_write_json("skill_tree.json", data)


def find_in_list_by_key(filename: str, value: str, key: str = "code") -> dict | None:
    """Trouve une entrée dans une liste JSON par clé."""
    data = load_json(filename, default=[]) or []
    if not isinstance(data, list):
        return None
    for entry in data:
        if isinstance(entry, dict) and entry.get(key) == value:
            return entry
    return None


def update_in_list_by_key(filename: str, value: str, new_entry: dict, key: str = "code") -> None:
    """Remplace une entrée dans une liste JSON en matchant sur key."""
    data = load_json(filename, default=[]) or []
    if not isinstance(data, list):
        raise ValueError(f"{filename} n'est pas une liste JSON")
    found = False
    for i, entry in enumerate(data):
        if isinstance(entry, dict) and entry.get(key) == value:
            data[i] = new_entry
            found = True
            break
    if not found:
        raise ValueError(f"Entrée `{value}` introuvable dans {filename}")
    atomic_write_json(filename, data)


def delete_in_list_by_key(filename: str, value: str, key: str = "code") -> None:
    data = load_json(filename, default=[]) or []
    if not isinstance(data, list):
        raise ValueError(f"{filename} n'est pas une liste JSON")
    new_data = [e for e in data if not (isinstance(e, dict) and e.get(key) == value)]
    if len(new_data) == len(data):
        raise ValueError(f"Entrée `{value}` introuvable dans {filename}")
    atomic_write_json(filename, new_data)
