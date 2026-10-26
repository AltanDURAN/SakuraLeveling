"""Use case d'utilisation d'un consommable depuis l'inventaire (`/utiliser`).

Effets (lus dans `item.stat_bonuses`, cf. `alchemy_service`) :
  • `heal_percent` : rend X % des PV max — refusée (non consommée) si les PV
    sont pleins ; la régénération hors combat écoulée est comptée AVANT ;
  • `mana_percent` : même chose pour le mana ;
  • `elixir` : effet temporaire. Un MÊME effet ne se cumule jamais (le
    reboire renouvelle sa durée), des effets différents s'additionnent ;
  • les OUTILS de Sorn (cor de chasse, sceau, parchemin, jeton, sablier),
    cf. `merchant_items` : ce qu'ils demandent au bot (rang Discord,
    invocation d'une élite) passe par `UseContext`.

Sécurité : décrément atomique de l'inventaire ; refus si quantité < 1
ou si l'item n'est pas marqué `category=consumable`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.services.player_stats_resolver import resolve_player_stats
from app.application.services.status_effect_resolver import resolve_regen_boosts
from app.domain.services.alchemy_service import (
    EFFECT_ELIXIR,
    EFFECT_HEAL,
    EFFECT_MANA,
    ELIXIR_LABELS,
    effect_text,
    elixir_of,
)
from app.domain.services.health_regeneration_service import HealthRegenerationService
from app.domain.services.mana_regeneration_service import ManaRegenerationService
from app.domain.services import merchant_items as tools
from app.domain.services.stats_service import StatsService
from app.domain.services.skill_tree_service import SkillTreeService
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_health_repository import (
    PlayerHealthRepository,
)
from app.infrastructure.db.repositories.player_mana_repository import PlayerManaRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.player_status_effect_repository import (
    PlayerStatusEffectRepository,
)
from app.infrastructure.skill_tree.skill_tree_loader import (
    get_definition as get_skill_tree_definition,
)


CONSUMABLE_CATEGORY = "consumable"
EFFECT_HEAL_PERCENT = EFFECT_HEAL   # compat


@dataclass
class UseContext:
    """Ce que seul le bot connaît : le rang porté (rôle Discord) et le moyen
    de faire apparaître une élite — `summon_elite(code du monstre, salon)`
    → (succès, message), branché sur l'EncounterCog."""
    player_rank: str | None = None
    summon_elite: Callable[[str, int], tuple[bool, str]] | None = None


@dataclass
class UseConsumableResult:
    success: bool
    message: str
    item_name: str = ""
    hp_before: int = 0
    hp_after: int = 0
    max_hp: int = 0
    #: Annonce publique à poster dans ce salon (cor de chasse).
    announce_channel_id: int | None = None
    announce: str = ""


class UseConsumableUseCase:
    def __init__(
        self,
        player_repository: PlayerRepository,
        item_repository: ItemRepository,
        inventory_repository: InventoryRepository,
        equipment_repository: EquipmentRepository,
        skill_allocation_repository: PlayerSkillAllocationRepository,
        health_repository: PlayerHealthRepository,
        stats_service: StatsService,
    ) -> None:
        self.player_repository = player_repository
        self.item_repository = item_repository
        self.inventory_repository = inventory_repository
        self.equipment_repository = equipment_repository
        self.skill_allocation_repository = skill_allocation_repository
        self.health_repository = health_repository
        self.stats_service = stats_service

    def execute(
        self,
        discord_id: int,
        username: str,
        display_name: str,
        item_code: str,
        context: UseContext | None = None,
    ) -> UseConsumableResult:
        item = self.item_repository.get_by_code(item_code)
        if item is None:
            return UseConsumableResult(
                success=False, message=f"❌ Item `{item_code}` introuvable."
            )
        if item.category != CONSUMABLE_CATEGORY:
            return UseConsumableResult(
                success=False,
                message=f"❌ **{item.name}** n'est pas un consommable.",
            )

        bonuses = item.stat_bonuses or {}
        effect = bonuses.get("effect")
        if effect not in (EFFECT_HEAL, EFFECT_MANA, EFFECT_ELIXIR, *tools.TOOL_EFFECTS) or (
                effect == EFFECT_ELIXIR and elixir_of(bonuses) is None):
            return UseConsumableResult(
                success=False,
                message=f"❌ Effet de **{item.name}** non géré.",
            )

        profile = self.player_repository.get_or_create_by_discord_id(
            discord_id=discord_id, username=username, display_name=display_name,
        )

        owned = sum(
            i.quantity for i in self.inventory_repository.list_by_player_id(profile.player.id)
            if i.item_definition.id == item.id
        )
        if owned < 1:
            return UseConsumableResult(
                success=False,
                message=f"❌ Vous n'avez pas de **{item.name}** en inventaire.",
                item_name=item.name,
            )

        # PV réels AVANT de consommer quoi que ce soit : max_hp par la chaîne
        # complète (arbre, sets, titres…) et régénération hors combat écoulée
        # depuis la dernière mise à jour. Sans elle, boire une potion après
        # une pause effaçait les PV régénérés entre-temps.
        session = self.equipment_repository.session
        if effect == EFFECT_ELIXIR:
            return self._drink_elixir(session, profile.player.id, item)
        if effect in tools.TOOL_EFFECTS:
            return self._use_tool(session, profile, item, effect, bonuses, context or UseContext())

        equipped = self.equipment_repository.list_by_player_id(profile.player.id)
        stats = resolve_player_stats(
            session,
            profile,
            equipped,
            stats_service=self.stats_service,
        )
        boosts = resolve_regen_boosts(session, profile.player.id)
        if effect == EFFECT_MANA:
            return self._drink_mana(session, profile.player.id, item, stats, boosts)
        max_hp = stats.max_hp
        health_state = self.health_repository.get_or_create(
            profile.player.id, default_current_hp=max_hp
        )
        hp_before = HealthRegenerationService().apply_out_of_combat_regeneration(
            current_hp=health_state.current_hp,
            max_hp=max_hp,
            hp_regeneration=stats.hp_regeneration,
            last_updated_at=health_state.updated_at,
            now=datetime.now(UTC),
            boosts=boosts,
        )

        # PV déjà pleins : on ne gâche pas la potion.
        if hp_before >= max_hp:
            return UseConsumableResult(
                success=False,
                message=(
                    f"💚 Tes PV sont déjà au maximum ({max_hp} / {max_hp}) : "
                    f"**{item.name}** n'a pas été utilisée."
                ),
                item_name=item.name,
                hp_before=hp_before,
                hp_after=hp_before,
                max_hp=max_hp,
            )

        # Décrément atomique : retire 1, refuse si pas en inventaire
        removed = self.inventory_repository.remove_item(
            player_id=profile.player.id, item_definition_id=item.id, quantity=1,
        )
        if not removed:
            return UseConsumableResult(
                success=False,
                message=f"❌ Vous n'avez pas de **{item.name}** en inventaire.",
                item_name=item.name,
            )

        # Application de l'effet
        percent = int(bonuses.get("value", 0))
        heal_amount = round(max_hp * percent / 100)
        hp_after = min(max_hp, hp_before + heal_amount)
        self.health_repository.update_current_hp(profile.player.id, hp_after)

        # NOTE: hook quête on_consumable_used retiré (V2).

        return UseConsumableResult(
            success=True,
            message=(
                f"💚 **{item.name}** utilisé : "
                f"PV {hp_before} → **{hp_after}** / {max_hp} (+{hp_after - hp_before})"
            ),
            item_name=item.name,
            hp_before=hp_before,
            hp_after=hp_after,
            max_hp=max_hp,
        )

    # ---------------------------------------------------------------- mana --
    def _drink_mana(self, session, player_id: int, item, stats, boosts) -> UseConsumableResult:
        mana_repo = PlayerManaRepository(session)
        state = mana_repo.get_or_create(player_id, default_current_mana=stats.mana_max)
        before = ManaRegenerationService().apply_out_of_combat_regeneration(
            current_mana=state.current_mana, mana_max=stats.mana_max,
            mana_regeneration=stats.mana_regeneration, last_updated_at=state.updated_at,
            now=datetime.now(UTC), boosts=boosts,
        )
        if before >= stats.mana_max:
            return UseConsumableResult(
                success=False, item_name=item.name,
                message=(f"💧 Ton mana est déjà au maximum ({stats.mana_max} / {stats.mana_max}) : "
                         f"**{item.name}** n'a pas été utilisée."),
            )
        if not self.inventory_repository.remove_item(player_id, item.id, 1):
            return UseConsumableResult(False, f"❌ Vous n'avez pas de **{item.name}** en inventaire.", item.name)
        after = min(stats.mana_max, before + round(stats.mana_max * int((item.stat_bonuses or {}).get("value", 0)) / 100))
        mana_repo.update_current_mana(player_id, after)
        return UseConsumableResult(
            success=True, item_name=item.name,
            message=f"💧 **{item.name}** utilisée : mana {before} → **{after}** / {stats.mana_max} (+{after - before})",
        )

    # ------------------------------------------------------------- élixirs --
    def _drink_elixir(self, session, player_id: int, item) -> UseConsumableResult:
        elixir = elixir_of(item.stat_bonuses)
        repo = PlayerStatusEffectRepository(session)
        active = repo.list_active_elixirs(player_id).get(elixir.status_kind)
        if active is not None and float(active.multiplier) > elixir.multiplier:
            return UseConsumableResult(
                False, f"🧪 Un élixir plus fort de ce type est déjà actif : **{item.name}** n'a pas été bu.",
                item.name)
        if not self.inventory_repository.remove_item(player_id, item.id, 1, commit=False):
            return UseConsumableResult(False, f"❌ Vous n'avez pas de **{item.name}** en inventaire.", item.name)
        _, renewed = repo.apply_elixir(player_id, item.code, elixir.status_kind, elixir.multiplier,
                                       elixir.minutes * 60)
        session.commit()
        lines = [
            f"🧪 **{item.name}** : {effect_text(item.stat_bonuses)}."
            + (" Il était déjà actif : sa durée repart à zéro (un même effet ne se cumule pas)."
               if renewed else ""),
        ]
        if elixir.kind != "regen":
            lines.append("⚠️ Les élixirs ne comptent PAS dans les épreuves de rang ni les défis.")
        lines.append("Élixirs actifs : " + active_elixirs_text(repo.list_active_elixirs(player_id)))
        return UseConsumableResult(success=True, message="\n".join(lines), item_name=item.name)

    # --------------------------------------------------------- outils de Sorn --
    def _consume(self, player_id: int, item) -> bool:
        return self.inventory_repository.remove_item(player_id, item.id, 1)

    def _use_tool(self, session, profile, item, effect: str, bonuses: dict,
                  context: UseContext) -> UseConsumableResult:
        from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository

        pid = profile.player.id
        fail = lambda message: UseConsumableResult(False, message, item.name)  # noqa: E731
        now = datetime.now(UTC)

        if effect == tools.EFFECT_DAILY_GUARD:
            return fail("⏳ Le sablier agit tout seul : il protégera ta série le premier jour "
                        "de /daily manqué.")

        if effect == tools.EFFECT_RESPEC:
            progression = profile.progression
            placed = (progression.points_attack or 0) + (progression.points_defense or 0) \
                + (progression.points_max_hp or 0)
            if not placed:
                return fail("📜 Tu n'as aucun point de stats placé : le parchemin n'a pas servi.")
            if not self._consume(pid, item):
                return fail(f"❌ Vous n'avez pas de **{item.name}** en inventaire.")
            refunded = self.player_repository.reset_stat_points(pid)
            return UseConsumableResult(True, f"📜 **{item.name}** : {refunded} points de stats repris. "
                                             "Replace-les avec `/stats`.", item.name)

        if effect == tools.EFFECT_RESET_TREE:
            from app.application.use_cases.reset_skill_tree import ResetSkillTreeUseCase
            from app.domain.services.cooldown_service import CooldownService

            result = ResetSkillTreeUseCase(
                self.player_repository, self.skill_allocation_repository,
                CooldownRepository(session), CooldownService(), get_skill_tree_definition(),
            ).execute(profile.player.discord_id, use_token=True)
            if not result.success:
                return fail(result.message)
            self._consume(pid, item)
            return UseConsumableResult(True, result.message + " Investis-les avec `/arbre`.", item.name)

        cooldowns = CooldownRepository(session)
        rank = str(bonuses.get("rank", ""))
        if effect == tools.EFFECT_TRIAL_RETRY:
            target = tools.next_rank(context.player_rank)
            if context.player_rank is None or target is None:
                return fail("🔱 Aucune épreuve de rang à retenter.")
            if target != rank:
                return fail(f"🔱 Ce sceau sert à l'épreuve du rang **{rank}** ; la tienne est celle "
                            f"du rang **{target}**.")
            cooldown = cooldowns.get_by_player_and_action(pid, "rank_trial")
            until = cooldown.next_available_at if cooldown else None
            if until is not None and until.tzinfo is None:
                until = until.replace(tzinfo=UTC)
            if until is None or until <= now:
                return fail("🔱 Tu peux déjà tenter ton épreuve : garde ton sceau pour un échec.")
            if not self._consume(pid, item):
                return fail(f"❌ Vous n'avez pas de **{item.name}** en inventaire.")
            cooldowns.upsert(pid, "rank_trial", last_used_at=cooldown.last_used_at or now, next_available_at=now)
            return UseConsumableResult(True, f"🔱 Second souffle ! Tu peux retenter l'épreuve du rang "
                                             f"**{rank}** tout de suite : `/epreuve`.", item.name)

        # ---- Cor de chasse ----
        if context.summon_elite is None:
            return fail("📯 Le cor ne résonne que depuis Discord.")
        if tools.rank_index(context.player_rank) < tools.rank_index(rank):
            return fail(f"📯 Il faut le rang **{rank}** pour entrer dans cette zone.")
        cooldown = cooldowns.get_by_player_and_action(pid, tools.HORN_ACTION_KEY)
        until = cooldown.next_available_at if cooldown else None
        if until is not None and until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        if until is not None and until > now:
            return fail(f"📯 Tu as encore le souffle court : prochain cor <t:{int(until.timestamp())}:R>.")
        target = zone_elite(session, rank)
        if target is None:
            return fail("📯 Cette zone n'est pas ouverte, ou n'a pas d'élite.")
        mob_code, mob_name, channel_id = target
        ok, message = context.summon_elite(mob_code, channel_id)
        if not ok:
            return fail(f"📯 {message}")
        self._consume(pid, item)
        cooldowns.upsert(pid, tools.HORN_ACTION_KEY, last_used_at=now, next_available_at=now + tools.HORN_COOLDOWN)
        return UseConsumableResult(
            True, f"📯 Tu sonnes le cor : **{mob_name}** {message} dans <#{channel_id}>.", item.name,
            announce_channel_id=channel_id,
            announce=f"📯 **{profile.player.display_name}** a sonné le cor de chasse : "
                     f"**{mob_name}** {message}. Rassemblez-vous !",
        )


def active_elixirs_text(active: dict) -> str:
    """« 💪 Force (58 min) · 🛡️ Garde (12 min) » — `active` = {kind: effet}."""
    from app.domain.services.alchemy_service import ELIXIR_STATUS_KINDS

    now = datetime.now(UTC).replace(tzinfo=None)
    by_kind = {status: kind for kind, status in ELIXIR_STATUS_KINDS.items()}
    parts = []
    for status_kind, effect in sorted(active.items()):
        minutes = max(1, int((effect.expires_at - now).total_seconds() // 60))
        parts.append(f"{ELIXIR_LABELS.get(by_kind.get(status_kind, ''), status_kind)} ({minutes} min)")
    return " · ".join(parts) or "aucun"

def zone_elite(session, rank: str) -> tuple[str, str, int] | None:
    """(code, nom, salon) de l'élite de groupe de la zone OUVERTE de ce rang
    (la plus forte s'il y en a plusieurs)."""
    from app.domain.services.mob_ability_service import is_group_elite
    from app.infrastructure.db.repositories.mob_repository import MobRepository
    from app.infrastructure.encounters import farm_zone_loader

    zone = next((z for z in farm_zone_loader.list_zones() if z.get("rank") == rank), None)
    if zone is None or not zone.get("channel_id"):
        return None
    elites = [m for m in MobRepository(session).list_all()
              if m.family in zone["families"] and is_group_elite(m.code)]
    if not elites:
        return None
    elite = max(elites, key=lambda m: m.xp_reward or 0)
    return elite.code, elite.name, int(zone["channel_id"])
