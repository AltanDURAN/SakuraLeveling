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
# le kawaï/mascotte, les personnages/décor, le photoréalisme, le multi-objets :
# on vise un objet isolé dessiné main, cel-shading coloré, fond blanc.
_NEGATIVE = ("cute, kawaii, chibi, adorable, mascot, smiling, happy face, eyes, "
             "cartoon character, googly eyes, sticker, "
             "photo, photograph, photorealistic, realistic, hyperdetailed, intricate "
             "details, 3d render, cgi, noisy, grainy, cross-hatching, pencil sketch, "
             "person, people, human, face, portrait, hands, fingers, body, "
             "skull head, creature, live animal, beast, "
             "tree, trees, forest, woods, tree trunks, bamboo, plant, building, "
             "castle, landscape, scenery, ground, floor, book, page, spine, "
             "colored background, gradient background, textured background, "
             "background circle, round backdrop, colored disc behind, halo, "
             "dark border, black border, vignette, box, square outline, "
             "character sheet, multiple views, text, letters, words, watermark, "
             "signature, logo, frame, ui, multiple objects, two objects, blurry, "
             "lowres, deformed, cropped")

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
# DA = dessin à la main de l'auteur : contour noir épais un peu tremblé, couleur
# en APLATS cel-shading (base + 1 ombre + reflets blancs), fond blanc, ton
# dark-fantasy edgy — JAMAIS kawaï, pas de visage. Medium en tête du prompt
# (verrouille le style) : géré dans build_item_prompt.
_ISOLATE = ("ONE single isolated object only, centered on a pure solid flat white "
            "background, plain white backdrop, RPG inventory item icon, no "
            "background scene, no colored background, nothing else in the frame")
_STYLE = ("hand-drawn digital illustration, bold uneven black ink outline, flat "
          "cel-shaded coloring, one darker shadow tone and a few simple white "
          "highlight streaks, limited flat color palette, loose slightly rough "
          "hand-drawn linework, gritty mature dark-fantasy video game item concept "
          "art, clean and simple, moderate detail, painted digitally over an ink "
          "sketch")

# Prompts ÉCRITS À LA MAIN par item (clé = code). Sujets concrets, SINGULIERS et
# COLORÉS, SANS mot « monstre / animal / goblin » (SDXL dessinerait la créature) :
# l'origine monstre est portée par l'objet (dent ensanglantée, cœur démoniaque,
# fragment spectral, gelée de slime). Item non listé → fallback générique.
ITEM_IMAGE_PROMPTS: dict[str, str] = {
    "potion_soin": "one single large potion bottle filling most of the frame, a round glass flask with a cork and glowing red healing liquid inside, close-up of just one bottle, only one",
    "bois": "a small stack of a few chopped firewood logs, warm brown cut wood with visible grain and bark, nothing else, no forest",
    "silex": "a single sharp shard of grey knapped flint stone, one angular chipped fractured rock, only one stone, nothing else",
    "morceau_de_tissu": "a single neatly folded stack of coarse beige linen cloth with frayed edges, one folded fabric scrap, nothing else",
    "gel_e": "a single blob of wobbly bright green slime jelly, a rounded translucent goo droplet dripping at the bottom",
    "dent_de_gobelin": "one single plain tooth, a simple smooth cream-white pointed tooth with a short root and a small red blood stain at its base, one lone isolated tooth, no jaw, no skull, no creature",
    "fragment_d_me": "a single jagged translucent pale-blue crystal shard glowing with a faint ghostly spirit inside and thin wisps of blue soul smoke, one shard",
    "c_ur_corrompu": "a single corrupted heart, one dark crimson and purple anatomical heart with black veins and small thorny spikes, dripping dark ooze, only one",
    "petite_bombe": "one single round black bomb sphere with one short lit twisted rope fuse and a small spark at the tip, only one bomb, dark charcoal body, nothing else",
    "diamant": "a single brilliant-cut faceted gemstone glowing pale blue and white, sharp geometric facets, one sparkling precious crystal",
    "essence_de_vie": "a single round glass orb sphere holding swirling glowing green life energy and a few tiny floating leaves inside, one orb",
    "dagues_jumelles": "a pair of two identical curved steel daggers crossed into an X, blue-grey blades with dark cord-wrapped grips",
    "cape_silencieuse": "a single empty dark blue hooded cloak laid out and spread open, no person inside, one empty cloak garment, just one, nothing else",
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
    return f"a hand-drawn inked and flat-colored illustration of {subject}, {_ISOLATE}, {_STYLE}"


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
    img = _whiten_bg(img)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _whiten_bg(img: "Image.Image", thresh: int = 48) -> "Image.Image":
    """Nettoie le fond en BLANC pur par flood-fill depuis les coins + milieux de
    bords. Fiable car la DA a des contours noirs FERMÉS qui stoppent le
    remplissage au bord de l'objet. Best-effort : n'échoue jamais."""
    from PIL import ImageDraw
    try:
        rgb = Image.new("RGB", img.size, (255, 255, 255))
        rgb.paste(img.convert("RGB"), (0, 0))
        w, h = rgb.size
        for xy in [(1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2),
                   (w // 2, 1), (w // 2, h - 2), (1, h // 2), (w - 2, h // 2)]:
            ImageDraw.floodfill(rgb, xy, (255, 255, 255), thresh=thresh)
        return rgb.convert("RGBA")
    except Exception:  # noqa: BLE001
        return img
