"""Accès aux salons (parcours d'arrivée) depuis le VPS, sans passer par Discord.

Même plan que `/admin acces` (`app/bot/access.py`) : l'accueil et le règlement
pour tous en lecture seule, le tutoriel, la tour et la première zone au Rang F
(règlement accepté), chaque zone à son rang, tout le reste au rôle Aventurier
(tutoriel fini ou passé). Les salons d'équipe ne sont pas touchés.

    .venv/bin/python -m scripts.channel_access                  # aperçu, ne change rien
    .venv/bin/python -m scripts.channel_access --confirm        # applique
    .venv/bin/python -m scripts.channel_access --create-role    # crée le rôle Aventurier s'il manque

Il passe par l'API REST avec le jeton du bot : le bot continue de tourner.
"""

from __future__ import annotations

import argparse
import asyncio

import discord

from app.bot import access
from app.infrastructure.config.settings import settings


async def _create_role(guild: discord.Guild) -> None:
    if settings.adventurer_role_id and guild.get_role(settings.adventurer_role_id):
        print(f"Le rôle Aventurier existe déjà ({settings.adventurer_role_id}).")
        return
    role = await guild.create_role(name=access.ADVENTURER_NAME, permissions=discord.Permissions.none(),
                                   reason=access.REASON)
    print(f"Rôle « {role.name} » créé : ajoute ADVENTURER_ROLE_ID={role.id} dans .env, puis redémarre le bot.")


async def main(confirm: bool, create_role: bool) -> int:
    client = discord.Client(intents=discord.Intents.none())
    await client.login(settings.discord_token)
    try:
        guild = await client.fetch_guild(settings.discord_guild_id)
        if create_role:
            await _create_role(guild)
            return 0
        if not access.configured():
            print("Rôles du parcours non configurés : RANK_ROLE_IDS et ADVENTURER_ROLE_ID (--create-role).")
            return 1
        if guild.get_role(settings.adventurer_role_id) is None:
            print(f"Le rôle Aventurier {settings.adventurer_role_id} n'existe pas sur le serveur.")
            return 1
        channels = await guild.fetch_channels()
        plan = access.plan(guild.id, channels)
        print(f"{guild.name} : {len(channels)} salons, {len(plan.changes)} à régler.\n")
        for change in plan.changes:
            print("  " + change.line.replace("**", ""))
        if plan.private:
            print("\nLaissés tels quels (salons d'équipe) : " + ", ".join(plan.private))
        if not plan.changes:
            print("Tout est déjà en place.")
            return 0
        if not confirm:
            print("\nAperçu seulement : relance avec --confirm pour appliquer.")
            return 0
        done, failed = await access.settle(guild, guild.fetch_channels)
        print(f"\n{done} salon(s) réglé(s), {len(failed)} échec(s).")
        for line in failed:
            print("  ❌ " + line)
        return 1 if failed else 0
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confirm", action="store_true", help="applique les changements")
    parser.add_argument("--create-role", action="store_true", help="crée le rôle Aventurier s'il manque")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.confirm, args.create_role)))
