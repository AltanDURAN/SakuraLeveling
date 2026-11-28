import discord
from discord.ext import commands

from app.application.services.player_stats_resolver import resolve_player_stats
from app.shared.formatters import format_int as _format_int
from app.domain.services.progression_service import ProgressionService
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_health_repository import (
    PlayerHealthRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.session import get_db_session
from app.bot.cogs.admin_group import admin as admin_group
from app.bot.cogs.admin_players import AdminPlayersMixin
from app.bot.cogs.admin_shop import AdminShopMixin
from app.bot.cogs.admin_items import AdminItemsMixin


class AdminCog(AdminPlayersMixin, AdminShopMixin, AdminItemsMixin, commands.Cog):
    """Commandes administrateur — réservées aux Discord IDs listés dans `ADMIN_DISCORD_IDS`."""

    # Le groupe vit dans `admin_group` : les mixins y accrochent leurs commandes.
    admin = admin_group

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # -------------------------- Or --------------------------

    # -------------------------- Resource triplet (set/give/remove) --------------------------
    #
    # Une seule commande paramétrée par action pour rester sous la limite
    # Discord de 25 child-commands par groupe. Le param `resource` choisit
    # quelle ressource manipuler.


    async def _apply_resource(
        self,
        action: str,  # "set" | "give" | "remove"
        resource: str,
        target: discord.Member,
        amount: int,
    ) -> str:
        with get_db_session() as session:
            repo = PlayerRepository(session)
            profile = repo.get_by_discord_id(target.id)
            if profile is None:
                return f"❌ {target.display_name} n'a pas encore de profil."

            if resource == "gold":
                current = profile.resources.gold
                if action == "set":
                    new = max(0, amount)
                elif action == "give":
                    new = current + amount
                else:
                    new = max(0, current - amount)
                repo.set_gold(profile.player.id, new)
                label = "Or"

            elif resource == "xp":
                current = profile.progression.xp
                if action == "set":
                    new = max(0, amount)
                    repo.apply_progression(
                        profile.player.id, profile.progression.level, new,
                        profile.progression.skill_points, source="admin",
                    )
                elif action == "give":
                    # Avec level-up calculé proprement
                    progression_service = ProgressionService()
                    result = progression_service.apply_level_up(
                        current_level=profile.progression.level,
                        current_xp=current,
                        gained_xp=amount,
                        current_skill_points=profile.progression.skill_points,
                        current_stat_points=profile.progression.stat_points,
                    )
                    repo.apply_progression(
                        profile.player.id, result.level, result.xp,
                        result.skill_points, result.stat_points, source="admin",
                    )
                    new = result.xp
                else:
                    new = max(0, current - amount)
                    repo.apply_progression(
                        profile.player.id, profile.progression.level, new,
                        profile.progression.skill_points, source="admin",
                    )
                label = "XP"

            elif resource == "skill_points":
                current = profile.progression.skill_points
                if action == "set":
                    repo.set_skill_points(profile.player.id, max(0, amount))
                    new = max(0, amount)
                elif action == "give":
                    repo.add_skill_points(profile.player.id, amount)
                    new = current + amount
                else:
                    repo.add_skill_points(profile.player.id, -amount)
                    new = max(0, current - amount)
                label = "Skill points"

            elif resource == "stat_points":
                # Points de stats EN RÉSERVE (pas ceux déjà placés via /stats).
                current = profile.progression.stat_points
                if action == "set":
                    new = max(0, amount)
                elif action == "give":
                    new = current + amount
                else:
                    new = max(0, current - amount)
                prog = profile.progression
                repo.apply_progression(
                    profile.player.id, prog.level, prog.xp, prog.skill_points, new, source="admin",
                )
                label = "Points de stats"

            elif resource == "current_hp":
                equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)
                # Chaîne complète (arbre + sets + titres) pour un
                # max_hp correct (l'inline ne comptait que les sets).
                stats = resolve_player_stats(session, profile, equipped)
                health_repo = PlayerHealthRepository(session)
                state = health_repo.get_or_create(
                    profile.player.id, default_current_hp=stats.max_hp,
                )
                if action == "set":
                    new = max(0, min(stats.max_hp, amount))
                elif action == "give":
                    new = min(stats.max_hp, state.current_hp + amount)
                else:
                    new = max(0, state.current_hp - amount)
                health_repo.update_current_hp(profile.player.id, new)
                label = f"PV courants (max {stats.max_hp})"

            elif resource == "current_mana":
                from app.infrastructure.db.repositories.player_mana_repository import (
                    PlayerManaRepository,
                )
                equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)
                stats = resolve_player_stats(session, profile, equipped)
                mana_repo = PlayerManaRepository(session)
                state = mana_repo.get_or_create(
                    profile.player.id, default_current_mana=stats.mana_max,
                )
                if action == "set":
                    new = max(0, min(stats.mana_max, amount))
                elif action == "give":
                    new = min(stats.mana_max, state.current_mana + amount)
                else:
                    new = max(0, state.current_mana - amount)
                mana_repo.update_current_mana(profile.player.id, new)
                label = f"Mana courant (max {stats.mana_max})"

            elif resource == "daily_streak":
                current = profile.resources.daily_streak
                if action == "set":
                    new = max(0, amount)
                elif action == "give":
                    new = current + amount
                else:
                    new = max(0, current - amount)
                repo.set_daily_streak(profile.player.id, new)
                label = "Daily streak"

            elif resource == "tower_floor":
                from app.domain.services.tower_service import TOWER_FLOORS
                from app.infrastructure.db.repositories.tower_repository import TowerRepository

                tower_repo = TowerRepository(session)
                current = tower_repo.best_floor(profile.player.id)
                if action == "set":
                    new = amount
                elif action == "give":
                    new = current + amount
                else:
                    new = current - amount
                new = max(0, min(TOWER_FLOORS, new))
                tower_repo.set_best_floor(profile.player.id, new)
                label = "Étage record de la tour"

            else:
                return f"❌ Ressource inconnue : `{resource}`."

        verb = {"set": "défini à", "give": "augmenté à", "remove": "réduit à"}[action]
        delta = (
            "" if action == "set"
            else f" ({'+' if action == 'give' else '-'}{_format_int(amount)})"
        )
        return f"✅ {label} de {target.mention} {verb} **{_format_int(new)}**{delta}."


    # -------------------------- Niveau (cas spécial) --------------------------


    # -------------------------- Items --------------------------


    # -------------------------- Classe active --------------------------


    # -------------------------- Kill counter --------------------------


    # -------------------------- Équipement forcé --------------------------


    # -------------------------- Défis de rôle --------------------------


    # -------------------------- Encounter management --------------------------


    # -------------------------- Outils de test --------------------------


    # -------------------------- Shop --------------------------


    # -------------------------- Autocomplete --------------------------


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
