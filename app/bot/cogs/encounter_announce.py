"""Annonces d'un combat de zone dans les salons (pièce mythique, premières
fois) et envois / suppressions sans erreur. Méthodes
d'`EncounterCog` (mixin), sorties d'`encounter_cog.py` le 28/11/2026 (audit) :
texte inchangé."""

import asyncio
import logging
import discord
from app.infrastructure.config.settings import settings
_logger = logging.getLogger("app.bot.cogs.encounter_cog")


class EncounterAnnounceMixin:
    @staticmethod
    async def _announce_mythics(channel, summary, jump_url: str | None) -> None:
        """Un mythique tombe environ 1 fois sur 25 000 morts : c'est un
        événement pour tout le serveur, on l'annonce dans le salon."""
        for reward in getattr(summary, "rewards", None) or []:
            for gear_name, rarity in getattr(reward, "gear", None) or []:
                if rarity != "mythic":
                    continue
                embed = discord.Embed(
                    title="🔴 UNE PIÈCE MYTHIQUE EST TOMBÉE",
                    description=(
                        f"<@{reward.user_id}> vient d'arracher **{gear_name}** "
                        f"(mythique) à {summary.mob_name} !"
                        + (f"\n[Voir le combat]({jump_url})" if jump_url else "")
                    ),
                    color=discord.Color.from_rgb(235, 70, 90),
                )
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    async def _announce_firsts(self, summary, mob_code: str) -> None:
        """Les premières fois d'un joueur (première pièce épique, première élite
        vaincue), dans le salon général, sans mention."""
        from app.application.services import milestones
        from app.domain.services.mob_ability_service import is_group_elite

        rewards = getattr(summary, "rewards", None) or []
        name = {r.player_id: discord.utils.escape_markdown(r.name) for r in rewards}
        epic = [r.player_id for r in rewards
                if any(rarity in milestones.EPIC_OR_BETTER for _, rarity in (getattr(r, "gear", None) or []))]
        elite = ([r.player_id for r in rewards if r.contribution is None or r.contribution.survived]
                 if getattr(summary, "outcome", "") == "victory" and is_group_elite(mob_code) else [])
        lines = []
        for pid in sorted(await asyncio.to_thread(milestones.claim_now, epic, milestones.FIRST_EPIC)):
            lines.append(f"🟣 **{name[pid]}** a trouvé sa **première pièce épique** : son passif s'éveille !")
        for pid in sorted(await asyncio.to_thread(milestones.claim_now, elite, milestones.FIRST_ELITE)):
            lines.append(f"👑 **{name[pid]}** a vaincu sa **première élite** : {summary.mob_name} !")
        channel = self.bot.get_channel(settings.rank_announce_channel_id) if lines else None
        if channel is None:
            return
        try:
            await channel.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            _logger.warning("annonce d'une première fois impossible", exc_info=True)

    @staticmethod
    async def _delete_quietly(message) -> None:
        try:
            await message.delete()
        except discord.NotFound:
            pass                                        # déjà retiré (à la main, par exemple)
        except discord.HTTPException:
            _logger.warning("message du combat non supprimé", exc_info=True)

    @staticmethod
    async def _send_quietly(channel, text: str) -> None:
        try:
            await channel.send(text)
        except discord.HTTPException:
            _logger.warning("message non envoyé", exc_info=True)
