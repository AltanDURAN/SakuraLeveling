"""Commandes CONSULTATIVES du joueur : `/ping`, `/profil` (bannière PNG),
`/affinites`, `/cd` (temps de recharge + élixirs actifs), `/or`.

Découpé de `player_cog.py` le 26/10/2026 (roadmap N6). `joueur` optionnel :
défaut = soi (profil créé au besoin), sinon lecture seule
(`PlayerLookupMixin._resolve_profile`).
"""

import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, UTC
from app.shared.formatters import format_int as _format_int
from app.bot.embeds.player_embeds import build_player_profile_embed
from app.domain.services.stats_service import StatsService
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.element_affinity_repository import ElementAffinityRepository
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_career_stats_repository import (
    PlayerCareerStatsRepository,
)
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.session import get_db_session
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.infrastructure.db.repositories.player_health_repository import PlayerHealthRepository
from app.domain.services.power_score_service import PowerScoreService
from app.bot.cogs._mixins import BetaChannelOnlyMixin, PlayerLookupMixin


class ProfileCog(PlayerLookupMixin, BetaChannelOnlyMixin, commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
            from app.application.services.combat_passives_resolver import resolve_player_power

            raw_power_score = resolve_player_power(session, profile.player.id, stats)
            formatted_power_score = power_score_service.format_score(raw_power_score)
            rank_label = power_score_service.compute_rank(raw_power_score)

            health_state = player_health_repository.get_or_create(
                player_id=profile.player.id,
                default_current_hp=stats.max_hp,
            )

            now = datetime.now(UTC)
            from app.application.services.status_effect_resolver import resolve_regen_boosts

            regen_boosts = resolve_regen_boosts(session, profile.player.id)
            regenerated_current_hp = HealthRegenerationService().apply_out_of_combat_regeneration(
                current_hp=health_state.current_hp,
                max_hp=stats.max_hp,
                hp_regeneration=stats.hp_regeneration,
                last_updated_at=health_state.updated_at,
                now=now,
                boosts=regen_boosts,
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
                boosts=regen_boosts,
            )
            if regenerated_current_mana != mana_state.current_mana and target is None:
                player_mana_repository.refresh_current_mana(
                    player_id=profile.player.id,
                    new_current_mana=regenerated_current_mana,
                )

            total_kills = kill_repository.get_total_kills(profile.player.id)
            career_stats = career_stats_repository.get_or_create(profile.player.id)

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

            from app.application.services.cosmetic_resolver import worn_cosmetics

            cosmetics_payload = worn_cosmetics(session, profile.player.id)

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
                cosmetics=cosmetics_payload,
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
            active_title=active_title_name,
            affinities=affinities,
        )
        await interaction.followup.send(embed=embed)

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
        HIDDEN_COOLDOWNS: set[str] = set()

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
            from app.application.use_cases.use_consumable import active_elixirs_text
            from app.infrastructure.db.repositories.player_status_effect_repository import (
                PlayerStatusEffectRepository,
            )

            elixirs = PlayerStatusEffectRepository(session).list_active_elixirs(profile.player.id)
            elixir_line = ("\n🧪 Élixirs actifs : " + active_elixirs_text(elixirs)
                           + " — combats de zone et world boss seulement") if elixirs else ""

        now = datetime.now(UTC)
        ticket_line = (
            f"🎟️ Tour solo : **{tickets.available}/{tickets.allowance}** ticket(s) "
            f"aujourd'hui" + (" (bonus compris)" if tickets.has_bonus else "")
            + " — non cumulables, renouvelés à minuit (heure de Paris)"
        ) + elixir_line
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
        owner = "Vos" if is_self else "Les"
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))
