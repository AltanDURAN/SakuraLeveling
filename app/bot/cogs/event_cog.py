"""Cog des événements non-combat (coffre au trésor, + petite fille / forge en
Lot 2/3).

Orchestrateur de spawn (`spawn_loop`, toutes les 10 min) : pour chaque type
activé dans `events.json`, tire un spawn selon sa cadence, en respectant :
  1. au moins 1h entre deux spawns (tous types confondus) ;
  2. un espacement propre au type ;
  3. un seul événement ACTIF par type à la fois.
Boucle de résolution (`resolve_loop`, 1 min) : résout les événements à échéance
(Lot 2/3) et purge les effets temporaires expirés.

Vues PERSISTANTES (custom_id stables, ré-enregistrées au boot) → les clics
survivent à un reboot du bot.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta, UTC

import discord
from discord import app_commands
from discord.ext import commands, tasks

from app.application.services.player_stats_resolver import resolve_player_stats
from app.domain.services.chest_loot_service import ChestLootService
from app.domain.services.forge_service import ForgeService
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.domain.services.little_girl_service import (
    CHOICE_HELP,
    CHOICE_IGNORE,
    LittleGirlConfig,
    LittleGirlService,
)
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.event_repository import (
    EventRepository,
    GLOBAL_KEY,
)
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_health_repository import (
    PlayerHealthRepository,
)
from app.infrastructure.db.repositories.player_item_level_repository import (
    PlayerItemLevelRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_status_effect_repository import (
    PlayerStatusEffectRepository,
)
from app.infrastructure.db.repositories.player_title_repository import (
    PlayerTitleRepository,
)
from app.infrastructure.db.session import get_db_session
from app.infrastructure.events import event_config_loader as cfg
from app.shared.formatters import format_int
from app.shared.paths import EVENTS_ASSETS_DIR

_logger = logging.getLogger(__name__)

_SPAWN_LOOP_MINUTES = 10


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _event_channel(bot: commands.Bot):
    return bot.get_channel(settings.event_channel_id)


def _image_file(image_name: str) -> discord.File | None:
    if not image_name:
        return None
    path = EVENTS_ASSETS_DIR / image_name
    if not path.exists():
        return None
    return discord.File(str(path), filename=path.name)


# --------------------------------------------------------------------------
# Vue Coffre : premier qui clique gagne
# --------------------------------------------------------------------------
class ChestView(discord.ui.View):
    def __init__(self, cog: "EventCog | None" = None) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    def _resolve_cog(self, interaction: discord.Interaction) -> "EventCog | None":
        return self.cog or interaction.client.get_cog("EventCog")

    @discord.ui.button(
        label="Ouvrir le coffre",
        style=discord.ButtonStyle.success,
        emoji="🗝️",
        custom_id="event_chest:open",
    )
    async def open_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        cog = self._resolve_cog(interaction)
        if cog is None:
            await interaction.followup.send("Indisponible.", ephemeral=True)
            return
        await cog.handle_chest_open(interaction)


class LittleGirlView(discord.ui.View):
    def __init__(self, cog: "EventCog | None" = None) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    def _resolve_cog(self, interaction: discord.Interaction) -> "EventCog | None":
        return self.cog or interaction.client.get_cog("EventCog")

    @discord.ui.button(
        label="Aider la petite fille",
        style=discord.ButtonStyle.success,
        emoji="🤝",
        custom_id="event_girl:help",
    )
    async def help_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        cog = self._resolve_cog(interaction)
        if cog:
            await cog.handle_girl_choice(interaction, CHOICE_HELP)

    @discord.ui.button(
        label="Ignorer",
        style=discord.ButtonStyle.secondary,
        emoji="🚶",
        custom_id="event_girl:ignore",
    )
    async def ignore_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        cog = self._resolve_cog(interaction)
        if cog:
            await cog.handle_girl_choice(interaction, CHOICE_IGNORE)


class ForgeView(discord.ui.View):
    def __init__(self, cog: "EventCog | None" = None) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    def _resolve_cog(self, interaction: discord.Interaction) -> "EventCog | None":
        return self.cog or interaction.client.get_cog("EventCog")

    @discord.ui.button(
        label="Forger un équipement",
        style=discord.ButtonStyle.primary,
        emoji="🔨",
        custom_id="event_forge:open",
    )
    async def forge_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        cog = self._resolve_cog(interaction)
        if cog:
            await cog.handle_forge_open(interaction)


class ForgeSelect(discord.ui.Select):
    def __init__(self, cog: "EventCog", event_id: int, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choisis l'équipement à forger…", options=options)
        self.cog = cog
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.cog.handle_forge_pick(interaction, self.event_id, int(self.values[0]))


class ForgeSelectView(discord.ui.View):
    """Vue éphémère (non persistante) : sélection de l'équipement à forger."""

    def __init__(self, cog: "EventCog", event_id: int, options: list[discord.SelectOption]):
        super().__init__(timeout=120)
        self.add_item(ForgeSelect(cog, event_id, options))


class EventCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.add_view(ChestView(self))
        self.bot.add_view(LittleGirlView(self))
        self.bot.add_view(ForgeView(self))
        self.spawn_loop.start()
        self.resolve_loop.start()

    def cog_unload(self) -> None:
        self.spawn_loop.cancel()
        self.resolve_loop.cancel()

    # ---------------- boucles ----------------

    @tasks.loop(minutes=_SPAWN_LOOP_MINUTES)
    async def spawn_loop(self) -> None:
        try:
            cfg.clear_cache()
            for event_type in cfg.EVENT_TYPES:
                if self._should_spawn(event_type):
                    await self.spawn_event(event_type)
                    # un seul spawn par tick (respecte l'espacement global 1h)
                    break
        except Exception:  # noqa: BLE001
            _logger.exception("event spawn_loop failed")

    @spawn_loop.before_loop
    async def _before_spawn(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def resolve_loop(self) -> None:
        try:
            with get_db_session() as session:
                PlayerStatusEffectRepository(session).purge_expired()
                session.commit()
            # Événements à échéance (petite fille = résolution à 5 min).
            with get_db_session() as session:
                due_ids = [
                    (ev.id, ev.event_type)
                    for ev in EventRepository(session).list_due()
                ]
            for event_id, event_type in due_ids:
                if event_type == "little_girl":
                    await self._resolve_little_girl(event_id)
                elif event_type == "sacred_forge":
                    await self._close_sacred_forge(event_id)
        except Exception:  # noqa: BLE001
            _logger.exception("event resolve_loop failed")

    @resolve_loop.before_loop
    async def _before_resolve(self) -> None:
        await self.bot.wait_until_ready()

    # ---------------- décision de spawn ----------------

    def _should_spawn(self, event_type: str) -> bool:
        if not cfg.is_enabled(event_type):
            return False
        per_hour = cfg.cadence_per_hour(event_type)
        if per_hour <= 0:
            return False
        now = _now()
        with get_db_session() as session:
            repo = EventRepository(session)
            if repo.get_active_by_type(event_type) is not None:
                return False
            last_global = repo.get_last_spawn(GLOBAL_KEY)
            if last_global and (now - last_global) < timedelta(hours=1):
                return False
            last_type = repo.get_last_spawn(event_type)
            # espacement mini propre au type = moitié de l'intervalle moyen
            min_type_gap = timedelta(hours=(0.5 / per_hour))
            if last_type and (now - last_type) < min_type_gap:
                return False
        prob = per_hour * (_SPAWN_LOOP_MINUTES / 60.0)
        return random.random() < prob

    # ---------------- spawn ----------------

    async def spawn_event(self, event_type: str) -> discord.Message | None:
        """Fait apparaître un événement. Lot 1 : seul `chest` est implémenté."""
        if event_type == "chest":
            return await self._spawn_chest()
        if event_type == "little_girl":
            return await self._spawn_little_girl()
        if event_type == "sacred_forge":
            return await self._spawn_sacred_forge()
        _logger.info("spawn_event: type '%s' non encore implémenté", event_type)
        return None

    async def _spawn_chest(self) -> discord.Message | None:
        channel = _event_channel(self.bot)
        if channel is None:
            _logger.warning("event channel introuvable (%s)", settings.event_channel_id)
            return None
        config = cfg.get_config("chest")
        with get_db_session() as session:
            repo = EventRepository(session)
            ev = repo.create("chest", channel.id)
            repo.touch_spawn("chest")
            session.commit()
            event_id = ev.id

        embed = discord.Embed(
            title="🎁 Un coffre au trésor apparaît !",
            description=(
                "Un coffre mystérieux se matérialise… **Le premier qui l'ouvre "
                "rafle le butin !** Serez-vous le plus rapide ?"
            ),
            color=discord.Color.gold(),
        )
        file = _image_file(config.get("image", ""))
        if file is not None:
            embed.set_image(url=f"attachment://{file.filename}")
        kwargs = {"embed": embed, "view": ChestView(self)}
        if file is not None:
            kwargs["file"] = file
        message = await channel.send(**kwargs)
        with get_db_session() as session:
            EventRepository(session).set_message_id(event_id, message.id)
            session.commit()
        return message

    # ---------------- interaction coffre ----------------

    async def handle_chest_open(self, interaction: discord.Interaction) -> None:
        message = interaction.message
        with get_db_session() as session:
            repo = EventRepository(session)
            player_repo = PlayerRepository(session)
            profile = player_repo.get_by_discord_id(interaction.user.id)
            if profile is None:
                await interaction.followup.send(
                    "Crée d'abord ton profil avec `/profil`.", ephemeral=True
                )
                return

            ev = repo.get_active_by_type("chest")
            if ev is None or (message and ev.message_id != message.id):
                await interaction.followup.send(
                    "⏳ Trop tard — ce coffre a déjà été ouvert !", ephemeral=True
                )
                return

            won = repo.claim_chest_winner(ev.id, profile.player.id)
            if not won:
                await interaction.followup.send(
                    "⏳ Trop tard — quelqu'un a été plus rapide !", ephemeral=True
                )
                return

            # Gagnant : on roule le loot, on le scale selon son niveau, on attribue.
            config = cfg.get_config("chest")
            loot_service = ChestLootService()
            entries = loot_service.parse_entries(config.get("loot", []))
            result = loot_service.roll(entries)
            result = loot_service.scale_for_level(
                result,
                profile.progression.level,
                float(config.get("level_scaling_pct", 0)),
            )
            reward_text = self._grant_chest_reward(session, profile.player.id, result)
            session.commit()

        winner_mention = interaction.user.mention
        await interaction.followup.send(
            f"🎉 Tu as ouvert le coffre en premier ! Tu remportes : **{reward_text}**",
            ephemeral=True,
        )
        # Édite le message public : coffre ouvert, plus de bouton.
        try:
            done = discord.Embed(
                title="🎁 Coffre ouvert !",
                description=f"{winner_mention} a été le plus rapide et remporte **{reward_text}** !",
                color=discord.Color.dark_gold(),
            )
            if message:
                await message.edit(embed=done, view=None, attachments=message.attachments)
        except Exception:  # noqa: BLE001
            _logger.exception("chest message edit failed")

    def _grant_chest_reward(self, session, player_id: int, result) -> str:
        if result.kind == "gold" and result.gold_amount > 0:
            PlayerRepository(session).add_gold(player_id, result.gold_amount)
            return f"{format_int(result.gold_amount)} or"
        if result.kind == "item" and result.item_code and result.quantity > 0:
            item = ItemRepository(session).get_by_code(result.item_code)
            if item is not None:
                InventoryRepository(session).add_item(player_id, item.id, result.quantity)
                return f"{result.quantity}× {item.name}"
        return "rien du tout… 😞 (le coffre était vide)"

    # ---------------- petite fille ----------------

    async def _spawn_little_girl(self) -> discord.Message | None:
        channel = _event_channel(self.bot)
        if channel is None:
            _logger.warning("event channel introuvable (%s)", settings.event_channel_id)
            return None
        config = cfg.get_config("little_girl")
        minutes = max(1, int(config.get("resolve_after_minutes", 5)))
        expires_at = _now() + timedelta(minutes=minutes)
        with get_db_session() as session:
            repo = EventRepository(session)
            ev = repo.create("little_girl", channel.id, expires_at=expires_at)
            repo.touch_spawn("little_girl")
            session.commit()
            event_id = ev.id

        embed = discord.Embed(
            title="👧 Une petite fille apparaît…",
            description=(
                "Une petite fille en pleurs surgit au détour du chemin et implore "
                "de l'aide. Mais dans ces terres maudites, tout n'est pas ce qu'il "
                "paraît… **Aider** ou **ignorer** ?\n\n"
                f"⏳ Le sort de chacun sera scellé dans **{minutes} minutes**. "
                "Tout le monde peut participer."
            ),
            color=discord.Color.purple(),
        )
        file = _image_file(config.get("image", ""))
        if file is not None:
            embed.set_image(url=f"attachment://{file.filename}")
        kwargs = {"embed": embed, "view": LittleGirlView(self)}
        if file is not None:
            kwargs["file"] = file
        message = await channel.send(**kwargs)
        with get_db_session() as session:
            EventRepository(session).set_message_id(event_id, message.id)
            session.commit()
        return message

    async def handle_girl_choice(
        self, interaction: discord.Interaction, choice: str
    ) -> None:
        message = interaction.message
        with get_db_session() as session:
            repo = EventRepository(session)
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                await interaction.followup.send(
                    "Crée d'abord ton profil avec `/profil`.", ephemeral=True
                )
                return
            ev = repo.get_active_by_type("little_girl")
            if ev is None or (message and ev.message_id != message.id):
                await interaction.followup.send(
                    "⏳ Trop tard — le sort de la petite fille est déjà scellé.",
                    ephemeral=True,
                )
                return
            repo.upsert_participation(ev.id, profile.player.id, choice=choice)
            session.commit()
        label = "🤝 aider" if choice == CHOICE_HELP else "🚶 ignorer"
        await interaction.followup.send(
            f"Ton choix est enregistré : **{label}**. Tu peux encore le changer "
            "tant que le temps n'est pas écoulé. Le résultat tombera à la fin.",
            ephemeral=True,
        )

    async def _resolve_little_girl(self, event_id: int) -> None:
        girl_service = LittleGirlService()
        config = cfg.get_config("little_girl")
        gcfg = LittleGirlConfig(
            trap_probability=int(config.get("trap_probability", 50)),
            gold_loss_per_level=int(config.get("gold_loss_per_level", 10)),
            buff_multiplier=float(config.get("buff_multiplier", 1.1)),
            buff_duration_hours=int(config.get("buff_duration_hours", 3)),
            debuff_multiplier=float(config.get("debuff_multiplier", 0.5)),
            debuff_duration_hours=int(config.get("debuff_duration_hours", 3)),
            title_chance=int(config.get("title_chance", 10)),
        )
        lines: list[str] = []
        channel_id = None
        message_id = None
        with get_db_session() as session:
            repo = EventRepository(session)
            ev = repo.get_by_id(event_id)
            if ev is None or ev.status != "active":
                return
            channel_id, message_id = ev.channel_id, ev.message_id
            # Marque résolu tout de suite (idempotence si le loop repasse).
            repo.set_status(event_id, "resolved")
            session.commit()

            is_trap = girl_service.roll_is_trap(gcfg)
            participations = repo.list_participations(event_id)
            title_repo = PlayerTitleRepository(session)
            for part in participations:
                profile = PlayerRepository(session).get_profile_by_player_id(
                    part.player_id
                )
                if profile is None:
                    continue
                has_title = title_repo.has_title(part.player_id, "ma_survie_avant_tout")
                consequence = girl_service.resolve(
                    choice=part.choice,
                    is_trap=is_trap,
                    player_level=profile.progression.level,
                    config=gcfg,
                    has_title=has_title,
                )
                self._apply_girl_consequence(session, profile, consequence)
                tag = self._girl_outcome_tag(consequence, part.choice)
                lines.append(f"<@{profile.player.discord_id}> · {tag}")
            session.commit()

        await self._edit_girl_result(channel_id, message_id, is_trap, lines)

    def _girl_outcome_tag(self, consequence, choice: str) -> str:
        if consequence.grant_title:
            return "🛡️ **titre Ma survie avant tout !**"
        if consequence.buff_multiplier > 0:
            return f"😇 buff +{round((consequence.buff_multiplier - 1) * 100)}% ({consequence.buff_hours}h)"
        if consequence.debuff_multiplier > 0:
            return f"💔 debuff ÷{round(1 / consequence.debuff_multiplier) if consequence.debuff_multiplier else 2} ({consequence.debuff_hours}h)"
        if consequence.gold_loss > 0 or consequence.halve_hp:
            return f"😈 −{format_int(consequence.gold_loss)} or & moitié PV"
        return "🚶 rien"

    def _apply_girl_consequence(self, session, profile, consequence) -> None:
        player_id = profile.player.id
        if consequence.buff_multiplier > 0:
            PlayerStatusEffectRepository(session).add(
                player_id, "little_girl_buff", consequence.buff_multiplier,
                consequence.buff_hours * 3600,
            )
        if consequence.debuff_multiplier > 0:
            PlayerStatusEffectRepository(session).add(
                player_id, "little_girl_debuff", consequence.debuff_multiplier,
                consequence.debuff_hours * 3600,
            )
        if consequence.gold_loss > 0:
            PlayerRepository(session).add_gold(player_id, -consequence.gold_loss)
        if consequence.halve_hp:
            self._halve_current_hp(session, profile)
        if consequence.grant_title:
            PlayerTitleRepository(session).unlock(player_id, consequence.grant_title)

    def _halve_current_hp(self, session, profile) -> None:
        """Divise par 2 les PV COURANTS (régénérés d'abord pour être juste)."""
        equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)
        active_class = ClassRepository(session).get_current_class_for_player(
            profile.player.id
        )
        stats = resolve_player_stats(session, profile, equipped, active_class)
        health_repo = PlayerHealthRepository(session)
        state = health_repo.get_or_create(profile.player.id, default_current_hp=stats.max_hp)
        from datetime import datetime, UTC

        current = HealthRegenerationService().apply_out_of_combat_regeneration(
            current_hp=state.current_hp,
            max_hp=stats.max_hp,
            hp_regeneration=stats.hp_regeneration,
            last_updated_at=state.updated_at,
            now=datetime.now(UTC),
        )
        health_repo.update_current_hp(profile.player.id, max(1, current // 2))

    async def _edit_girl_result(
        self, channel_id, message_id, is_trap: bool, lines: list[str]
    ) -> None:
        if not channel_id or not message_id:
            return
        try:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                return
            message = await channel.fetch_message(message_id)
            if is_trap:
                title = "😈 C'était un piège !"
                desc = (
                    "La « petite fille » était un **monstre déguisé** venu piéger "
                    "les âmes charitables. Ceux qui l'ont aidée l'ont payé cher ; "
                    "ceux qui l'ont ignorée ont eu le nez creux."
                )
                color = discord.Color.dark_red()
            else:
                title = "😇 C'était une vraie petite fille."
                desc = (
                    "Une enfant réellement perdue. Ceux qui l'ont aidée sont "
                    "bénis ; ceux qui l'ont ignorée le regrettent amèrement."
                )
                color = discord.Color.green()
            embed = discord.Embed(title=title, description=desc, color=color)
            if lines:
                embed.add_field(
                    name="Sort des participants",
                    value="\n".join(lines[:20]),
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Sort des participants",
                    value="Personne n'a participé…",
                    inline=False,
                )
            await message.edit(embed=embed, view=None, attachments=message.attachments)
        except Exception:  # noqa: BLE001
            _logger.exception("little girl result edit failed")

    # ---------------- forge sacrée ----------------

    async def _spawn_sacred_forge(self) -> discord.Message | None:
        channel = _event_channel(self.bot)
        if channel is None:
            _logger.warning("event channel introuvable (%s)", settings.event_channel_id)
            return None
        config = cfg.get_config("sacred_forge")
        minutes = max(1, int(config.get("window_minutes", 5)))
        max_level = int(config.get("max_level", 10))
        expires_at = _now() + timedelta(minutes=minutes)
        with get_db_session() as session:
            repo = EventRepository(session)
            ev = repo.create("sacred_forge", channel.id, expires_at=expires_at)
            repo.touch_spawn("sacred_forge")
            session.commit()
            event_id = ev.id

        embed = discord.Embed(
            title="🔨 La forge sacrée s'embrase !",
            description=(
                "Une forge légendaire apparaît, brûlant d'une flamme divine. "
                "Pendant **{m} minutes**, chacun peut y **renforcer un seul de ses "
                "équipements** (une seule fois). Chaque niveau ajoute les stats de "
                "base de la pièce — jusqu'au **niveau {lv}**.\n\nClique **Forger** "
                "et choisis ta pièce !"
            ).format(m=minutes, lv=max_level),
            color=discord.Color.orange(),
        )
        file = _image_file(config.get("image", ""))
        if file is not None:
            embed.set_image(url=f"attachment://{file.filename}")
        kwargs = {"embed": embed, "view": ForgeView(self)}
        if file is not None:
            kwargs["file"] = file
        message = await channel.send(**kwargs)
        with get_db_session() as session:
            EventRepository(session).set_message_id(event_id, message.id)
            session.commit()
        return message

    async def handle_forge_open(self, interaction: discord.Interaction) -> None:
        message = interaction.message
        with get_db_session() as session:
            repo = EventRepository(session)
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                await interaction.followup.send(
                    "Crée d'abord ton profil avec `/profil`.", ephemeral=True
                )
                return
            ev = repo.get_active_by_type("sacred_forge")
            if ev is None or (message and ev.message_id != message.id):
                await interaction.followup.send(
                    "🔥 La forge s'est éteinte — trop tard !", ephemeral=True
                )
                return
            if repo.get_participation(ev.id, profile.player.id) is not None:
                await interaction.followup.send(
                    "Tu as déjà utilisé la forge pour cet événement. Une seule "
                    "pièce par forge !", ephemeral=True
                )
                return
            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)
            levels = PlayerItemLevelRepository(session).get_levels_for_player(
                profile.player.id
            )
            max_level = int(cfg.get_config("sacred_forge").get("max_level", 10))
            options: list[discord.SelectOption] = []
            seen: set[int] = set()
            for eq in equipped:
                idef = eq.item_definition
                if idef.id in seen:
                    continue
                seen.add(idef.id)
                lvl = levels.get(idef.id, 0)
                if lvl >= max_level:
                    label = f"{idef.name} (niv MAX)"
                else:
                    label = f"{idef.name} (niv {lvl} → {lvl + 1})"
                options.append(
                    discord.SelectOption(label=label[:100], value=str(idef.id))
                )
            if not options:
                await interaction.followup.send(
                    "Tu n'as aucun équipement à forger.", ephemeral=True
                )
                return
            event_id = ev.id
        await interaction.followup.send(
            "Choisis l'équipement à renforcer :",
            view=ForgeSelectView(self, event_id, options[:25]),
            ephemeral=True,
        )

    async def handle_forge_pick(
        self, interaction: discord.Interaction, event_id: int, item_definition_id: int
    ) -> None:
        with get_db_session() as session:
            repo = EventRepository(session)
            profile = PlayerRepository(session).get_by_discord_id(interaction.user.id)
            if profile is None:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return
            ev = repo.get_by_id(event_id)
            if ev is None or ev.status != "active":
                await interaction.followup.send(
                    "🔥 La forge s'est éteinte entre-temps !", ephemeral=True
                )
                return
            if repo.get_participation(event_id, profile.player.id) is not None:
                await interaction.followup.send(
                    "Tu as déjà forgé une pièce pour cet événement.", ephemeral=True
                )
                return
            # Vérifie que la pièce est bien équipée par le joueur.
            equipped = EquipmentRepository(session).list_by_player_id(profile.player.id)
            item = next(
                (e.item_definition for e in equipped
                 if e.item_definition.id == item_definition_id),
                None,
            )
            if item is None:
                await interaction.followup.send(
                    "Cet équipement n'est plus équipé.", ephemeral=True
                )
                return
            max_level = int(cfg.get_config("sacred_forge").get("max_level", 10))
            level_repo = PlayerItemLevelRepository(session)
            new_level = level_repo.increment(
                profile.player.id, item_definition_id, max_level
            )
            if new_level == -1:
                await interaction.followup.send(
                    f"**{item.name}** est déjà au niveau maximum ({max_level}).",
                    ephemeral=True,
                )
                return
            # Enregistre la participation (une seule forge par joueur/event).
            repo.upsert_participation(
                event_id, profile.player.id, choice=str(item_definition_id)
            )
            session.commit()
            gains = ForgeService().gain_per_level(item.stat_bonuses)
        gain_txt = ", ".join(f"+{v} {k}" for k, v in gains.items()) or "ses stats de base"
        await interaction.followup.send(
            f"🔨 **{item.name}** forgé au **niveau {new_level}** ! "
            f"(gain de {gain_txt}). Vérifie avec `/equipement`.",
            ephemeral=True,
        )

    async def _close_sacred_forge(self, event_id: int) -> None:
        channel_id = None
        message_id = None
        forged_count = 0
        with get_db_session() as session:
            repo = EventRepository(session)
            ev = repo.get_by_id(event_id)
            if ev is None or ev.status != "active":
                return
            channel_id, message_id = ev.channel_id, ev.message_id
            forged_count = len(repo.list_participations(event_id))
            repo.set_status(event_id, "resolved")
            session.commit()
        if not channel_id or not message_id:
            return
        try:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                return
            message = await channel.fetch_message(message_id)
            embed = discord.Embed(
                title="🔥 La forge sacrée s'est éteinte.",
                description=(
                    f"La flamme divine s'éteint. **{forged_count}** aventurier(s) "
                    "ont renforcé un équipement."
                ),
                color=discord.Color.dark_orange(),
            )
            await message.edit(embed=embed, view=None, attachments=message.attachments)
        except Exception:  # noqa: BLE001
            _logger.exception("sacred forge close edit failed")

    # ---------------- commande admin de test ----------------

    @app_commands.command(
        name="spawn_event",
        description="[Admin] Fait spawn immédiatement un événement.",
    )
    @app_commands.describe(event_type="Type d'événement à faire apparaître")
    @app_commands.choices(
        event_type=[
            app_commands.Choice(name="Coffre au trésor", value="chest"),
            app_commands.Choice(name="La petite fille", value="little_girl"),
            app_commands.Choice(name="La forge sacrée", value="sacred_forge"),
        ]
    )
    async def spawn_event_cmd(
        self, interaction: discord.Interaction, event_type: app_commands.Choice[str]
    ) -> None:
        from app.bot.checks.admin_check import is_admin_user

        if not is_admin_user(interaction.user.id):
            await interaction.response.send_message(
                "Réservé aux admins.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        msg = await self.spawn_event(event_type.value)
        if msg is None:
            await interaction.followup.send(
                f"Impossible de spawn `{event_type.value}` "
                "(type non implémenté ou salon introuvable).",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"✅ Événement `{event_type.value}` spawné.", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventCog(bot))
