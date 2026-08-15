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
# personnages/décor/texte/couleur, pour rester sur un croquis d'objet isolé N&B
# cohérent avec la DA dessinée à la main des monstres.
_NEGATIVE = ("color, colored, vibrant, photo, photograph, 3d render, cgi, glossy, "
             "shiny, smooth gradient, person, people, human, character, face, "
             "portrait, hands, fingers, body, skull, head, creature, monster, "
             "animal, beast, horns, jaw, tree, trees, forest, woods, tree trunks, "
             "bamboo, plant, building, castle, landscape, scenery, ground, floor, "
             "book, page, spine, sketchbook border, dark border, black border, "
             "vignette, box, square outline, character sheet, multiple views, "
             "text, letters, words, watermark, signature, logo, frame, ui, "
             "multiple objects, two objects, blurry, lowres, deformed, cropped")

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
# DA commune = croquis encre/crayon niveaux de gris hachuré, fond blanc, cohérent
# avec les MONSTRES dessinés à la main du jeu (trait N&B + hachures + fond blanc).
# Isolation forte (un seul objet) puis medium en tête du prompt (verrouille le
# style croquis même sur objets lisses) : géré dans build_item_prompt.
_ISOLATE = ("ONE single small isolated object only, centered on a plain empty white "
            "background, RPG inventory item icon, still-life object study, nothing "
            "else in the frame, no scenery")
_STYLE = ("hand-drawn black ink and graphite pencil sketch, monochrome grayscale, "
          "bold confident black ink outlines, dense cross-hatching and pencil "
          "shading, hand-inked linework, dark fantasy RPG item drawing, high "
          "contrast, detailed but sketchy")

# Prompts ÉCRITS À LA MAIN par item (clé = code). Sujets concrets et SINGULIERS,
# SANS mot « monstre / animal / goblin » (SDXL dessinerait la créature entière) :
# l'origine monstre est portée par l'objet lui-même (dent, cœur démoniaque,
# fragment spectral, gelée de slime). Item non listé → fallback générique.
ITEM_IMAGE_PROMPTS: dict[str, str] = {
    "potion_soin": "a single lone glass potion flask, exactly one round bottle sealed with a cork, glowing liquid and tiny bubbles inside, only one bottle and nothing else",
    "bois": "a small stack of a few chopped stove wood billets bound with twine, one lone tied wood bundle, centered on blank white, nothing else",
    "silex": "a single lone shard of knapped flint stone, exactly one angular grey rock flake with sharp chipped edges, only one stone and nothing else",
    "morceau_de_tissu": "a single neatly folded square of coarse frayed cloth lying flat, one lone folded fabric scrap with loose threads on its edges, no clothesline, empty white background",
    "gel_e": "a single glistening blob of gelatinous slime jelly, a wobbly rounded translucent goo droplet dripping at the bottom",
    "dent_de_gobelin": "one single triangular ivory tooth, a flat pointed tooth with a serrated cutting edge and a worn cream-white root",
    "fragment_d_me": "a single jagged translucent crystal shard with a faint anguished ghostly face dimly trapped inside and thin curling wisps of spirit smoke rising off it",
    "c_ur_corrompu": "a corrupted heart, a single anatomical heart organ with dark bulging veins and tiny thorny spikes, dripping ooze",
    "petite_bombe": "a single round black cast-iron bomb sphere with a short curled rope fuse and a small lit spark at the tip",
    "diamant": "a single brilliant-cut faceted diamond gemstone, sharp geometric facets, a sparkling precious crystal",
    "essence_de_vie": "a single round glass sphere orb holding swirling wisps of glowing living energy and tiny floating leaves inside",
    "dagues_jumelles": "a pair of two identical curved matched daggers crossed into a single X shape, twin blades with cord-wrapped hilts",
    "cape_silencieuse": "a single empty hooded cloak garment laid out flat seen from above, one folded cape with a visible deep hood, empty apparel, no person, empty white background",
}


class ImageGenError(RuntimeError):
    pass


def build_item_prompt(code: str, name: str, category: str, rarity: str) -> str:
    """Description pour générer l'image d'un item : sujet CURATÉ si l'item est
    connu (clé = code), sinon sujet générique dérivé du nom/type. Le medium
    (croquis encre) est placé EN TÊTE pour verrouiller la DA même sur objets
    lisses, suivi de l'isolation forte et du style commun."""
    subject = ITEM_IMAGE_PROMPTS.get(code)
    if not subject:
        cat = _CATEGORY_HINT.get(category, "a fantasy object")
        subject = ", ".join(p for p in (f"a single {name.strip()}", cat) if p)
    return f"a rough black ink and pencil sketch drawing of {subject}, {_ISOLATE}, {_STYLE}"


_CF_DEFAULT_MODEL = "@cf/stabilityai/stable-diffusion-xl-base-1.0"


_GOOGLE_DEFAULT_MODEL = "imagen-3.0-generate-002"


def active_provider() -> str:
    """Fournisseur effectif selon la config (repli 'pollinations' gratuit si le
    fournisseur demandé n'est pas configuré)."""
    prov = settings.image_gen_provider.strip().lower()
    if (prov == "cloudflare" and settings.cloudflare_account_id.strip()
            and settings.cloudflare_api_token.strip()):
        return "cloudflare"
    if prov == "google" and settings.google_api_key.strip():
        return "google"
    return "pollinations"


def _generate_google(prompt: str, timeout: int) -> bytes:
    """Google (Gemini API). Gère Imagen (`imagen-*` via :predict) ET les modèles
    image Gemini (`gemini-*` via :generateContent)."""
    key = settings.google_api_key.strip()
    model = settings.image_gen_model.strip() or _GOOGLE_DEFAULT_MODEL
    base = "https://generativelanguage.googleapis.com/v1beta/models/"
    try:
        if model.startswith("imagen"):
            url = f"{base}{model}:predict?key={key}"
            body = {"instances": [{"prompt": prompt}],
                    "parameters": {"sampleCount": 1, "aspectRatio": "1:1"}}
            r = requests.post(url, json=body, timeout=timeout)
            if r.status_code != 200:
                raise ImageGenError(f"Google a répondu {r.status_code} : {r.text[:200]}")
            preds = (r.json() or {}).get("predictions") or []
            b64 = preds[0].get("bytesBase64Encoded") if preds else None
        else:
            url = f"{base}{model}:generateContent?key={key}"
            body = {"contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseModalities": ["IMAGE"]}}
            r = requests.post(url, json=body, timeout=timeout)
            if r.status_code != 200:
                raise ImageGenError(f"Google a répondu {r.status_code} : {r.text[:200]}")
            b64 = None
            for cand in (r.json() or {}).get("candidates") or []:
                for part in (cand.get("content") or {}).get("parts") or []:
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and inline.get("data"):
                        b64 = inline["data"]
                        break
                if b64:
                    break
    except ImageGenError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError(f"Google injoignable ({type(exc).__name__}).") from exc
    if not b64:
        raise ImageGenError("Aucune image dans la réponse Google.")
    return base64.b64decode(b64)


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
    prov = active_provider()
    if prov == "cloudflare":
        raw = _generate_cloudflare(prompt, size, timeout)
    elif prov == "google":
        raw = _generate_google(prompt, timeout)
    else:
        raw = _generate_pollinations(prompt, min(size, 1024), seed, model, timeout)
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError("Image générée illisible.") from exc
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
