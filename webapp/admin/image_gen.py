"""Génération d'images d'items via un service GRATUIT sans clé (Pollinations.ai).

Appelé côté serveur depuis l'admin : on construit une description (« prompt »)
à partir du nom / type / rareté de l'item, on demande une image au service, puis
l'appelant la sauve en assets/items/<code>.png.

Gratuit, sans compte ni clé. Débit modéré (quelques images à la demande) — c'est
suffisant pour l'usage admin. En cas d'indisponibilité du service, on lève
`ImageGenError` (l'admin réessaiera ou uploadera manuellement).

Pour changer de fournisseur (ex : Cloudflare Workers AI, meilleure qualité mais
nécessite un token), il suffit de réimplémenter `generate_image`.
"""

from __future__ import annotations

import io
import urllib.parse
import urllib.request

from PIL import Image

_ENDPOINT = "https://image.pollinations.ai/prompt/"

# Indices visuels par type d'item (aident le modèle à cadrer l'objet).
_CATEGORY_HINT = {
    "resource": "a crafting material / raw resource",
    "weapon": "a weapon",
    "shield": "a shield",
    "helmet": "a helmet",
    "chest": "a chest armor breastplate",
    "legs": "leg armor greaves",
    "boots": "a pair of boots",
    "necklace": "a necklace amulet pendant",
    "bracelet": "a bracelet",
    "ring": "a ring",
    "belt": "a belt",
    "cape": "a cape cloak",
    "earring": "an earring",
    "consumable": "a consumable potion",
    "potion": "a potion in a glass flask",
}
# Indices visuels par rareté (couleur / aura).
_RARITY_HINT = {
    "common": "simple, plain, worn",
    "uncommon": "fine quality, faint green glow",
    "rare": "ornate, glowing blue aura",
    "epic": "elaborate, magical purple glow",
    "legendary": "legendary, radiant golden glow, epic masterwork",
}

_STYLE = ("fantasy RPG game item icon, single object centered, plain soft neutral "
          "background, soft studio lighting, digital painting, highly detailed, "
          "crisp, no text, no watermark, no border")


class ImageGenError(RuntimeError):
    pass


def build_item_prompt(name: str, category: str, rarity: str) -> str:
    """Description auto (éditable côté admin) pour générer l'image de l'item."""
    cat = _CATEGORY_HINT.get(category, "a fantasy object")
    rar = _RARITY_HINT.get(rarity, "")
    parts = [p for p in (name.strip(), cat, rar, _STYLE) if p]
    return ", ".join(parts)


def generate_image(prompt: str, size: int = 512, seed: int | None = None,
                   model: str = "flux", timeout: int = 60) -> bytes:
    """Génère une image depuis le prompt et renvoie des octets PNG (RGBA).

    Lève ImageGenError si le service est indisponible / la réponse illisible.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageGenError("Description vide.")
    q = {"width": size, "height": size, "nologo": "true", "model": model}
    if seed is not None:
        q["seed"] = seed
    url = _ENDPOINT + urllib.parse.quote(prompt, safe="") + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "sakura-admin"})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except Exception as exc:  # noqa: BLE001 — réseau/HTTP, message générique
        raise ImageGenError(f"Service de génération indisponible ({type(exc).__name__}).") from exc
    if not raw:
        raise ImageGenError("Réponse vide du service de génération.")
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError("Image générée illisible.") from exc
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
