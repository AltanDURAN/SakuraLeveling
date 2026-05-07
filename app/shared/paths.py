from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

ASSETS_DIR = BASE_DIR / "assets"
MOBS_ASSETS_DIR = ASSETS_DIR / "mobs"
ITEMS_ASSETS_DIR = ASSETS_DIR / "items"
LANDSCAPES_ASSETS_DIR = ASSETS_DIR / "landscapes"
GENERATED_ENCOUNTERS_DIR = ASSETS_DIR / "generated_encounters"
GENERATED_PROFILES_DIR = ASSETS_DIR / "generated_profiles"
GENERATED_EQUIPMENT_DIR = ASSETS_DIR / "generated_equipment"
GENERATED_LISTS_DIR = ASSETS_DIR / "generated_lists"