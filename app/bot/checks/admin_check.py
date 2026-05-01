import discord
from discord import app_commands

from app.infrastructure.config.settings import settings


def is_admin_user(user_id: int) -> bool:
    return user_id in settings.admin_ids


async def _admin_predicate(interaction: discord.Interaction) -> bool:
    if not is_admin_user(interaction.user.id):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Cette commande est réservée aux administrateurs.",
                ephemeral=True,
            )
        return False
    return True


admin_only = app_commands.check(_admin_predicate)
