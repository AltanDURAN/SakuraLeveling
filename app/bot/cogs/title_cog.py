"""Cog des titres : `/titre [joueur]` et `/titre_actif [titre]`.

- `/titre`       : le livre des titres (débloqués, puis à débloquer avec la
                   progression), en pages — cf. `title_embeds.py` ;
- `/titre_actif` : choisit le titre affiché sur `/profil` (cosmétique). Sans
                   argument, plus aucun titre n'est affiché.

Les effets d'un titre sont actifs DÈS QU'IL EST DÉBLOQUÉ : `/titre_actif` ne
choisit que l'affichage.
"""

import discord
from discord import app_commands
from discord.ext import commands

from app.application.services.exclusive_title_service import ExclusiveTitleService
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_title_repository import (
    PlayerTitleRepository,
)
from app.infrastructure.db.session import get_db_session
from app.infrastructure.titles.title_loader import (
    get_definition,
    list_definitions,
)

from app.bot.cogs._mixins import BetaChannelOnlyMixin
from app.bot.embeds.title_embeds import build_title_pages
from app.bot.views.bestiaire_view import PagedBookView
from app.domain.services.quest_generation_service import FAMILY_LABELS
from app.domain.services.role_trial_service import RESULTS_HOUR


#: Pseudo d'un détenteur dans une ligne : au plus tant de caractères.
HOLDER_NAME_MAX = 24


class TitleProgress:
    """Où en est un joueur pour chaque titre qu'il n'a pas encore. Construit
    UNE fois par commande : ses compteurs sont lus une seule fois (avant, les
    victoires par monstre étaient relues pour chacun des 50 titres de chasseur)."""

    def __init__(self, session, profile) -> None:
        self.session = session
        self.profile = profile
        self.pid = profile.player.id
        self.kill_repo = PlayerKillRepository(session)
        self.excl = ExclusiveTitleService(session)
        self._per_mob: dict[str, int] | None = None
        self._total: int | None = None
        self._album = None
        self._names: dict[int, str] = {}

    @property
    def per_mob(self) -> dict[str, int]:
        if self._per_mob is None:
            self._per_mob = self.kill_repo.get_kills_per_mob(self.pid)
        return self._per_mob

    @property
    def total_kills(self) -> int:
        if self._total is None:
            self._total = self.kill_repo.get_total_kills(self.pid)
        return self._total

    @property
    def album(self):
        if self._album is None:
            from app.application.use_cases import cards

            self._album = cards.collection(self.session, self.pid).album
        return self._album

    def holder_name(self, holder_id: int) -> str:
        if holder_id not in self._names:
            holder = PlayerRepository(self.session).get_profile_by_player_id(holder_id)
            name = holder.player.display_name if holder else f"#{holder_id}"
            if len(name) > HOLDER_NAME_MAX:
                name = name[: HOLDER_NAME_MAX - 1] + "…"
            self._names[holder_id] = name
        return self._names[holder_id]

    @staticmethod
    def _ratio(progress: int, goal: int) -> float:
        return min(1.0, progress / goal) if goal and goal > 0 else 0.0

    def of(self, title) -> tuple[str, float]:
        """(ligne de progression, proximité de 0 à 1) d'un titre non débloqué."""
        kind, target, goal = title.condition_type, title.condition_target, title.condition_value

        if kind == "kills_family" and target:
            progress = self.kill_repo.get_kills_for_family(self.pid, target)
            family = FAMILY_LABELS.get(target, target.replace("_", " "))
            return f"**{progress}/{goal}** victoires contre les {family}", self._ratio(progress, goal)

        if kind == "kills_total":
            return f"**{self.total_kills}/{goal}** monstres vaincus", self._ratio(self.total_kills, goal)

        if kind == "kills_mob" and target:
            progress = self.per_mob.get(target, 0)
            return f"**{progress}/{goal}** victoires", self._ratio(progress, goal)

        if kind == "dodges_total":
            career = PlayerCareerStatsRepository(self.session).get_or_create(self.pid)
            progress = getattr(career, "dodges_total", 0)
            return f"**{progress}/{goal}** esquives en combat", self._ratio(progress, goal)

        if kind == "daily_streak":
            progress = self.profile.resources.daily_streak
            return f"**{progress}/{goal}** jours de suite au `/daily`", self._ratio(progress, goal)

        if kind == "weekly_role_trial":
            holder_id = self.excl.current_holder(title.code)
            if holder_id is None:
                return (f"_personne cette semaine — résultats des défis le dimanche à "
                        f"{RESULTS_HOUR} h (`/defi`)_"), 0.0
            if holder_id == self.pid:
                return "_tu le détiens cette semaine !_", 1.0
            return f"détenu par **{self.holder_name(holder_id)}** cette semaine (`/defi`)", 0.0

        if kind == "kills_record":
            holder_id = self.excl.current_holder(title.code)
            if holder_id is None:
                return f"_personne ne détient encore le record_ · toi : **{self.total_kills}** monstres vaincus", 0.0
            holder_total = self.kill_repo.get_total_kills(holder_id)
            if holder_id == self.pid:
                return f"_tu détiens le record avec_ **{holder_total}** monstres vaincus", 1.0
            # Il faut dépasser strictement : au moins un de plus que le détenteur.
            gap = max(0, holder_total - self.total_kills + 1)
            return (f"détenu par **{self.holder_name(holder_id)}** (**{holder_total}** monstres vaincus) · "
                    f"toi : **{self.total_kills}**, il t'en manque **{gap}**"), self._ratio(self.total_kills, holder_total + 1)

        if kind == "records_rank":
            holder_id = self.excl.current_holder(title.code)
            if holder_id is None:
                return "_personne ne le détient — les records sont mis à jour chaque nuit (`/records`)_", 0.0
            if holder_id == self.pid:
                return "_tu le détiens jusqu'à la prochaine mise à jour, à minuit (`/records`)_", 1.0
            return f"détenu par **{self.holder_name(holder_id)}** · bats des records pour le prendre (`/records`)", 0.0

        if kind == "world_boss_mvp":
            holder_id = self.excl.current_holder(title.code)
            if holder_id is None:
                return "_personne ne le détient — il va au meilleur contributeur du prochain boss vaincu_", 0.0
            if holder_id == self.pid:
                return "_tu le détiens jusqu'au prochain boss vaincu_", 1.0
            return f"détenu par **{self.holder_name(holder_id)}** · sois le meilleur contributeur du prochain boss vaincu", 0.0

        if kind == "world_boss_kill":
            return "_participe à une victoire contre ce boss au raid_", 0.0

        if kind == "event":
            return "_se gagne lors d'un événement_", 0.0

        if kind == "card_album":
            percent = self.album.percent
            return f"**{percent} %** de l'album sur **{goal} %** (`/album`)", self._ratio(percent, goal)

        if kind == "card_brillante":
            album = self.album
            return (f"**{album.brillantes}/{album.total}** cartes brillantes (`/album`)",
                    self._ratio(album.brillantes, album.total))

        return "_à découvrir_", 0.0


class TitleBookView(PagedBookView):
    """Les pages de `/titre` (◀ n/N ▶), réservées à celui qui a tapé la commande."""

    command = "/titre"

    async def render(self) -> tuple[discord.Embed, None]:
        return self.pages[self.index], None


class TitleCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="titre", description="Afficher les titres débloqués d'un joueur"
    )
    @app_commands.describe(target="Joueur ciblé (par défaut : toi)")
    async def title(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        target_member = target or interaction.user
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(target_member.id)
            if profile is None:
                await interaction.response.send_message(
                    f"❌ {target_member.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return
            title_repo = PlayerTitleRepository(session)
            unlocked_codes = title_repo.list_codes_for_player(profile.player.id)
            active_code = title_repo.get_active_title_code(profile.player.id)

            definitions = list_definitions()
            unlocked = [d for d in definitions if d.code in unlocked_codes]
            locked = [d for d in definitions if d.code not in unlocked_codes]

            # On reste DANS la session : la progression lit les victoires, la
            # carrière, les détenteurs des titres disputés et l'album.
            progress = TitleProgress(session, profile)
            labels: dict[str, str] = {}
            closeness: dict[str, float] = {}
            for definition in locked:
                labels[definition.code], closeness[definition.code] = progress.of(definition)

        pages = build_title_pages(
            target_member.display_name, unlocked, locked, labels,
            active_code=active_code, total=len(definitions), closeness=closeness,
        )
        if len(pages) == 1:
            await interaction.response.send_message(embed=pages[0])
            return
        view = TitleBookView(interaction.user.id, pages)
        view._refresh_buttons()
        await interaction.response.send_message(embed=pages[0], view=view)

    @app_commands.command(
        name="titre_actif",
        description="Choisis le titre affiché sur ton profil",
    )
    @app_commands.describe(
        title="Code du titre à afficher (laisser vide pour désactiver)"
    )
    async def title_set(
        self,
        interaction: discord.Interaction,
        title: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            title_repo = PlayerTitleRepository(session)

            if title is None:
                title_repo.set_active(profile.player.id, None)
                await interaction.followup.send(
                    "✅ Aucun titre actif : ton profil n'en affiche plus.",
                    ephemeral=True,
                )
                return

            title_def = get_definition(title)
            if title_def is None:
                await interaction.followup.send(
                    f"❌ Titre `{title}` introuvable.", ephemeral=True
                )
                return

            success = title_repo.set_active(profile.player.id, title)
            if not success:
                await interaction.followup.send(
                    f"❌ Tu n'as pas débloqué **{title_def.name}**.",
                    ephemeral=True,
                )
                return

        await interaction.followup.send(
            f"✅ Titre actif : {title_def.icon} **{title_def.name}**.", ephemeral=True
        )

    @title_set.autocomplete("title")
    async def title_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []
            unlocked = PlayerTitleRepository(session).list_codes_for_player(
                profile.player.id
            )
        defs = [d for d in list_definitions() if d.code in unlocked]
        current_lower = current.lower()
        return [
            app_commands.Choice(name=f"{d.icon} {d.name} ({d.code})", value=d.code)
            for d in defs
            if current_lower in d.code.lower() or current_lower in d.name.lower()
        ][:25]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TitleCog(bot))
