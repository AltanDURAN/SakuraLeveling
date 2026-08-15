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

# Style commun à TOUTES les icônes → un set visuellement cohérent.
_STYLE = ("centered fantasy RPG inventory item icon, single inanimate object, "
          "dark slate gradient background, dramatic rim lighting, painterly "
          "digital art, vibrant, crisp high detail, no person, no character, "
          "no human, no hands, no text, no watermark, no border")

# Prompts ÉCRITS À LA MAIN par item (clé = code). Le sujet est décrit finement ;
# le style commun est ajouté automatiquement. Pour un nouvel item non listé, on
# retombe sur une description générique (build_item_prompt), qu'on peut ensuite
# affiner ici. Ajouter un item = une ligne.
ITEM_IMAGE_PROMPTS: dict[str, str] = {
    # Consommable
    "potion_soin": "a small round glass flask filled with glowing crimson-red healing potion, cork stopper, warm red inner glow, tiny bubbles",
    # Ressources
    "bois": "a small bundle of chopped wooden logs tied with rope, brown bark and rings, rustic",
    "silex": "a chunk of grey knapped flint stone with sharp fractured edges, faint spark, raw mineral",
    "morceau_de_tissu": "a neatly folded piece of coarse beige linen cloth, woven textile with frayed edges",
    "gel_e": "a glossy translucent blob of bright lime-green slime jelly, gooey and dripping, jiggly gelatinous",
    "dent_de_gobelin": "a single sharp yellowed goblin fang tooth, jagged, dirty, chipped, a small hunting trophy",
    "fragment_d_me": "a floating translucent pale-blue soul shard, ghostly ethereal wisps, faint spectral glow",
    "c_ur_corrompu": "a corrupted demonic heart, pulsing black-and-crimson flesh laced with sickly purple veins, dripping shadowy ooze, ominous",
    "petite_bombe": "a small round black iron bomb with a short lit sparking fuse, cartoonish, danger",
    "diamant": "a large brilliant-cut clear diamond gemstone, sharp sparkling facets, prismatic blue-white light refraction",
    "essence_de_vie": "a swirling glowing orb of luminous emerald-green life essence, vital energy wisps, ethereal soft radiance",
    # Arme
    "dagues_jumelles": "a pair of crossed twin goblin daggers, wickedly curved sharp steel blades, crude bone handles wrapped in worn leather, faint blue rare glint",
    # Équipement
    "cape_silencieuse": "a neatly folded dark hooded cloak laid flat as a folded fabric bundle on the ground, charcoal shadow-woven cloth, subtle violet magical shimmer, product flat-lay of an apparel item",
}


class ImageGenError(RuntimeError):
    pass


def build_item_prompt(code: str, name: str, category: str, rarity: str) -> str:
    """Description pour générer l'image d'un item : prompt CURATÉ si l'item est
    connu (clé = code), sinon description générique dérivée du nom/type/rareté.
    Le style commun est toujours ajouté."""
    subject = ITEM_IMAGE_PROMPTS.get(code)
    if not subject:
        cat = _CATEGORY_HINT.get(category, "a fantasy object")
        rar = _RARITY_HINT.get(rarity, "")
        subject = ", ".join(p for p in (name.strip(), cat, rar) if p)
    return f"{subject}, {_STYLE}"


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
