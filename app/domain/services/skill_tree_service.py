from app.domain.entities.skill_node import SkillNode
from app.domain.entities.skill_tree_definition import SkillTreeDefinition
from app.domain.value_objects.skill_bonuses import SkillBonuses


# Mapping effet du JSON -> attribut de SkillBonuses. Les types absents sont
# poliment ignorés (permet d'étendre l'arbre sans casser les anciens loaders).
_EFFECT_FIELD_MAP: dict[str, str] = {
    "atk_percent": "atk_percent",
    "def_percent": "def_percent",
    "hp_max_percent": "hp_max_percent",
    "crit_chance_flat": "crit_chance_flat",
    "crit_damage_flat": "crit_damage_flat",
    "dodge_flat": "dodge_flat",
    "speed_flat": "speed_flat",
    "hp_regeneration_flat": "hp_regeneration_flat",
    "xp_drop_percent": "xp_drop_percent",
    "gold_drop_percent": "gold_drop_percent",
    "drop_rate_multiplier": "drop_rate_multiplier",
}


class SkillTreeService:
    """Logique pure de l'arbre de compétences : agrégation de bonus, validation
    d'investissement, calcul d'état pour le rendu."""

    def __init__(self, definition: SkillTreeDefinition):
        self.definition = definition

    # ---------- Agrégation des bonus ----------

    def aggregate_bonuses(self, allocations: dict[str, int]) -> SkillBonuses:
        """Somme les effets de tous les niveaux investis."""
        atk_percent = 0.0
        def_percent = 0.0
        hp_max_percent = 0.0
        crit_chance_flat = 0
        crit_damage_flat = 0
        dodge_flat = 0
        speed_flat = 0
        hp_regeneration_flat = 0
        xp_drop_percent = 0.0
        gold_drop_percent = 0.0
        drop_rate_multiplier = 1.0

        for skill_code, level in allocations.items():
            if level <= 0:
                continue
            node = self.definition.get(skill_code)
            if node is None:
                continue

            for effect in node.effects:
                if effect.type not in _EFFECT_FIELD_MAP:
                    continue

                # `values` représente le bonus *cumulé* à chaque palier :
                # values[0] = bonus à lvl 1, values[1] = bonus à lvl 2, etc.
                # On indexe directement par level-1 (clamp si level dépasse).
                idx = min(level, len(effect.values)) - 1
                if idx < 0:
                    continue
                cumulative = effect.values[idx]

                match effect.type:
                    case "atk_percent":
                        atk_percent += cumulative / 100.0
                    case "def_percent":
                        def_percent += cumulative / 100.0
                    case "hp_max_percent":
                        hp_max_percent += cumulative / 100.0
                    case "crit_chance_flat":
                        crit_chance_flat += int(cumulative)
                    case "crit_damage_flat":
                        crit_damage_flat += int(cumulative)
                    case "dodge_flat":
                        dodge_flat += int(cumulative)
                    case "speed_flat":
                        speed_flat += int(cumulative)
                    case "hp_regeneration_flat":
                        hp_regeneration_flat += int(cumulative)
                    case "xp_drop_percent":
                        xp_drop_percent += cumulative / 100.0
                    case "gold_drop_percent":
                        gold_drop_percent += cumulative / 100.0
                    case "drop_rate_multiplier":
                        # Les paliers s'additionnent en pourcentage, mais le résultat
                        # est appliqué de manière multiplicative au taux de base.
                        # +5% de chance = drop_rate_multiplier = 1.05.
                        drop_rate_multiplier += cumulative / 100.0

        return SkillBonuses(
            atk_percent=atk_percent,
            def_percent=def_percent,
            hp_max_percent=hp_max_percent,
            crit_chance_flat=crit_chance_flat,
            crit_damage_flat=crit_damage_flat,
            dodge_flat=dodge_flat,
            speed_flat=speed_flat,
            hp_regeneration_flat=hp_regeneration_flat,
            xp_drop_percent=xp_drop_percent,
            gold_drop_percent=gold_drop_percent,
            drop_rate_multiplier=drop_rate_multiplier,
        )

    # ---------- État d'un nœud ----------

    def compute_node_state(
        self, allocations: dict[str, int], skill_code: str
    ) -> str:
        """Renvoie 'maxed' | 'in_progress' | 'unlockable' | 'locked'."""
        node = self.definition.get(skill_code)
        if node is None:
            return "locked"

        current_level = allocations.get(skill_code, 0)

        if current_level >= node.max_level:
            return "maxed"
        if current_level > 0:
            return "in_progress"
        if self._prerequisites_satisfied(allocations, node):
            return "unlockable"
        return "locked"

    def _prerequisites_satisfied(
        self, allocations: dict[str, int], node: SkillNode
    ) -> bool:
        for prereq_code in node.prerequisites:
            if allocations.get(prereq_code, 0) <= 0:
                return False
        return True

    # ---------- Liste des compétences débloquables ----------

    def compute_unlockable_skills(
        self, allocations: dict[str, int], limit: int = 25
    ) -> list[SkillNode]:
        """Renvoie les nœuds que le joueur peut investir maintenant : prérequis
        remplis ET niveau actuel < max_level. Trié par profondeur (parents avant
        enfants) puis par code, plafonné à `limit`.

        La limite par défaut est 25 (max d'options dans un Discord Select Menu)
        pour rester cohérent avec le rendu visuel de l'arbre : si l'image montre
        un nœud "débloquable" mais qu'on le tronque ici, le joueur ne peut pas
        le sélectionner, et on a un bug de divergence front/back.
        """
        candidates: list[SkillNode] = []
        for node in self.definition:
            current_level = allocations.get(node.code, 0)
            if current_level >= node.max_level:
                continue
            if not self._prerequisites_satisfied(allocations, node):
                continue
            candidates.append(node)

        candidates.sort(key=lambda n: (self._depth(n), n.code))
        return candidates[:limit]

    def _depth(self, node: SkillNode) -> int:
        """Profondeur (longueur du chemin depuis la racine, mémorisée à la volée)."""
        if not node.prerequisites:
            return 0
        # Le calcul exact serait BFS, mais on peut approximer par max(depth(parents))+1
        return 1 + max(
            (
                self._depth(self.definition.get(p))
                for p in node.prerequisites
                if self.definition.get(p) is not None
            ),
            default=0,
        )

    # ---------- Validation d'un investissement ----------

    def validate_investment(
        self,
        allocations: dict[str, int],
        available_points: int,
        skill_code: str,
    ) -> tuple[bool, str, int]:
        """Vérifie si on peut investir +1 niveau dans `skill_code`.

        Renvoie (ok, message, cost). Si ok=False, message décrit la raison.
        """
        node = self.definition.get(skill_code)
        if node is None:
            return False, f"Compétence inconnue : `{skill_code}`.", 0

        current_level = allocations.get(skill_code, 0)
        target_level = current_level + 1

        if current_level >= node.max_level:
            return (
                False,
                f"**{node.name}** est déjà au niveau maximum ({node.max_level}/{node.max_level}).",
                0,
            )

        if not self._prerequisites_satisfied(allocations, node):
            missing = [
                self.definition.get(p).name if self.definition.get(p) else p
                for p in node.prerequisites
                if allocations.get(p, 0) <= 0
            ]
            return (
                False,
                f"Prérequis manquants pour **{node.name}** : {', '.join(missing)}.",
                0,
            )

        cost = node.cost_for_level(target_level)
        if available_points < cost:
            return (
                False,
                f"Points insuffisants : il vous manque **{cost - available_points}** "
                f"point(s) pour débloquer **{node.name}** (niveau {target_level}).",
                cost,
            )

        return (
            True,
            f"**{node.name}** investi au niveau {target_level}/{node.max_level} "
            f"(coût : {cost} pts).",
            cost,
        )

    # ---------- Refund total (utilisé par le reset) ----------

    def compute_total_refund(self, allocations: dict[str, int]) -> int:
        total = 0
        for skill_code, level in allocations.items():
            node = self.definition.get(skill_code)
            if node is None or level <= 0:
                continue
            total += node.cumulative_cost(level)
        return total
