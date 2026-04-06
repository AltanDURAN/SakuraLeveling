import discord

from app.bot.runtime.active_encounter import ActiveEncounter


def build_encounter_spawn_embed(encounter: ActiveEncounter) -> discord.Embed:
    embed = discord.Embed(
        title=f"🚨 Un {encounter.mob_name} apparaît !",
        description=(
            "Des aventuriers peuvent rejoindre le combat.\n"
            "Cliquez sur **Combattre** dans les 5 minutes."
        ),
        color=discord.Color.dark_red(),
    )

    if encounter.mob_image_url:
        embed.set_thumbnail(url=encounter.mob_image_url)

    embed.add_field(name="⏳ Temps restant", value="5 minutes", inline=True)
    embed.add_field(name="👥 Participants", value=str(len(encounter.participant_user_ids)), inline=True)

    embed.set_footer(text="Préparez-vous au combat.")
    return embed


def build_encounter_no_participants_embed(encounter: ActiveEncounter) -> discord.Embed:
    embed = discord.Embed(
        title=f"💨 {encounter.mob_name} s'est enfui",
        description="Aucun aventurier n'a répondu à l'appel.",
        color=discord.Color.light_grey(),
    )

    if encounter.mob_image_url:
        embed.set_thumbnail(url=encounter.mob_image_url)

    return embed