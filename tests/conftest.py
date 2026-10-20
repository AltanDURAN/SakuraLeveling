"""Configuration commune des tests.

Enregistre TOUS les modèles SQLAlchemy dans `Base.metadata` avant le moindre
test : un fixture qui fait `Base.metadata.create_all(engine)` obtient alors
toutes les tables, qu'il soit lancé seul ou dans la suite complète. Sans ça,
un fichier de tests ne passait que si un AUTRE fichier avait importé avant
lui les modèles qui lui manquaient.
"""

import importlib
import pkgutil

import app.infrastructure.db.models as _models

for _mod in pkgutil.iter_modules(_models.__path__):
    importlib.import_module(f"{_models.__name__}.{_mod.name}")
