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

import base64
import io
import urllib.parse
import urllib.request

import requests
from PIL import Image

from app.infrastructure.config.settings import settings

_ENDPOINT = "https://image.pollinations.ai/prompt/"

# Negative prompt (fournisseurs qui le gèrent, ex : Cloudflare SDXL) → écarte
# personnages/visages/texte, la faiblesse n°1 des rendus d'items.
_NEGATIVE = ("person, people, human, character, face, portrait, hands, fingers, "
             "body, mannequin, figure, text, letters, words, watermark, logo, "
             "signature, frame, border, ui, blurry, lowres, low quality, "
             "deformed, cropped, multiple different objects")

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
# Style commun à TOUTES les icônes → cadrage/fond/lumière identiques = set cohérent.
_STYLE = ("single inanimate object, floating centered, smooth dark charcoal grey "
          "radial gradient background, soft rim lighting from top-left, subtle drop "
          "shadow beneath, clean fantasy RPG inventory item icon, semi-realistic "
          "painterly render, sharp focus, symmetrical, no person, no face, no "
          "character, no creature, no hands, no pedestal, no base, no ring, no "
          "scene, no text, no watermark, no border")

# Aura par rareté → lecture couleur cohérente sans écraser la matière de l'objet.
_RARITY_AURA = {
    "common": "plain mundane object, no magical glow",
    "uncommon": "a faint soft green magical aura around it",
    "rare": "a soft glowing blue magical aura around it",
    "epic": "a vivid purple magical aura and faint glowing runes around it",
    "legendary": "a radiant golden divine aura, intense warm glow around it",
}

# Prompts ÉCRITS À LA MAIN par item (clé = code). Sujet décrit sans ambiguïté et
# SANS mot qui attire un personnage/visage (le modèle gratuit ignore les
# négations) : on privilégie « single », « isolated », « object », « flat »…
# Style + aura de rareté ajoutés automatiquement. Item non listé → fallback.
ITEM_IMAGE_PROMPTS: dict[str, str] = {
    # Consommable
    "potion_soin": "a single small round glass potion vial sealed with a cork, filled with glowing bright red healing liquid, tiny bubbles inside the glass",
    # Ressources — matériaux bruts d'un univers dark fantasy
    "bois": "three short round firewood logs bound together with a rope, cylindrical brown wood with sawn ends showing tree growth rings, plain timber bundle",
    "silex": "a single sharp shard of dark grey-black flint stone, glassy knapped fractured edges, one primitive fire-starter rock",
    "morceau_de_tissu": "a single folded square of coarse beige linen cloth, plain woven fabric swatch with frayed edges",
    "gel_e": "a single glossy droplet of translucent bright green slime jelly, gooey wobbly gelatinous blob",
    "dent_de_gobelin": "one single small curved ivory-yellow fang, an isolated pointed tooth, chipped and dirty, tiny lone tooth object close-up",
    "fragment_d_me": "a single small floating translucent pale-blue crystalline shard, a glowing sliver of spirit crystal, faint spectral wisps",
    "c_ur_corrompu": "a single fleshy anatomical heart organ corrupted by dark magic, black and crimson veined flesh dripping purple ooze, an isolated grisly organ",
    "petite_bombe": "a single round black cast-iron cannonball bomb with a short lit rope fuse and a bright orange spark, classic cartoon game bomb",
    "diamant": "a single large brilliant-cut clear diamond gemstone, sharp geometric facets, sparkling white crystal",
    "essence_de_vie": "a single floating radiant orb sphere of swirling green life energy, glowing wisps of vital nature magic, an orb of light",
    # Arme
    "dagues_jumelles": "two identical curved steel daggers crossed in an X shape, a matched pair of blades with leather-wrapped hilts, weapon icon of blades and handles only",
    # Équipement
    "cape_silencieuse": "top-down flat lay product photo of a neatly folded black cloak garment on a flat surface, folded charcoal fabric only, empty apparel, nobody, mannequin-free clothing product shot",
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
        subject = ", ".join(p for p in (f"a single {name.strip()}", cat) if p)
    aura = _RARITY_AURA.get(rarity, "")
    return ". ".join(p for p in (subject, aura, _STYLE) if p)


_CF_DEFAULT_MODEL = "@cf/stabilityai/stable-diffusion-xl-base-1.0"


def active_provider() -> str:
    """Fournisseur effectif : 'cloudflare' si demandé ET configuré, sinon
    'pollinations' (repli gratuit sans clé)."""
    if (settings.image_gen_provider.strip().lower() == "cloudflare"
            and settings.cloudflare_account_id.strip()
            and settings.cloudflare_api_token.strip()):
        return "cloudflare"
    return "pollinations"


def _generate_pollinations(prompt: str, size: int, seed: int | None,
                           model: str, timeout: int) -> bytes:
    q = {"width": size, "height": size, "nologo": "true", "model": model}
    if seed is not None:
        q["seed"] = seed
    url = _ENDPOINT + urllib.parse.quote(prompt, safe="") + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "sakura-admin"})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError(f"Service de génération indisponible ({type(exc).__name__}).") from exc
    if not raw:
        raise ImageGenError("Réponse vide du service de génération.")
    return raw


def _generate_cloudflare(prompt: str, size: int, timeout: int) -> bytes:
    acc = settings.cloudflare_account_id.strip()
    tok = settings.cloudflare_api_token.strip()
    model = settings.image_gen_model.strip() or _CF_DEFAULT_MODEL
    url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model}"
    body: dict = {"prompt": prompt, "width": size, "height": size}
    # SDXL/Stable Diffusion acceptent le negative prompt (Flux non).
    if "flux" not in model:
        body["negative_prompt"] = _NEGATIVE
        body["num_steps"] = 20
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {tok}"},
                          json=body, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError(f"Cloudflare injoignable ({type(exc).__name__}).") from exc
    if r.status_code != 200:
        raise ImageGenError(f"Cloudflare a répondu {r.status_code} : {r.text[:180]}")
    if "application/json" in r.headers.get("content-type", ""):
        b64 = ((r.json() or {}).get("result") or {}).get("image")
        if not b64:
            raise ImageGenError(f"Réponse Cloudflare inattendue : {r.text[:180]}")
        return base64.b64decode(b64)
    return r.content


def generate_image(prompt: str, size: int = 1024, seed: int | None = None,
                   model: str = "flux", timeout: int = 90) -> bytes:
    """Génère une image depuis le prompt et renvoie des octets PNG (RGBA).

    Fournisseur selon la config (Cloudflare si configuré, sinon Pollinations).
    Lève ImageGenError en cas d'indisponibilité / réponse illisible.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageGenError("Description vide.")
    if active_provider() == "cloudflare":
        raw = _generate_cloudflare(prompt, size, timeout)
    else:
        raw = _generate_pollinations(prompt, min(size, 1024), seed, model, timeout)
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError("Image générée illisible.") from exc
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
