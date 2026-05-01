import discord
from discord import app_commands
from discord.ext import commands

from app.bot.checks.admin_check import admin_only
from app.domain.services.progression_service import ProgressionService
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


class AdminCog(commands.Cog):
    """Commandes administrateur — réservées aux Discord IDs listés dans `ADMIN_DISCORD_IDS`."""

    admin = app_commands.Group(
        name="admin",
        description="Commandes administrateur",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -------------------------- Or --------------------------

    @admin.command(name="give_gold", description="Ajoute de l'or à un joueur")
    @app_commands.describe(target="Joueur ciblé", amount="Quantité d'or à ajouter")
    @admin_only
    async def give_gold(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            player_repository.add_gold(profile.player.id, amount)

        await interaction.followup.send(
            f"✅ **{_format_int(amount)}** or ajouté à {target.mention}.",
            ephemeral=True,
        )

    @admin.command(name="set_gold", description="Définit le montant d'or d'un joueur")
    @app_commands.describe(target="Joueur ciblé", amount="Nouvelle quantité d'or (>= 0)")
    @admin_only
    async def set_gold(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 0, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            player_repository.set_gold(profile.player.id, amount)

        await interaction.followup.send(
            f"✅ Or de {target.mention} défini à **{_format_int(amount)}**.",
            ephemeral=True,
        )

    # -------------------------- XP / Niveau --------------------------

    @admin.command(name="give_xp", description="Ajoute de l'XP à un joueur (peut faire monter de niveau)")
    @app_commands.describe(target="Joueur ciblé", amount="Quantité d'XP à ajouter")
    @admin_only
    async def give_xp(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        progression_service = ProgressionService()

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            new_level, new_xp, new_skill_points = progression_service.apply_level_up(
                current_level=profile.progression.level,
                current_xp=profile.progression.xp,
                gained_xp=amount,
                current_skill_points=profile.progression.skill_points,
            )

            player_repository.apply_progression(
                player_id=profile.player.id,
                new_level=new_level,
                new_xp=new_xp,
                new_skill_points=new_skill_points,
            )

            level_msg = (
                f" — niveau **{profile.progression.level} → {new_level}**"
                if new_level > profile.progression.level
                else ""
            )

        await interaction.followup.send(
            f"✅ **{_format_int(amount)}** XP ajoutés à {target.mention}{level_msg}.",
            ephemeral=True,
        )

    @admin.command(name="set_level", description="Définit le niveau d'un joueur (XP remis à 0 pour ce niveau)")
    @app_commands.describe(target="Joueur ciblé", level="Nouveau niveau (>= 1)")
    @admin_only
    async def set_level(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        level: app_commands.Range[int, 1, 1000],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            profile = player_repository.get_by_discord_id(target.id)

            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            player_repository.apply_progression(
                player_id=profile.player.id,
                new_level=level,
                new_xp=0,
                new_skill_points=profile.progression.skill_points,
            )

        await interaction.followup.send(
            f"✅ Niveau de {target.mention} défini à **{level}**.",
            ephemeral=True,
        )

    # -------------------------- Items --------------------------

    @admin.command(name="give_item", description="Ajoute un objet à l'inventaire d'un joueur")
    @app_commands.describe(
        target="Joueur ciblé",
        item_code="Code de l'objet (ex : slime_gel)",
        quantity="Quantité à ajouter",
    )
    @admin_only
    async def give_item(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        item_code: str,
        quantity: app_commands.Range[int, 1, 9999],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            item_repository = ItemRepository(session)
            inventory_repository = InventoryRepository(session)

            profile = player_repository.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            item = item_repository.get_by_code(item_code)
            if item is None:
                await interaction.followup.send(
                    f"❌ Objet `{item_code}` introuvable.",
                    ephemeral=True,
                )
                return

            inventory_repository.add_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=quantity,
            )

        await interaction.followup.send(
            f"✅ {quantity}× **{item.name}** ajouté à l'inventaire de {target.mention}.",
            ephemeral=True,
        )

    @admin.command(name="remove_item", description="Retire un objet de l'inventaire d'un joueur")
    @app_commands.describe(
        target="Joueur ciblé",
        item_code="Code de l'objet",
        quantity="Quantité à retirer",
    )
    @admin_only
    async def remove_item(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        item_code: str,
        quantity: app_commands.Range[int, 1, 9999],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            item_repository = ItemRepository(session)
            inventory_repository = InventoryRepository(session)

            profile = player_repository.get_by_discord_id(target.id)
            if profile is None:
                await interaction.followup.send(
                    f"❌ {target.display_name} n'a pas encore de profil.",
                    ephemeral=True,
                )
                return

            item = item_repository.get_by_code(item_code)
            if item is None:
                await interaction.followup.send(
                    f"❌ Objet `{item_code}` introuvable.",
                    ephemeral=True,
                )
                return

            removed = inventory_repository.remove_item(
                player_id=profile.player.id,
                item_definition_id=item.id,
                quantity=quantity,
            )

            if not removed:
                await interaction.followup.send(
                    f"❌ {target.display_name} ne possède pas {quantity}× **{item.name}**.",
                    ephemeral=True,
                )
                return

        await interaction.followup.send(
            f"✅ {quantity}× **{item.name}** retiré de l'inventaire de {target.mention}.",
            ephemeral=True,
        )

    @give_item.autocomplete("item_code")
    @remove_item.autocomplete("item_code")
    async def item_code_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        with get_db_session() as session:
            item_repository = ItemRepository(session)
            items = item_repository.list_all()

        if not items:
            return []

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        for item in items:
            if (
                current_lower in item.code.lower()
                or current_lower in item.name.lower()
            ):
                choices.append(
                    app_commands.Choice(
                        name=f"{item.name} ({item.code})",
                        value=item.code,
                    )
                )

            if len(choices) >= 25:
                break

        return choices


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
