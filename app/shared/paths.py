from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

ASSETS_DIR = BASE_DIR / "assets"
MOBS_ASSETS_DIR = ASSETS_DIR / "mobs"
ITEMS_ASSETS_DIR = ASSETS_DIR / "items"
LANDSCAPES_ASSETS_DIR = ASSETS_DIR / "landscapes"
EVENTS_ASSETS_DIR = ASSETS_DIR / "events"
NPCS_ASSETS_DIR = ASSETS_DIR / "npcs"
# La pièce d'or (512 px, fond transparent) : dessinée à la place de 💰 / 🪙
# dans les images du bot (`emoji_text.IMAGE_EMOJIS`).
GOLD_COIN_IMAGE = ASSETS_DIR / "others" / "piece_or.png"
GENERATED_ENCOUNTERS_DIR = ASSETS_DIR / "generated_encounters"
GENERATED_PROFILES_DIR = ASSETS_DIR / "generated_profiles"
GENERATED_EQUIPMENT_DIR = ASSETS_DIR / "generated_equipment"
GENERATED_LISTS_DIR = ASSETS_DIR / "generated_lists"
GENERATED_NPCS_DIR = ASSETS_DIR / "generated_npcs"
