"""Le règlement s'accepte avant d'avoir accès au bot (07/11/2026, demande de
l'auteur).

Un BOUTON plutôt qu'une réaction : la réponse est privée et immédiate, la
version acceptée est gardée en base, et l'on accepte là où l'on est. Une
commande ou un bouton du jeu utilisé sans avoir accepté répond par le
règlement et son bouton ; une fois accepté, on relance son action.

Branché sur `SakuraTree.interaction_check` (toutes les commandes) et sur
`GatedView` (boutons publics : monstres, raid, événements, tutoriel, échanges,
offrande). Passent toujours : /reglement, les autocomplétions et les groupes
admin (`@admin_only` garde ceux-là).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import discord

from app.application.use_cases import rules as rules_uc
from app.bot.embeds.rules_embeds import build_rules_embed
from app.domain.services.rules_service import Rules, needs_acceptance
from app.infrastructure.config.settings import settings
from app.infrastructure.db.session import get_db_session
from app.infrastructure.rules.rules_loader import get_rules

_logger = logging.getLogger(__name__)

ACCEPT_ID = "rules:accept"
#: Commandes (nom de tête) ouvertes sans avoir accepté le règlement.
OPEN_COMMANDS = frozenset({"reglement", "admin", "boss_admin", "event"})

ASK_FIRST = "📜 Pour jouer, il faut d'abord accepter le règlement (une seule fois). Lis-le, puis clique en bas."
ASK_AGAIN = "📝 Le règlement a changé depuis que tu l'as accepté : relis-le et accepte la nouvelle version."
DONE_IN_PLACE = ("✅ Règlement accepté, merci ! Le jeu t'est ouvert : "
                 "relance ta commande ou reclique sur le bouton.")
SAVE_FAILED = "❌ Ton acceptation n'a pas pu être enregistrée. Réessaie dans un instant."

#: discord_id → version acceptée. Seules les acceptations y entrent : un
#: joueur qui n'a pas encore accepté est relu en base à chaque fois.
_accepted: dict[int, int] = {}


def timestamp(moment: datetime) -> str:
    """Date affichée par Discord dans la langue de chacun."""
    return f"<t:{int(moment.replace(tzinfo=UTC).timestamp())}:D>"


def _read(discord_id: int) -> rules_uc.Acceptance | None:
    with get_db_session() as session:
        return rules_uc.acceptance(session, discord_id)


def _write(discord_id: int, version: int) -> tuple[bool, rules_uc.Acceptance]:
    with get_db_session() as session:
        newly = rules_uc.accept(session, discord_id, version)
        return newly, rules_uc.acceptance(session, discord_id)


async def accepted_version(discord_id: int) -> int | None:
    if discord_id in _accepted:
        return _accepted[discord_id]
    found = await asyncio.to_thread(_read, discord_id)
    if found is not None:
        _accepted[discord_id] = found.version
        return found.version
    return None


async def read_acceptance(discord_id: int) -> rules_uc.Acceptance | None:
    return await asyncio.to_thread(_read, discord_id)


def _command_root(interaction: discord.Interaction) -> str:
    data = getattr(interaction, "data", None) or {}
    return str(data.get("name", ""))


async def allow(interaction: discord.Interaction) -> bool:
    """Vrai si l'action peut continuer ; sinon le règlement est proposé."""
    if interaction.type is discord.InteractionType.autocomplete:
        return True
    if (interaction.type is discord.InteractionType.application_command
            and _command_root(interaction) in OPEN_COMMANDS):
        return True
    rules = get_rules()
    try:
        version = await accepted_version(interaction.user.id)
    except Exception:  # noqa: BLE001 — une base indisponible ne doit pas fermer le jeu
        _logger.exception("règlement : lecture impossible pour %s, accès laissé ouvert", interaction.user.id)
        return True
    if not needs_acceptance(version, rules):
        return True
    await prompt(interaction, rules, again=version is not None)
    return False


async def prompt(interaction: discord.Interaction, rules: Rules | None = None, *, again: bool = False) -> None:
    rules = rules or get_rules()
    kwargs = {"content": ASK_AGAIN if again else ASK_FIRST, "embed": build_rules_embed(rules),
              "view": RulesAcceptView(), "ephemeral": True}
    try:
        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)
    except discord.HTTPException:
        _logger.warning("règlement : impossible de le montrer à %s", interaction.user.id, exc_info=True)


def welcome_text() -> str:
    """Ce qu'on dit à qui vient d'accepter depuis le salon du règlement."""
    text = "✅ Merci, c'est noté : le jeu t'est ouvert !"
    if settings.tutorial_channel_id:
        text += f"\n🌸 Nouveau ? Hana t'attend dans <#{settings.tutorial_channel_id}> pour te guider (ou tape `/tuto`)."
    return text


async def accept(interaction: discord.Interaction) -> None:
    rules = get_rules()
    try:
        newly, found = await asyncio.to_thread(_write, interaction.user.id, rules.version)
    except Exception:  # noqa: BLE001
        _logger.exception("règlement : acceptation de %s non enregistrée", interaction.user.id)
        await interaction.response.send_message(SAVE_FAILED, ephemeral=True)
        return
    _accepted[interaction.user.id] = max(_accepted.get(interaction.user.id, 0), found.version)
    message = interaction.message
    if message is not None and message.flags.ephemeral:
        # Le règlement proposé à la place d'une action : on le remplace.
        await interaction.response.edit_message(content=DONE_IN_PLACE, embed=None, view=None)
        return
    if newly:
        text = welcome_text()
    else:
        text = f"✅ Tu as déjà accepté ce règlement (le {timestamp(found.accepted_at)}). Bonne chasse !"
    await interaction.response.send_message(text, ephemeral=True)


class RulesAcceptView(discord.ui.View):
    """Le bouton d'acceptation : panneau du salon (persistant) et réponses privées."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="J'accepte le règlement", style=discord.ButtonStyle.success, emoji="✅",
                       custom_id=ACCEPT_ID)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await accept(interaction)


class GatedView(discord.ui.View):
    """Vue publique du jeu : qui n'a pas accepté le règlement se le voit proposer."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await allow(interaction)
