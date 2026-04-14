from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

ASSETS_DIR = BASE_DIR / "assets"
MOBS_ASSETS_DIR = ASSETS_DIR / "mobs"
LANDSCAPES_ASSETS_DIR = ASSETS_DIR / "landscapes"
GENERATED_ENCOUNTERS_DIR = ASSETS_DIR / "generated_encounters"