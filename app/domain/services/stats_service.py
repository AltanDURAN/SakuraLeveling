"""Calcul des stats de combat d'un joueur — SAISON 1.

Refonte d'octobre 2026. L'ancien modèle empilait des bonus PLATS venus de
partout (arbre, équipement, classe, panoplie) sur un socle constant. Un objet
de fin de jeu valait donc exactement autant sur un débutant que sur un
vétéran, et offrir une pièce à un nouveau joueur le rendait surpuissant d'un
coup.

Le nouveau modèle a un seul socle et deux natures de bonus :

  SOCLE  — les trois stats de base (ATK, DEF, PV max), montées par les POINTS
           DE STATS que le joueur place à chaque niveau. C'est la seule source
           de puissance brute du jeu.

  %      — l'équipement, l'arbre, les panoplies et les titres s'expriment en
           POURCENTAGE de ce socle pour ATK / DEF / PV. Un même objet rapporte
           donc peu à un débutant et beaucoup à un vétéran : il ne peut plus
           « cheater » un nouveau joueur.

  PLAT   — les stats secondaires (vitesse, esquive, crit, régénérations, mana)
           restent en valeurs brutes, parce qu'un « pourcentage de pourcentage
           de critique » n'aurait aucun sens lisible. Elles viennent surtout de
           l'arbre de compétences.

⚠️ Les pourcentages de toutes les sources s'ADDITIONNENT avant d'être
appliqués UNE SEULE FOIS au socle (+20 % équipement et +15 % arbre donnent
+35 %, pas ×1,20×1,15). Multiplier les sources rend l'équilibrage
ingérable dès qu'on ajoute une quatrième source.
"""

from __future__ import annotations

from dataclasses import replace

from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_profile import PlayerProfile
from app.domain.services.item_upgrade_service import level_multiplier
from app.domain.services.set_bonus_service import SetBonuses
from app.domain.services.title_bonus_service import TitleBonuses
from app.domain.value_objects.base_stats import BaseStats
from app.domain.value_objects.skill_bonuses import SkillBonuses
from app.domain.value_objects.stats import Stats
from app.domain.value_objects.status_effect_bonuses import StatusEffectBonuses

#: Valeurs de départ des stats SECONDAIRES (celles qui ne sont pas montées par
#: les points de stats). Elles progressent via l'arbre, en brut.
BASE_SPEED = 5
BASE_CRIT_CHANCE = 5.0
BASE_CRIT_DAMAGE = 150.0
BASE_DODGE = 0.0
BASE_HP_REGENERATION = 5
BASE_MANA_MAX = 100
BASE_MANA_REGENERATION = 5

#: Clés de pourcentage reconnues dans `stat_bonuses` d'un item.
PERCENT_KEYS = ("attack_pct", "defense_pct", "max_hp_pct")
#: Clés plates reconnues (stats secondaires uniquement).
FLAT_KEYS = (
    "speed", "crit_chance", "crit_damage", "dodge",
    "hp_regeneration", "mana_max", "mana_regeneration",
)

#: Plafond du cumul de pourcentages, par stat. Sans lui, empiler équipement +
#: arbre + panoplie + titres finirait par multiplier le socle sans limite.
MAX_PERCENT_BONUS = 3.0  # +300 %


class StatsService:
    def calculate_player_stats(
        self,
        profile: PlayerProfile,
        equipped_items: list[PlayerEquipmentItem],
        skill_bonuses: SkillBonuses | None = None,
        title_bonuses: TitleBonuses | None = None,
        set_bonuses: SetBonuses | None = None,
        status_bonuses: StatusEffectBonuses | None = None,
        item_levels: dict[int, int] | None = None,
    ) -> Stats:
        base = self.base_stats_for(profile)

        pct = {"attack": 0.0, "defense": 0.0, "max_hp": 0.0}
        flat = {
            "speed": BASE_SPEED,
            "crit_chance": BASE_CRIT_CHANCE,
            "crit_damage": BASE_CRIT_DAMAGE,
            "dodge": BASE_DODGE,
            "hp_regeneration": BASE_HP_REGENERATION,
            "mana_max": BASE_MANA_MAX,
            "mana_regeneration": BASE_MANA_REGENERATION,
        }

        # ---- Équipement : % sur le socle, plat sur les stats secondaires ----
        for item in equipped_items:
            bonuses = item.item_definition.stat_bonuses or {}
            # Amélioration (fusion / forge sacrée) : +10 % des bonus de la
            # pièce par niveau, +10 = ×2. Cf. item_upgrade_service.
            level = (item_levels or {}).get(item.item_definition.id, 0)
            multiplier = level_multiplier(level)
            self._accumulate(bonuses, pct, flat, multiplier)

        # ---- Arbre de compétences ----
        if skill_bonuses is not None:
            pct["attack"] += skill_bonuses.atk_percent
            pct["defense"] += skill_bonuses.def_percent
            pct["max_hp"] += skill_bonuses.hp_max_percent

            flat["speed"] += skill_bonuses.speed_flat
            flat["crit_chance"] += skill_bonuses.crit_chance_flat
            flat["crit_damage"] += skill_bonuses.crit_damage_flat
            flat["dodge"] += skill_bonuses.dodge_flat
            flat["hp_regeneration"] += skill_bonuses.hp_regeneration_flat
            flat["mana_max"] += skill_bonuses.mana_max_flat
            flat["mana_regeneration"] += skill_bonuses.mana_regeneration_flat

        # ---- Panoplies ----
        if set_bonuses is not None:
            pct["attack"] += getattr(set_bonuses, "attack_percent", 0.0)
            pct["defense"] += getattr(set_bonuses, "defense_percent", 0.0)
            pct["max_hp"] += getattr(set_bonuses, "max_hp_percent", 0.0)

            flat["speed"] += set_bonuses.speed_flat
            flat["crit_chance"] += set_bonuses.crit_chance_flat
            flat["crit_damage"] += set_bonuses.crit_damage_flat
            flat["dodge"] += set_bonuses.dodge_flat
            flat["hp_regeneration"] += set_bonuses.hp_regeneration_flat
            flat["mana_max"] += set_bonuses.mana_max_flat
            flat["mana_regeneration"] += set_bonuses.mana_regeneration_flat

        # ---- Application du socle ----
        stats = Stats(
            max_hp=max(1, round(base.max_hp * (1 + self._cap(pct["max_hp"])))),
            attack=max(1, round(base.attack * (1 + self._cap(pct["attack"])))),
            defense=max(1, round(base.defense * (1 + self._cap(pct["defense"])))),
            speed=max(1, int(flat["speed"])),
            crit_chance=min(75.0, max(0.0, flat["crit_chance"])),
            crit_damage=max(100.0, flat["crit_damage"]),
            dodge=min(50.0, max(0.0, flat["dodge"])),
            hp_regeneration=max(0, int(flat["hp_regeneration"])),
            mana_max=max(0, int(flat["mana_max"])),
            mana_regeneration=max(0, int(flat["mana_regeneration"])),
        )

        # ---- Multiplicateurs de critique (classe Assassin : chances ×2, dégâts
        # ×3). Ils agissent sur la stat FINALE, au-delà du plafond de 75 % des
        # chances (borné à 100 %) : c'est l'identité de la classe. ----
        if skill_bonuses is not None and (
            skill_bonuses.crit_chance_multiplier != 1.0
            or skill_bonuses.crit_damage_multiplier != 1.0
        ):
            stats = replace(
                stats,
                crit_chance=min(100.0, stats.crit_chance * skill_bonuses.crit_chance_multiplier),
                crit_damage=max(100.0, stats.crit_damage * skill_bonuses.crit_damage_multiplier),
            )

        # ---- Titres : appliqués APRÈS les plafonds (c'est leur privilège) ----
        if title_bonuses is not None:
            stats = title_bonuses.apply_to_stats(stats)

        # ---- Effets temporaires (buff/debuff d'événement) ----
        if status_bonuses is not None:
            stats = status_bonuses.apply_to_stats(stats)

        return stats

    # ------------------------------------------------------------- socle --
    @staticmethod
    def base_stats_for(profile: PlayerProfile) -> BaseStats:
        """Socle issu des points de stats investis par le joueur."""
        progression = getattr(profile, "progression", None)
        return BaseStats.from_points(
            attack_points=getattr(progression, "points_attack", 0) or 0,
            defense_points=getattr(progression, "points_defense", 0) or 0,
            hp_points=getattr(progression, "points_max_hp", 0) or 0,
        )

    # -------------------------------------------------------- accumulation --
    @staticmethod
    def _accumulate(
        bonuses: dict, pct: dict, flat: dict, multiplier: int = 1,
    ) -> None:
        """Répartit les bonus d'un item entre pourcentages et valeurs plates.

        Une clé inconnue est ignorée SILENCIEUSEMENT : le contenu est éditable
        depuis l'admin, une faute de frappe ne doit pas faire planter un combat.
        """
        for key in PERCENT_KEYS:
            raw = bonuses.get(key)
            if raw is None:
                continue
            try:
                # Le contenu est saisi en points de pourcentage (20 = +20 %).
                pct[key[:-4]] += float(raw) * multiplier / 100.0
            except (TypeError, ValueError):
                continue

        for key in FLAT_KEYS:
            raw = bonuses.get(key)
            if raw is None:
                continue
            try:
                flat[key] += float(raw) * multiplier
            except (TypeError, ValueError):
                continue

    @staticmethod
    def _cap(value: float) -> float:
        return min(MAX_PERCENT_BONUS, max(-0.9, value))
