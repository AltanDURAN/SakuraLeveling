"""Un élément et ses faiblesses, écrits pareil partout (fiche du bestiaire,
world boss) — audit des duplications du 21/11/2026."""

from __future__ import annotations

from app.domain.services import element_service
from app.shared.enums import ELEMENT_EMOJIS, ELEMENT_LABELS


def element_with_weaknesses(element: str) -> str:
    """« 🔥 **Feu**\\nFaible à : 💧 Eau, … » ; « **neutre** » sans élément."""
    if not element:
        return "**neutre**"
    emoji = ELEMENT_EMOJIS.get(element, "")
    label = ELEMENT_LABELS.get(element, element)
    weak = ", ".join(
        f"{ELEMENT_EMOJIS.get(e.value, '')} {ELEMENT_LABELS.get(e.value, e.value)}"
        for e in element_service.weaknesses_of(element)
    ) or "—"
    return f"{emoji} **{label}**\nFaible à : {weak}"
