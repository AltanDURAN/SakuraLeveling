"""Tutoriel : chaque étape s'affiche (RP, actions, vérification) et le
premier écran propose de suivre le tutoriel ou de le passer."""

import json
from pathlib import Path

from app.bot.cogs import tutorial_cog
from app.domain.services import tutorial_service as tsvc


def test_chaque_etape_s_affiche_sans_trou():
    zone = tutorial_cog._first_zone()
    for i, step in enumerate(tsvc.STEPS):
        embed = tutorial_cog.step_embed(i)
        text = embed.description + "".join(f.value for f in embed.fields)
        assert "{zone}" not in text and len(embed.description) < 4096
        assert f"Étape {i + 1} / {len(tsvc.STEPS)}" in embed.footer.text
        if step.check:
            assert any(f.name == "✅ Vérification" for f in embed.fields)
    assert zone in tutorial_cog.step_embed(3).description            # le combat pointe la 1re zone


def test_premier_choix_suivre_ou_passer():
    view = tutorial_cog.TutorialView(player_id=1)
    labels = [c.label for c in view.children]
    assert labels == ["Suivre le tutoriel", "Passer et commencer l'aventure"]
    last = tutorial_cog.TutorialView(player_id=1, step=len(tsvc.STEPS) - 1)
    assert "Commencer l'aventure" in [c.label for c in last.children]
    verify = tutorial_cog.TutorialView(player_id=1, step=1)            # /daily : vérifiée
    assert [c.label for c in verify.children] == ["Précédent", "C'est fait", "Passer l'étape"]


def test_la_potion_de_recompense_rend_tous_les_pv():
    items = json.loads((Path(__file__).parents[2] / "app/infrastructure/content/items.json").read_text())
    potion = next(i for i in items if i["code"] == tsvc.REWARD_ITEM)
    assert potion["category"] == "consumable"
    assert potion["stat_bonuses"] == {"effect": "heal_percent", "value": 100}
    assert "3 potions" in tutorial_cog.adventure_embed(3, skipped=False).description or \
        "3 × Potion" in tutorial_cog.adventure_embed(3, skipped=False).description
