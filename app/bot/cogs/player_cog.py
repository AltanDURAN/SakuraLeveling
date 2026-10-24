import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, UTC

from app.application.services.set_bonus_resolver import resolve_set_bonuses
from app.application.services.player_stats_resolver import resolve_player_stats
from app.domain.entities.player_profile import PlayerProfile
from app.shared.formatters import format_int as _format_int
from app.application.use_cases.transfer_gold import TransferGoldUseCase
from app.application.use_cases.claim_daily_reward import ClaimDailyRewardUseCase
from app.application.use_cases.challenge_player import ChallengePlayerUseCase
from app.application.use_cases.use_consumable import UseConsumableUseCase
from app.application.use_cases.get_player_equipment import GetPlayerEquipmentUseCase
from app.application.use_cases.equip_item import (
    EquipItemUseCase,
    plan_equip,
)
from app.bot.embeds.duel_embeds import (
    build_duel_intro_embed,
    build_duel_result_embed,
    build_duel_turn_embed,
)
from app.bot.embeds.daily_embeds import (
    build_daily_cooldown_embed,
    build_daily_success_embed,
)
from app.bot.views.equipment_view import EquipmentView
from app.bot.views.inventory_view import InventoryView
from app.bot.embeds.inventory_embeds import build_inventory_embed
from app.bot.embeds.player_embeds import build_player_profile_embed
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.duel_combat_service import DuelCombatService
from app.domain.services.stats_service import StatsService
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.element_affinity_repository import (
    ElementAffinityRepository,
)
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_duel_rank_repository import (
    PlayerDuelRankRepository,
)
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.session import get_db_session
from app.shared.enums import EQUIPMENT_SLOT_LABELS, SLOT_LABELS
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.infrastructure.db.repositories.player_health_repository import PlayerHealthRepository
from app.domain.services.power_score_service import PowerScoreService
from app.bot.cogs._mixins import BetaChannelOnlyMixin


class PlayerCog(BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _resolve_profile(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None,
        session,
    ) -> tuple[PlayerProfile | None, discord.abc.User]:
        """Renvoie (profile, target_member). Si target est None, get_or_create
        le profil de l'auteur. Si target est spécifié, lookup pur (pas de
        création). Le profil est None si target n'a jamais joué."""
        repo = PlayerRepository(session)

        if target is None:
            target_member = interaction.user
            profile = repo.get_or_create_by_discord_id(
                discord_id=target_member.id,
                username=target_member.name,
                display_name=target_member.display_name,
            )
        else:
            target_member = target
            profile = repo.get_by_discord_id(target_member.id)

        return profile, target_member

    async def _send_no_profile_error(
        self,
        interaction: discord.Interaction,
        target_member,
    ) -> None:
        message = (
            f"❌ {target_member.display_name} n'a pas encore de profil joueur."
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="ping", description="Vérifier si le bot fonctionne")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("🏓 Pong !")

    @app_commands.command(name="profil", description="Afficher un profil joueur")
    @app_commands.describe(target="Joueur dont afficher le profil (par défaut : vous)")
    async def profile(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        # defer() AVANT le calcul de stats + le rendu Pillow (évite Unknown
        # interaction). _send_no_profile_error gère le cas déjà-répondu.
        await interaction.response.defer()
        # Filet de sécurité : quiconque consulte SON profil obtient le Rang F
        # s'il ne l'a pas encore (no-op s'il porte déjà un rôle de rang).
        if target is None and isinstance(interaction.user, discord.Member):
            from app.bot.rank_roles import ensure_start_rank_role
            await ensure_start_rank_role(interaction.user)
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            equipment_repository = EquipmentRepository(session)
            player_health_repository = PlayerHealthRepository(session)
            kill_repository = PlayerKillRepository(session)
            career_stats_repository = PlayerCareerStatsRepository(session)
            skill_allocation_repository = PlayerSkillAllocationRepository(session)

            equipped_items = equipment_repository.list_by_player_id(profile.player.id)
            allocations = skill_allocation_repository.list_by_player(profile.player.id)
            skill_bonuses = SkillTreeService(get_skill_tree_definition()).aggregate_bonuses(
                allocations
            )
            from app.application.services.title_bonus_resolver import (
                resolve_title_bonuses,
            )
            from app.application.services.set_bonus_resolver import (
                resolve_set_bonuses,
            )
            from app.application.services.status_effect_resolver import (
                resolve_status_effects,
            )
            title_bonuses = resolve_title_bonuses(session, profile.player.id)
            set_bonuses = resolve_set_bonuses(equipped_items, profile.player.panoplie_bonus)
            status_bonuses = resolve_status_effects(session, profile.player.id)
            stats = StatsService().calculate_player_stats(
                profile=profile,
                equipped_items=equipped_items,
                skill_bonuses=skill_bonuses,
                title_bonuses=title_bonuses,
                set_bonuses=set_bonuses,
                status_bonuses=status_bonuses,
            )

            power_score_service = PowerScoreService()
            raw_power_score = power_score_service.calculate_from_stats(stats)
            formatted_power_score = power_score_service.format_score(raw_power_score)
            rank_label = power_score_service.compute_rank(raw_power_score)

            health_state = player_health_repository.get_or_create(
                player_id=profile.player.id,
                default_current_hp=stats.max_hp,
            )

            now = datetime.now(UTC)
            regenerated_current_hp = HealthRegenerationService().apply_out_of_combat_regeneration(
                current_hp=health_state.current_hp,
                max_hp=stats.max_hp,
                hp_regeneration=stats.hp_regeneration,
                last_updated_at=health_state.updated_at,
                now=now,
            )

            # On ne persiste la régénération que pour soi-même : éviter d'écrire
            # sur le profil d'un tiers en simple consultation.
            if regenerated_current_hp != health_state.current_hp and target is None:
                player_health_repository.refresh_current_hp(
                    player_id=profile.player.id,
                    new_current_hp=regenerated_current_hp,
                )

            # Mana courant : miroir strict du HP (régén hors combat uniquement).
            from app.infrastructure.db.repositories.player_mana_repository import (
                PlayerManaRepository,
            )
            from app.domain.services.mana_regeneration_service import (
                ManaRegenerationService,
            )
            player_mana_repository = PlayerManaRepository(session)
            mana_state = player_mana_repository.get_or_create(
                player_id=profile.player.id,
                default_current_mana=stats.mana_max,
            )
            regenerated_current_mana = ManaRegenerationService().apply_out_of_combat_regeneration(
                current_mana=mana_state.current_mana,
                mana_max=stats.mana_max,
                mana_regeneration=stats.mana_regeneration,
                last_updated_at=mana_state.updated_at,
                now=now,
            )
            if regenerated_current_mana != mana_state.current_mana and target is None:
                player_mana_repository.refresh_current_mana(
                    player_id=profile.player.id,
                    new_current_mana=regenerated_current_mana,
                )

            total_kills = kill_repository.get_total_kills(profile.player.id)
            career_stats = career_stats_repository.get_or_create(profile.player.id)

            duel_rank = PlayerDuelRankRepository(session).get_by_player_id(
                profile.player.id
            )

            from app.infrastructure.db.repositories.player_title_repository import (
                PlayerTitleRepository,
            )
            from app.infrastructure.titles.title_loader import get_definition as _get_title_def

            active_title_code = PlayerTitleRepository(session).get_active_title_code(
                profile.player.id
            )
            active_title_name: str | None = None
            if active_title_code:
                title_def = _get_title_def(active_title_code)
                if title_def is not None:
                    active_title_name = f"{title_def.icon} {title_def.name}"

            affinities = ElementAffinityRepository(session).get_affinities(
                profile.player.id
            )

        # NB : l'embed texte de fallback n'est construit QUE dans le except
        # (cf. plus bas) — inutile de le calculer à chaque appel sur le chemin
        # nominal (bannière image).

        # Bannière Pillow CONTIENT TOUT le profil — l'embed n'est qu'un
        # conteneur minimaliste pour l'image (pas de duplication des
        # informations en fields). Si la génération échoue, on retombe
        # sur l'embed texte historique.
        try:
            from app.bot.rendering.profile_banner import (
                compose_profile_banner, _rank_color,
            )
            from app.domain.services.progression_service import ProgressionService
            from app.shared.paths import GENERATED_PROFILES_DIR

            GENERATED_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
            banner_filename = f"profile_{profile.player.id}.png"
            banner_path = GENERATED_PROFILES_DIR / banner_filename

            avatar_url = (
                target_member.display_avatar.url if target_member else None
            )
            # Classes : obtenues dans l'arbre de compétences (cases « classe »).
            # ⚠️ Pas d'import local ici : il rendrait ces noms LOCAUX à toute la
            # fonction et ferait planter leur premier usage plus haut.
            classes = SkillTreeService(get_skill_tree_definition()).class_names(allocations)
            class_name = " · ".join(classes) if classes else None
            xp_required = ProgressionService().xp_required_for_next_level(
                profile.progression.level
            )

            career_payload = {}
            if career_stats is not None:
                career_payload = {
                    "monsters_killed": total_kills,
                    "combats_fought": career_stats.combats_fought,
                    "combats_won": career_stats.combats_won,
                    "combats_lost": career_stats.combats_lost,
                    "gold_earned_total": career_stats.gold_earned_total,
                    "damage_dealt_total": career_stats.damage_dealt_total,
                    "damage_tanked_total": career_stats.damage_tanked_total,
                    "hp_healed_total": career_stats.hp_healed_total,
                    "dodges_total": getattr(career_stats, "dodges_total", 0),
                }

            # Affinités élémentaires : la stat la plus lente du jeu, affichée
            # sur la bannière pour ne pas obliger à passer par /affinites.
            _aff_repo = ElementAffinityRepository(session)
            _talents = _aff_repo.get_talents(profile.player.id)
            affinities_payload = _aff_repo.get_affinities(profile.player.id)
            _revealed = _aff_repo.revealed_elements(profile.player.id)
            affinity_talents_payload = {
                code: {
                    "known": True, "dead": t.dead, "cap": t.cap, "boosts": t.boosts,
                }
                for code, t in _talents.items() if code in _revealed
            }

            # Rendu Pillow sync + download avatar Discord : off-thread pour ne
            # pas bloquer l'event loop (cf. audit B5).
            await asyncio.to_thread(
                compose_profile_banner,
                output_path=str(banner_path),
                display_name=profile.player.display_name,
                avatar_url=avatar_url,
                level=profile.progression.level,
                xp_current=profile.progression.xp,
                xp_required=xp_required,
                gold=profile.resources.gold,
                rank_label=rank_label,
                power_score=formatted_power_score,
                class_name=class_name,
                active_title=active_title_name,
                duel_position=duel_rank.rank_position if duel_rank else None,
                duel_wins=duel_rank.wins if duel_rank else 0,
                duel_losses=duel_rank.losses if duel_rank else 0,
                daily_streak=profile.resources.daily_streak,
                skill_points=profile.progression.skill_points,
                stat_points=profile.progression.stat_points,
                stats={
                    "max_hp": stats.max_hp,
                    "current_hp": regenerated_current_hp,
                    "attack": stats.attack,
                    "defense": stats.defense,
                    "speed": stats.speed,
                    "crit_chance": stats.crit_chance,
                    "crit_damage": stats.crit_damage,
                    "dodge": stats.dodge,
                    "hp_regeneration": stats.hp_regeneration,
                    "mana_max": stats.mana_max,
                    "current_mana": regenerated_current_mana,
                    "mana_regeneration": stats.mana_regeneration,
                },
                career=career_payload,
                affinities=affinities_payload,
                affinity_talents=affinity_talents_payload,
                mythic_pieces=sum(
                    1 for e in equipped_items if getattr(e, "rarity", "") == "mythic"
                ),
            )

            # /profil = bannière PNG seule (l'embed n'est qu'un conteneur pour
            # l'image, pas de navigation ni de duplication en fields).
            image_embed = discord.Embed(color=discord.Color.from_rgb(*_rank_color(rank_label)))
            image_embed.set_image(url=f"attachment://{banner_filename}")
            file = discord.File(str(banner_path), filename=banner_filename)
            await interaction.followup.send(embed=image_embed, file=file)
            return
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning(
                "Profile banner render failed, falling back to text embed: %s",
                _e, exc_info=True,
            )

        # Fallback : embed texte plein de fields (construit uniquement ici,
        # quand la bannière échoue — pas à chaque /profil).
        embed = build_player_profile_embed(
            profile=profile,
            stats=stats,
            current_hp=regenerated_current_hp,
            power_score=formatted_power_score,
            rank_label=rank_label,
            total_kills=total_kills,
            career_stats=career_stats,
            duel_rank_position=duel_rank.rank_position if duel_rank else None,
            duel_wins=duel_rank.wins if duel_rank else 0,
            duel_losses=duel_rank.losses if duel_rank else 0,
            active_title=active_title_name,
            affinities=affinities,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="inventaire", description="Afficher un inventaire")
    @app_commands.describe(target="Joueur dont afficher l'inventaire (par défaut : vous)")
    async def inventory(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            inventory_repository = InventoryRepository(session)
            items = inventory_repository.list_by_player_id(profile.player.id)

        view = InventoryView(target_member.display_name, items)
        await interaction.response.send_message(embed=view._build_embed(), view=view)

    @app_commands.command(
        name="equipement",
        description="Afficher l'équipement en image (2 pages : emplacements / résumé)",
    )
    @app_commands.describe(target="Joueur dont afficher l'équipement (par défaut : vous)")
    async def equipment(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        await interaction.response.defer()
        from app.bot.views.equipment_image_view import EquipmentImageView

        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            equipment_repository = EquipmentRepository(session)
            equipment_items = equipment_repository.list_by_player_id(profile.player.id)
            set_bonuses = resolve_set_bonuses(equipment_items, profile.player.panoplie_bonus)

        try:
            view = EquipmentImageView(
                player_id=profile.player.id,
                player_name=target_member.display_name,
                equipped_items=equipment_items,
                set_bonuses=set_bonuses,
                timeout=600.0,
            )
            embed, file = await asyncio.to_thread(view.render_current_page)
            await interaction.followup.send(embed=embed, file=file, view=view)
        except Exception as _e:
            # Fallback historique : embed texte 2 pages si Pillow plante
            import logging
            logging.getLogger(__name__).warning(
                "Equipment image render failed, falling back to text embed: %s",
                _e, exc_info=True,
            )
            fallback = EquipmentView(
                target_name=target_member.display_name,
                equipped_items=equipment_items,
                timeout=600.0,
            )
            await interaction.followup.send(
                embed=fallback.current_embed, view=fallback,
            )

    @app_commands.command(
        name="equipement_liste",
        description="Liste les équipements possédés par catégorie (équipés ou non)",
    )
    @app_commands.describe(target="Joueur ciblé (par défaut : vous)")
    async def equipement_list(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        from app.bot.views.equipment_list_view import EquipmentListView

        await interaction.response.defer()
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            from app.infrastructure.db.repositories.gear_repository import GearRepository

            items = GearRepository(session).list_owned(profile.player.id)
            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)

        view = EquipmentListView(
            player_id=profile.player.id,
            display_name=target_member.display_name,
            items=items,
            equipped=equipped,
        )
        embed, file, _, _ = await asyncio.to_thread(view.render_current)
        await interaction.followup.send(embed=embed, file=file, view=view)

    @app_commands.command(name="equiper", description="Équiper une de tes pièces d'équipement")
    @app_commands.describe(piece="La pièce à porter (autocomplétion : tes copies libres, les plus rares d'abord)")
    async def equip(
        self,
        interaction: discord.Interaction,
        piece: str,
    ) -> None:
        from app.application.use_cases.equip_item import rarity_label
        from app.bot.views.equip_confirm_view import (
            EquipConfirmView,
            build_equip_confirm_embed,
            compute_stats_diff,
        )
        from app.domain.entities.player_equipment_item import PlayerEquipmentItem
        from app.infrastructure.db.repositories.gear_repository import GearRepository

        # defer() AVANT le travail lourd (jusqu'à 2 calculs de stats complets) :
        # évite "Unknown interaction" si la DB est chargée.
        await interaction.response.defer()

        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            equipment_repository = EquipmentRepository(session)
            owned = GearRepository(session).list_owned(profile.player.id)

            # Valeur d'autocomplétion « gear:<id> », sinon un code ou un nom
            # tapé à la main : on prend alors la meilleure copie libre.
            gear = None
            if piece.startswith("gear:") and piece[5:].isdigit():
                gear = next((g for g in owned if g.id == int(piece[5:])), None)
            else:
                wanted = piece.strip().lower()
                gear = next((g for g in owned if not g.equipped and wanted in (
                    g.item_definition.code.lower(), g.item_definition.name.lower())), None)
            if gear is None:
                await interaction.followup.send(
                    "❌ Tu ne possèdes pas cette pièce (ou toutes ses copies sont déjà portées).",
                    ephemeral=True,
                )
                return

            item_def = gear.item_definition
            current_equipment = equipment_repository.list_by_player_id(profile.player.id)
            same = next((e for e in current_equipment if e.item_definition.id == item_def.id), None)
            if same is not None:
                target_slot, freed = same.slot, ()
            else:
                # Même décision que le use case, via la fonction pure partagée.
                plan = plan_equip(item_def, {e.slot: e.item_definition for e in current_equipment})
                if plan is None:
                    await interaction.followup.send(
                        f"❌ **{item_def.name}** n'a pas d'emplacement valide.", ephemeral=True,
                    )
                    return
                target_slot, freed = plan.target_slot, plan.freed_slots

            current_in_slot = next((e for e in current_equipment if e.slot == target_slot), None)

            # Emplacement libre : on équipe directement.
            if current_in_slot is None:
                result = EquipItemUseCase(
                    player_repository=PlayerRepository(session),
                    inventory_repository=InventoryRepository(session),
                    equipment_repository=equipment_repository,
                ).execute(
                    discord_id=interaction.user.id,
                    username=interaction.user.name,
                    display_name=interaction.user.display_name,
                    gear_id=gear.id,
                )
                if not result.success:
                    await interaction.followup.send(result.message, ephemeral=True)
                    return
                msg = result.message
                if result.unequipped_items:
                    msg += f"\n_Déséquipé : {', '.join(result.unequipped_items)}._"
                await interaction.followup.send(msg)
                return

            # Sinon : diff de stats avant / après (chaîne complète, titres compris).
            current_stats = resolve_player_stats(session, profile, current_equipment)
            simulated_new = PlayerEquipmentItem(
                id=-1, player_id=profile.player.id, slot=target_slot,
                item_definition=item_def, created_at=current_in_slot.created_at,
                updated_at=current_in_slot.updated_at, rarity=gear.rarity,
                forge_level=gear.forge_level, gear_id=gear.id,
            )
            dropped = {target_slot, *freed}
            simulated = [e for e in current_equipment if e.slot not in dropped] + [simulated_new]
            new_stats = resolve_player_stats(session, profile, simulated)
            replacing = (f"{current_in_slot.item_definition.name} "
                         f"({rarity_label(current_in_slot.rarity)})")
            label = f"{item_def.name} ({rarity_label(gear.rarity)})"

        embed = build_equip_confirm_embed(
            item_name=label, slot=target_slot, replacing_name=replacing,
            diffs=compute_stats_diff(current_stats, new_stats),
        )
        view = EquipConfirmView(
            author_id=interaction.user.id,
            discord_id=interaction.user.id,
            username=interaction.user.name,
            display_name=interaction.user.display_name,
            gear_id=gear.id,
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @equip.autocomplete("piece")
    async def equip_item_code_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Tes copies LIBRES, les plus rares d'abord : une entrée par (pièce,
        rareté), avec le niveau de forge sacrée le plus haut de ces copies."""
        from app.domain.services.gear_service import RARITY_EMOJIS, RARITY_LABELS
        from app.infrastructure.db.repositories.gear_repository import GearRepository

        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []
            owned = GearRepository(session).list_owned(profile.player.id)

        current_lower = current.lower()
        seen: set[tuple[int, str]] = set()
        choices: list[app_commands.Choice[str]] = []
        for g in owned:  # déjà triées : rareté puis forge décroissantes
            d = g.item_definition
            key = (d.id, g.rarity)
            if g.equipped or key in seen:
                continue
            if current_lower not in d.name.lower() and current_lower not in d.code.lower():
                continue
            seen.add(key)
            forge = f" +{g.forge_level}" if g.forge_level else ""
            slot = EQUIPMENT_SLOT_LABELS.get(d.equipment_slot, d.equipment_slot)
            choices.append(app_commands.Choice(
                name=f"{RARITY_EMOJIS.get(g.rarity, '')} {d.name} — "
                     f"{RARITY_LABELS.get(g.rarity, g.rarity).lower()}{forge} ({slot})"[:100],
                value=f"gear:{g.id}",
            ))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(
        name="desequiper",
        description="Déséquiper un emplacement (ou tout, avec slot=all)",
    )
    @app_commands.describe(slot="`all` pour tout retirer, sinon le slot ciblé (autocomplete)")
    async def unequip(
        self,
        interaction: discord.Interaction,
        slot: str,
    ) -> None:
        # Cas spécial : slot="all" → vide tous les emplacements
        if slot.strip().lower() == "all":
            from app.application.use_cases.equipment_sets import (
                UnequipAllUseCase,
            )

            with get_db_session() as session:
                use_case = UnequipAllUseCase(
                    player_repository=PlayerRepository(session),
                    equipment_repository=EquipmentRepository(session),
                )
                result = use_case.execute(
                    discord_id=interaction.user.id,
                    username=interaction.user.name,
                    display_name=interaction.user.display_name,
                )
            await interaction.response.send_message(
                result.message, ephemeral=not result.success,
            )
            return

        with get_db_session() as session:
            profile = PlayerRepository(session).get_or_create_by_discord_id(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )
            equipment_repository = EquipmentRepository(session)
            current = equipment_repository.get_slot(profile.player.id, slot)
            if current is None:
                await interaction.response.send_message(
                    f"❌ Aucun équipement dans **{SLOT_LABELS.get(slot, slot)}**.",
                    ephemeral=True,
                )
                return

            item_name = current.item_definition.name
            was_two_hands = bool(current.item_definition.requires_two_hands)
            equipment_repository.unequip_slot(profile.player.id, slot)

        msg = f"✅ **{item_name}** déséquipé de **{SLOT_LABELS.get(slot, slot)}**."
        if was_two_hands:
            msg += "\n_(Pièce à 2 mains : vos deux emplacements d'arme sont de nouveau libres.)_"
        await interaction.response.send_message(msg)

    @unequip.autocomplete("slot")
    async def unequip_slot_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Liste les slots actuellement occupés + l'option spéciale 'all'."""
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []

            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []

        # Option spéciale : tout déséquiper d'un coup (en tête de liste)
        all_label = f"all — Tout retirer ({len(equipped)} pièce(s))"
        if not current_lower or current_lower in "all":
            choices.append(app_commands.Choice(name=all_label[:100], value="all"))

        for entry in equipped:
            slot_label = SLOT_LABELS.get(entry.slot, entry.slot)
            label = f"{slot_label} — {entry.item_definition.name}"[:100]
            if current_lower and current_lower not in entry.slot.lower():
                continue
            choices.append(app_commands.Choice(name=label, value=entry.slot))
            if len(choices) >= 25:
                break
        return choices

    # ---------------------- Sets d'équipement (loadouts) -----------------

    @app_commands.command(
        name="creer_set",
        description="Sauvegarde l'équipement actuel sous un nom (loadout réutilisable)",
    )
    @app_commands.describe(nom="Nom du set (max 50 caractères, libre)")
    async def create_set(
        self, interaction: discord.Interaction, nom: str,
    ) -> None:
        from app.application.use_cases.equipment_sets import (
            CreateEquipmentSetUseCase,
        )
        from app.infrastructure.db.repositories.equipment_set_repository import (
            EquipmentSetRepository,
        )

        with get_db_session() as session:
            use_case = CreateEquipmentSetUseCase(
                player_repository=PlayerRepository(session),
                equipment_repository=EquipmentRepository(session),
                equipment_set_repository=EquipmentSetRepository(session),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                name=nom,
            )
        await interaction.response.send_message(
            result.message, ephemeral=not result.success,
        )

    @app_commands.command(
        name="supprimer_set",
        description="Supprime un set d'équipement sauvegardé",
    )
    @app_commands.describe(nom="Nom du set à supprimer (autocomplete)")
    async def delete_set(
        self, interaction: discord.Interaction, nom: str,
    ) -> None:
        from app.application.use_cases.equipment_sets import (
            DeleteEquipmentSetUseCase,
        )
        from app.infrastructure.db.repositories.equipment_set_repository import (
            EquipmentSetRepository,
        )

        with get_db_session() as session:
            use_case = DeleteEquipmentSetUseCase(
                player_repository=PlayerRepository(session),
                equipment_set_repository=EquipmentSetRepository(session),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                name=nom,
            )
        await interaction.response.send_message(
            result.message, ephemeral=not result.success,
        )

    @app_commands.command(
        name="equiper_set",
        description="Applique un set d'équipement sauvegardé",
    )
    @app_commands.describe(nom="Nom du set à équiper (autocomplete)")
    async def equip_set(
        self, interaction: discord.Interaction, nom: str,
    ) -> None:
        from app.application.use_cases.equipment_sets import (
            EquipSavedSetUseCase,
        )
        from app.infrastructure.db.repositories.equipment_set_repository import (
            EquipmentSetRepository,
        )

        await interaction.response.defer()
        with get_db_session() as session:
            use_case = EquipSavedSetUseCase(
                player_repository=PlayerRepository(session),
                equipment_repository=EquipmentRepository(session),
                equipment_set_repository=EquipmentSetRepository(session),
                inventory_repository=InventoryRepository(session),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                name=nom,
            )
        await interaction.followup.send(
            result.message, ephemeral=not result.success,
        )

    @delete_set.autocomplete("nom")
    @equip_set.autocomplete("nom")
    async def _set_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        from app.infrastructure.db.repositories.equipment_set_repository import (
            EquipmentSetRepository,
        )

        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(
                interaction.user.id,
            )
            if profile is None:
                return []
            sets = EquipmentSetRepository(session).list_for_player(
                profile.player.id,
            )

        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for s in sets:
            if current_lower and current_lower not in s.name.lower():
                continue
            label = f"{s.name} ({len(s.items)} pièces)"[:100]
            choices.append(app_commands.Choice(name=label, value=s.name))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(
        name="duel",
        description="Défier un autre joueur en duel 1v1 (PvP, sans gain ni perte)",
    )
    @app_commands.describe(target="Joueur à défier")
    async def fight(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if target.bot:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas défier un bot.",
                ephemeral=True,
            )
            return
        if target.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas vous défier vous-même.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        with get_db_session() as session:
            use_case = ChallengePlayerUseCase(
                player_repository=PlayerRepository(session),
                equipment_repository=EquipmentRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                duel_rank_repository=PlayerDuelRankRepository(session),
                cooldown_repository=CooldownRepository(session),
                stats_service=StatsService(),
                duel_combat_service=DuelCombatService(),
                cooldown_service=CooldownService(),
            )
            outcome = use_case.execute(
                challenger_discord_id=interaction.user.id,
                challenger_username=interaction.user.name,
                challenger_display_name=interaction.user.display_name,
                target_discord_id=target.id,
                target_display_name=target.display_name,
            )

        if not outcome.success or outcome.result is None:
            await interaction.followup.send(outcome.message, ephemeral=True)
            return

        challenger_name = outcome.challenger_display_name
        target_name = outcome.target_display_name
        result = outcome.result

        intro = build_duel_intro_embed(
            challenger_name=challenger_name,
            target_name=target_name,
            challenger_max_hp=result.a_max_hp,
            target_max_hp=result.b_max_hp,
        )
        message = await interaction.followup.send(
            content=f"⚔️ {interaction.user.mention} défie {target.mention} !",
            embed=intro,
        )

        await asyncio.sleep(1.5)
        for turn_log in result.turn_logs:
            embed = build_duel_turn_embed(
                challenger_name=challenger_name,
                target_name=target_name,
                result=result,
                turn_log=turn_log,
            )
            await message.edit(embed=embed)
            await asyncio.sleep(1.2)

        final_embed = build_duel_result_embed(
            challenger_name=challenger_name,
            target_name=target_name,
            result=result,
            challenger_won=outcome.challenger_won,
            swapped=outcome.swapped,
            challenger_old_position=outcome.challenger_old_position,
            target_old_position=outcome.target_old_position,
            challenger_new_position=outcome.challenger_new_position,
            target_new_position=outcome.target_new_position,
        )
        await message.edit(embed=final_embed)

    @app_commands.command(
        name="affinites",
        description="Voir vos affinités élémentaires et votre progression d'essences",
    )
    @app_commands.describe(target="Joueur dont afficher les affinités (par défaut : vous)")
    async def affinities_cmd(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        from app.infrastructure.db.repositories.element_affinity_repository import (
            ElementAffinityRepository,
        )
        from app.infrastructure.db.repositories.element_essence_repository import (
            ElementEssenceRepository,
        )
        from app.bot.embeds.player_embeds import build_affinities_embed
        from app.bot.views.seer_view import SeerButton
        from app.domain.services.element_talent_service import paper_price
        from app.infrastructure.artisans import artisan_loader

        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            affinity_repo = ElementAffinityRepository(session)
            talents = affinity_repo.get_talents(profile.player.id)
            affinities = affinity_repo.get_affinities(profile.player.id)
            revealed = affinity_repo.revealed_elements(profile.player.id)
            essences = ElementEssenceRepository(session).get_essences(profile.player.id)
            player_id = profile.player.id

        # Rendu Pillow ≈ quelques centaines de ms : on prend la main d'abord.
        await interaction.response.defer()

        is_self = target_member.id == interaction.user.id
        next_price = paper_price(
            len(revealed), artisan_loader.get_seer().reading_prices,
        )
        view = None
        if is_self and next_price is not None:
            view = discord.ui.View(timeout=300)
            view.add_item(SeerButton(
                get_db_session, player_id, next_price,
                owner_discord_id=interaction.user.id,
            ))

        try:
            from app.bot.rendering.affinities_image import (
                build_affinity_cards,
                compose_affinities_image,
            )
            from app.shared.paths import GENERATED_PROFILES_DIR

            GENERATED_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"affinities_{player_id}.png"
            path = GENERATED_PROFILES_DIR / filename
            await asyncio.to_thread(
                compose_affinities_image,
                str(path),
                display_name=target_member.display_name,
                cards=build_affinity_cards(affinities, essences, talents, revealed),
                is_self=is_self,
                next_paper_price=next_price,
                seed=player_id,
            )
            embed = discord.Embed(color=discord.Color.purple())
            embed.set_image(url=f"attachment://{filename}")
            kwargs = {"embed": embed, "file": discord.File(str(path), filename=filename)}
        except Exception:
            logging.getLogger(__name__).exception(
                "Rendu de /affinites en échec, repli sur l'embed texte"
            )
            kwargs = {"embed": build_affinities_embed(
                display_name=target_member.display_name,
                affinities=affinities,
                essences=essences,
                is_self=is_self,
                talents=talents,
                revealed=revealed,
                next_paper_price=next_price,
            )}
        if view is not None:
            kwargs["view"] = view
        await interaction.followup.send(**kwargs)

    # ------------------------------------------------------------------
    # Le craft et la forge ont quitté ce cog : ils passent désormais par
    # les PNJ (`/forgeron`, `/artisan`) — cf. artisan_cog. Fabriquer coûte
    # maintenant de l'or et prend du temps, ce qu'une commande directe ne
    # savait pas exprimer.
    # ------------------------------------------------------------------


    @app_commands.command(
        name="payer",
        description="Envoyer de l'or à un autre joueur",
    )
    @app_commands.describe(
        target="Joueur destinataire",
        amount="Montant à envoyer (>= 1)",
    )
    async def pay(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000_000],
    ) -> None:
        if target.bot:
            await interaction.response.send_message(
                "❌ Vous ne pouvez pas envoyer d'or à un bot.",
                ephemeral=True,
            )
            return

        with get_db_session() as session:
            use_case = TransferGoldUseCase(PlayerRepository(session))
            result = use_case.execute(
                sender_discord_id=interaction.user.id,
                sender_username=interaction.user.name,
                sender_display_name=interaction.user.display_name,
                receiver_discord_id=target.id,
                receiver_display_name=target.display_name,
                amount=amount,
            )

        if not result.success:
            await interaction.response.send_message(result.message, ephemeral=True)
            return

        await interaction.response.send_message(
            f"💸 {interaction.user.mention} a envoyé **{amount}** or à {target.mention}.\n"
            f"_Votre solde : {result.sender_balance_after} or._"
        )

    @app_commands.command(
        name="utiliser",
        description="Utiliser un consommable de votre inventaire (potion, etc.)",
    )
    @app_commands.describe(item_code="Code du consommable (autocomplete sur votre inventaire)")
    async def use(self, interaction: discord.Interaction, item_code: str) -> None:
        await interaction.response.defer(ephemeral=True)
        with get_db_session() as session:
            use_case = UseConsumableUseCase(
                player_repository=PlayerRepository(session),
                item_repository=ItemRepository(session),
                inventory_repository=InventoryRepository(session),
                equipment_repository=EquipmentRepository(session),
                skill_allocation_repository=PlayerSkillAllocationRepository(session),
                health_repository=PlayerHealthRepository(session),
                stats_service=StatsService(),
            )
            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
                item_code=item_code,
            )
        await interaction.followup.send(result.message, ephemeral=True)

    @use.autocomplete("item_code")
    async def use_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete sur les consommables actuellement en inventaire."""
        with get_db_session() as session:
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                return []
            inventory = InventoryRepository(session).list_by_player_id(profile.player.id)
        current_lower = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for inv_item in inventory:
            item = inv_item.item_definition
            if item.category != "consumable":
                continue
            if (
                current_lower in item.code.lower()
                or current_lower in item.name.lower()
            ):
                choices.append(
                    app_commands.Choice(
                        name=f"{item.name} (×{inv_item.quantity})",
                        value=item.code,
                    )
                )
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(
        name="cd",
        description="Voir les cooldowns d'un joueur (daily, world boss, etc.)",
    )
    @app_commands.describe(target="Joueur ciblé (par défaut : vous)")
    async def cd(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        from datetime import datetime, UTC

        # Labels lisibles pour chaque action_key connue. Si l'action_key
        # n'est pas mappée, on l'affiche brut (utile pour debug).
        ACTION_LABELS: dict[str, str] = {
            "daily":              "🌅 Récompense quotidienne (/daily)",
            "world_boss_fight":   "👑 Combat du world boss",
            "skill_tree_reset":   "🌳 Reset de l'arbre de compétences",
            "rank_trial":         "🎖️ Épreuve de rang",
        }
        # Cooldowns trop courts pour être pertinents dans cet affichage.
        HIDDEN_COOLDOWNS = {"duel_challenge"}

        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            cooldowns = CooldownRepository(session).list_for_player(
                profile.player.id,
            )
            from app.application.use_cases.tower_tickets import TowerTicketsUseCase

            tickets = TowerTicketsUseCase(session).status(profile.player.id)

        now = datetime.now(UTC)
        ticket_line = (
            f"🎟️ Tour solo : **{tickets.available}/{tickets.allowance}** ticket(s) "
            f"aujourd'hui" + (" (bonus compris)" if tickets.has_bonus else "")
            + " — non cumulables, renouvelés à minuit (heure de Paris)"
        )
        # On garde uniquement les cooldowns encore actifs et non cachés
        active: list[tuple[str, datetime]] = []
        for cd in cooldowns:
            if cd.action_key in HIDDEN_COOLDOWNS:
                continue
            if cd.next_available_at is None:
                continue
            next_at = cd.next_available_at
            if next_at.tzinfo is None:
                next_at = next_at.replace(tzinfo=UTC)
            if next_at <= now:
                continue
            active.append((cd.action_key, next_at))

        is_self = target_member.id == interaction.user.id
        owner = "Vos" if is_self else f"Les"
        suffix = "" if is_self else f" de {target_member.display_name}"
        title = f"⏳ {owner} cooldowns{suffix}"

        embed = discord.Embed(
            title=title,
            color=discord.Color.blurple(),
        )

        if not active:
            embed.description = (
                "✅ Aucun cooldown en cours — tout est disponible !\n\n" + ticket_line
            )
            await interaction.response.send_message(embed=embed)
            return

        # Sort by next_available (le plus proche en premier)
        active.sort(key=lambda x: x[1])
        lines: list[str] = []
        for action_key, next_at in active:
            label = ACTION_LABELS.get(action_key, f"`{action_key}`")
            ts = int(next_at.timestamp())
            lines.append(f"{label} — <t:{ts}:R> (<t:{ts}:f>)")
        embed.description = "\n".join(lines) + "\n\n" + ticket_line
        embed.set_footer(text=f"{len(active)} cooldown(s) actif(s)")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="or",
        description="Voir votre or (ou celui d'un autre joueur)",
    )
    @app_commands.describe(target="Joueur ciblé (par défaut : vous)")
    async def gold(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        with get_db_session() as session:
            profile, target_member = self._resolve_profile(interaction, target, session)
            if profile is None:
                await self._send_no_profile_error(interaction, target_member)
                return

            gold_amount = profile.resources.gold
            career_gold = 0
            try:
                career = PlayerCareerStatsRepository(session).get_or_create(
                    profile.player.id
                )
                career_gold = int(getattr(career, "gold_earned_total", 0) or 0)
            except Exception:
                career_gold = 0

        is_self = target_member.id == interaction.user.id
        title = "💰 Votre bourse" if is_self else f"💰 Bourse de {target_member.display_name}"

        embed = discord.Embed(
            title=title,
            color=discord.Color.gold(),
        )
        embed.set_thumbnail(url=target_member.display_avatar.url)
        embed.add_field(
            name="Or actuel",
            value=f"🪙 **{_format_int(gold_amount)}**",
            inline=False,
        )
        if career_gold > 0:
            embed.add_field(
                name="Or amassé (carrière)",
                value=f"📊 {_format_int(career_gold)}",
                inline=False,
            )
        embed.set_footer(text=f"Joueur : {target_member.display_name}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Récupérer votre récompense quotidienne")
    async def daily(self, interaction: discord.Interaction) -> None:
        with get_db_session() as session:
            player_repository = PlayerRepository(session)
            cooldown_repository = CooldownRepository(session)

            use_case = ClaimDailyRewardUseCase(
                player_repository=player_repository,
                cooldown_repository=cooldown_repository,
                cooldown_service=CooldownService(),
                career_stats_repository=PlayerCareerStatsRepository(session),
            )

            result = use_case.execute(
                discord_id=interaction.user.id,
                username=interaction.user.name,
                display_name=interaction.user.display_name,
            )

        if result.success:
            embed = build_daily_success_embed(
                streak=result.streak,
                gold_gained=result.gold_gained,
                bonus_items=result.bonus_items,
                streak_bonus_pct=result.streak_bonus_pct,
                days_missed=result.days_missed,
                streak_before_absence=result.streak_before_absence,
                titles_unlocked=result.titles_unlocked,
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = build_daily_cooldown_embed(
                streak=result.streak,
                next_available_at=result.next_available_at,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # NOTE : /gather retiré (juin 2026). Le système de métiers sera retravaillé
    # sérieusement plus tard (GatherResourceUseCase conservé mais non câblé).

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlayerCog(bot))