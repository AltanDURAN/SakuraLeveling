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
    assert zone in tutorial_cog.step_embed(4).description            # le combat pointe la 1re zone


def test_premier_choix_suivre_ou_passer():
    view = tutorial_cog.TutorialView(player_id=1)
    labels = [c.label for c in view.children]
    assert labels == ["Suivre le tutoriel", "Passer et commencer l'aventure"]
    last = tutorial_cog.TutorialView(player_id=1, step=len(tsvc.STEPS) - 1)
    assert "Commencer l'aventure" in [c.label for c in last.children]
    verify = tutorial_cog.TutorialView(player_id=1, step=1)            # /daily : vérifiée
    assert [c.label for c in verify.children] == ["Réclamer ma solde", "Précédent", "C'est fait",
                                                  "Passer l'étape"]


# --- Salon du tutoriel en lecture seule (25/11/2026) -------------------------

def _command_names() -> set[str]:
    import re
    root = Path(__file__).parents[2] / "app/bot/cogs"
    return {m for f in root.glob("*.py")
            for m in re.findall(r'command\(\s*name="([a-z_]+)"', f.read_text())}


def test_chaque_etape_se_joue_sans_ecrire_dans_le_salon_du_tutoriel():
    names = _command_names()
    for step in tsvc.STEPS:
        if step.button:
            assert step.button[0] in names, step.code                 # une vraie commande
        assert step.go in ("", "tour", "zone")
        # Une étape vérifiée se fait d'un bouton ou dans un autre salon, jamais en tapant ici.
        if step.check:
            assert step.button or step.go, step.code
    assert {s.code: s.go for s in tsvc.STEPS if s.go} == {"tour": "tour", "combat": "zone"}


def test_les_boutons_menent_au_bon_salon(monkeypatch):
    monkeypatch.setattr(tutorial_cog.access, "first_zone",
                        lambda: {"channel_id": 77, "name": "Clairière sinistre"})
    monkeypatch.setattr(tutorial_cog.settings, "tower_channel_id", 66)
    codes = [s.code for s in tsvc.STEPS]
    tower = tutorial_cog.TutorialView(player_id=1, step=codes.index("tour"), guild_id=5)
    links = [c for c in tower.children if getattr(c, "url", None)]
    assert [(c.label, c.url) for c in links] == [("Aller à la Tour", "https://discord.com/channels/5/66")]
    fight = tutorial_cog.TutorialView(player_id=1, step=codes.index("combat"), guild_id=5)
    assert [c.url for c in fight.children if getattr(c, "url", None)] == ["https://discord.com/channels/5/77"]
    assert tsvc.LATER in "".join(f.value for f in tutorial_cog.step_embed(codes.index("daily")).fields)


def test_une_commande_lancee_d_un_bouton_repond_en_prive():
    import asyncio
    from types import SimpleNamespace

    import discord

    from app.bot import private_interaction as pi

    calls = []

    class Response:
        async def defer(self, **kw):
            calls.append(("defer", kw))

        async def send_message(self, *a, **kw):
            calls.append(("send_message", kw))

        def is_done(self):
            return False

    class Followup:
        async def send(self, *a, **kw):
            calls.append(("followup", kw))

    from discord.ext import commands

    class Economy(commands.Cog):
        @discord.app_commands.command(name="daily", description="d")
        async def daily(self, interaction: discord.Interaction) -> None:
            await interaction.response.defer()                 # public dans /daily
            await interaction.followup.send(embed=None)
            assert interaction.user.id == 9 and not interaction.response.is_done()

    command = Economy().daily
    assert command.binding is not None
    interaction = SimpleNamespace(user=SimpleNamespace(id=9), response=Response(), followup=Followup(),
                                  client=SimpleNamespace(tree=SimpleNamespace(
                                      get_command=lambda name: command if name == "daily" else None)))
    assert asyncio.run(pi.run_command(interaction, "daily"))
    assert calls == [("defer", {"ephemeral": True, "thinking": True}), ("followup", {"embed": None, "ephemeral": True})]
    assert not asyncio.run(pi.run_command(interaction, "inconnue"))


def test_la_potion_de_recompense_rend_tous_les_pv():
    items = json.loads((Path(__file__).parents[2] / "app/infrastructure/content/items.json").read_text())
    potion = next(i for i in items if i["code"] == tsvc.REWARD_ITEM)
    assert potion["category"] == "consumable"
    assert potion["stat_bonuses"] == {"effect": "heal_percent", "value": 100}
    assert "3 potions" in tutorial_cog.adventure_embed(3, skipped=False).description or \
        "3 × Potion" in tutorial_cog.adventure_embed(3, skipped=False).description
