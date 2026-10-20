"""Contrôles statiques sur tout le code (rapides, sans base ni Discord).

1. Un nom importé LOCALEMENT dans une fonction devient local à TOUTE la
   fonction : l'utiliser avant cet import plante (UnboundLocalError). C'est ce
   qui avait cassé /profil pour tout le monde. Pyflakes ne le voit pas.
2. Un message joueur qui cite une commande qui n'existe pas (renommage oublié :
   /profile, /equipement_list, /delete_set…).
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _local_imports(fn) -> dict[str, int]:
    found: dict[str, int] = {}

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPES):
                continue
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    found.setdefault((alias.asname or alias.name).split(".")[0], child.lineno)
            visit(child)

    visit(fn)
    return found


def _loads(node):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _SCOPES):
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            yield child
        yield from _loads(child)


def _py_files():
    for folder in ("app", "webapp", "scripts"):
        yield from (ROOT / folder).rglob("*.py")


def test_pas_d_usage_avant_import_local():
    problems = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            imports = _local_imports(fn)
            for name in _loads(fn):
                line = imports.get(name.id)
                if line and name.lineno < line:
                    problems.append(
                        f"{path.relative_to(ROOT)}:{name.lineno} `{name.id}` "
                        f"utilisé avant son import local (ligne {line})"
                    )
    assert not problems, "\n".join(sorted(set(problems)))


def _command_names() -> set[str]:
    names = set()
    for path in (ROOT / "app" / "bot").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        names |= set(re.findall(r"""(?:command|Group)\(\s*name\s*=\s*["']([\w-]+)["']""", text))
    return names


def _is_docstring(node, parents) -> bool:
    parent = parents.get(node)
    return (
        isinstance(parent, ast.Expr)
        and isinstance(parents.get(parent), (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )


def test_messages_ne_citent_que_des_commandes_existantes():
    names = _command_names()
    assert {"profil", "arbre", "marchand"} <= names  # garde-fou de détection
    pattern = re.compile(r"(?<![\w/:.<])/([a-z_]{3,})\b")
    not_commands = {"usr", "min", "skill", "api", "admin", "static", "assets", "home", "tmp"}
    problems = []
    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if _is_docstring(node, parents):
                continue
            for match in pattern.finditer(node.value):
                name = match.group(1)
                if name not in names and name not in not_commands:
                    problems.append(f"{path.relative_to(ROOT)}:{node.lineno} /{name}")
    assert not problems, "\n".join(sorted(set(problems)))
