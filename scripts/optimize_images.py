"""Réduit et détoure les images déjà rangées dans `assets/` (une fois pour
toutes : les nouveaux dépôts passent par `app.shared.image_tools` au dépôt).

    .venv/bin/python -m scripts.optimize_images          # aperçu
    .venv/bin/python -m scripts.optimize_images --write

Sans danger à relancer : une image déjà prête ne change pas.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from app.shared.image_tools import MOB_MAX_SIDE, has_white_background, prepare_item_image, shrink
from app.shared.paths import ITEMS_ASSETS_DIR, MOBS_ASSETS_DIR


def _plan() -> list[tuple[Path, str]]:
    work = []
    for path in sorted(ITEMS_ASSETS_DIR.glob("*.png")):
        with Image.open(path) as image:
            if has_white_background(image) or max(image.size) > 512:
                work.append((path, "item"))
    for path in sorted(MOBS_ASSETS_DIR.glob("*.png")):
        with Image.open(path) as image:
            if max(image.size) > MOB_MAX_SIDE:
                work.append((path, "mob"))
    return work


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="écrit les images (sinon : aperçu)")
    args = parser.parse_args()
    before = after = 0
    work = _plan()
    for path, kind in work:
        before += path.stat().st_size
        if not args.write:
            continue
        with Image.open(path) as image:
            ready = prepare_item_image(image) if kind == "item" else shrink(image.convert("RGBA"), MOB_MAX_SIDE)
        ready.save(path, "PNG", optimize=True)
        after += path.stat().st_size
    print(f"{len(work)} image(s) à préparer, {before / 1e6:.0f} Mo"
          + (f" → {after / 1e6:.0f} Mo" if args.write else " (aperçu : --write pour écrire)"))


if __name__ == "__main__":
    main()
