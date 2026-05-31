"""Parity test : formule Excel du tableur ↔ PowerScoreService.

Le tableur d'équilibrage (`scripts/export_content_spreadsheet.py`) injecte
DEUX formules Excel écrites à la main :

- `_equip_power_formula` (marginal : power(base+item) − power(base))
- `_mob_power_formula` (absolu)

Ces formules doivent rester en sync avec `PowerScoreService.calculate_from_stats`
(la formule Python de référence). Si quelqu'un modifie la formule Python sans
répercuter dans le générateur de tableur (ou inversement), les chiffres du
tableur deviennent silencieusement faux.

On NE peut PAS évaluer la formule Excel via LibreOffice dans un test pytest
(trop lourd). À la place, on réimplémente la formule Excel EN PYTHON
LITTÉRALEMENT (même expression mathématique que la chaîne `=ROUND(...)` écrite
dans la feuille). Si le calcul Python diverge de celui de `PowerScoreService`,
c'est que la formule Excel a divergé aussi — le test sert d'ancre.

L'écart toléré est de 2 (arrondi int() côté Python vs ROUND() côté Excel).
"""
from __future__ import annotations

from app.domain.services.power_score_service import (
    PowerScoreService,
    _DEF_EFFECTIVE_HITS,
    _SCALE,
)
from app.domain.value_objects.stats import Stats


def _excel_power_formula(
    max_hp: int,
    attack: int,
    defense: int,
    crit_chance: int,
    crit_damage: int,
    dodge: int,
    speed: int,
) -> float:
    """Réimplémentation littérale de la formule Excel ABSOLUE.

    Reproduit EXACTEMENT l'expression écrite dans `_mob_power_formula` (et la
    partie "absolue" de `_equip_power_formula`, soit power(base+item)) :

        off = atk * (1 + (cc/100) * MAX(0, cd-100)/100) * (1 + sp/100)
        ehp = (hp + def*K_DEF) / MAX(0.01, 1 - dg/100)
        power = (off * ehp) / SCALE

    K_DEF = `_DEF_EFFECTIVE_HITS` (=25), SCALE = `_SCALE` (=42). Ces deux
    constantes sont également exportées dans la feuille « Calibration » du
    tableur via les références `$B$9` et `$B$10`.
    """
    crit_mult = 1 + (crit_chance / 100) * max(0, crit_damage - 100) / 100
    speed_mult = 1 + speed / 100
    off = attack * crit_mult * speed_mult

    ehp = (max_hp + defense * _DEF_EFFECTIVE_HITS) / max(0.01, 1 - dodge / 100)

    return (off * ehp) / _SCALE


# Cas de test couvrant les principaux profils : joueur débutant, mid, mob
# standard, mob crit-immune, mob avec dodge fort, joueur très investi.
# Chaque tuple : (max_hp, attack, defense, crit_chance, crit_damage, dodge, speed)
_PARITY_CASES: list[tuple[int, int, int, int, int, int, int]] = [
    # Joueur de référence niveau 1 (base StatsService 100/10/5/5)
    (100, 10, 5, 5, 150, 0, 5),
    # Joueur niveau ~50 (mid game, équipement modeste)
    (350, 35, 20, 12, 160, 5, 7),
    # Joueur niveau ~100 (entrée endgame, build équilibré)
    (700, 80, 45, 20, 175, 10, 10),
    # Joueur très investi (build crit, gros gear)
    (1200, 150, 80, 35, 200, 15, 15),
    # Mob standard niveau 10 (DEF ~45% ATK joueur, PV ~11× ATK joueur)
    (220, 20, 9, 5, 150, 0, 5),
    # Mob brute (ATK élevé, DEF faible)
    (400, 60, 5, 10, 180, 0, 8),
    # Mob blindé (DEF élevée, ATK faible)
    (600, 25, 70, 0, 100, 0, 3),
    # Mob crit-immune (crit_chance=0, crit_damage=100 → bonus crit nul)
    (500, 40, 15, 0, 100, 0, 6),
    # Mob rapide avec dodge fort
    (300, 30, 10, 8, 160, 25, 20),
]


def test_excel_formula_matches_service_python():
    """Pour chaque cas, la formule Excel (réimplémentée) doit donner le même
    résultat que `PowerScoreService.calculate_from_stats` à l'arrondi près."""
    service = PowerScoreService()
    for case in _PARITY_CASES:
        max_hp, attack, defense, crit_chance, crit_damage, dodge, speed = case
        excel_value = _excel_power_formula(
            max_hp=max_hp,
            attack=attack,
            defense=defense,
            crit_chance=crit_chance,
            crit_damage=crit_damage,
            dodge=dodge,
            speed=speed,
        )
        stats = Stats(
            max_hp=max_hp,
            attack=attack,
            defense=defense,
            crit_chance=crit_chance,
            crit_damage=crit_damage,
            dodge=dodge,
            hp_regeneration=0,
            speed=speed,
        )
        service_value = service.calculate_from_stats(stats)

        # Excel renvoie un float arrondi (ROUND), service renvoie max(1, int()).
        # Tolérance 2 = différence d'arrondi (truncation int vs round half-up).
        # Si la formule diverge réellement, l'écart sera bien supérieur.
        delta = abs(excel_value - service_value)
        assert delta < 2, (
            f"Divergence formule Excel ↔ PowerScoreService pour {case} : "
            f"Excel={excel_value:.2f}, service={service_value}, delta={delta:.2f}. "
            f"La formule du tableur (scripts/export_content_spreadsheet.py) "
            f"n'est plus en sync avec PowerScoreService.calculate_from_stats."
        )


def test_excel_formula_marginal_matches_service_python():
    """Formule MARGINALE d'équipement : power(base+item) − power(base).

    Vérifie que (excel(base+item) − excel(base)) ≈ (service(base+item) − service(base)).
    On utilise la base CALIB_REF du tableur (100/10/5/5%/150/0%/5).
    """
    service = PowerScoreService()
    base = (100, 10, 5, 5, 150, 0, 5)  # joueur de référence (CALIB)
    # 4 items factices : armure, bouclier, anneau crit, cape esquive
    items = [
        (40, 0, 0, 0, 0, 0, 0),    # HP +40
        (0, 5, 0, 0, 0, 0, 0),     # ATK +5
        (0, 0, 0, 3, 10, 0, 0),    # crit_chance +3, crit_damage +10
        (0, 0, 8, 0, 0, 2, 1),     # DEF +8, dodge +2, speed +1
    ]

    base_excel = _excel_power_formula(*base)
    base_service = service.calculate_from_stats(
        Stats(
            max_hp=base[0], attack=base[1], defense=base[2],
            crit_chance=base[3], crit_damage=base[4], dodge=base[5],
            hp_regeneration=0, speed=base[6],
        )
    )

    for item in items:
        combined = tuple(b + i for b, i in zip(base, item))
        combined_excel = _excel_power_formula(*combined)
        combined_service = service.calculate_from_stats(
            Stats(
                max_hp=combined[0], attack=combined[1], defense=combined[2],
                crit_chance=combined[3], crit_damage=combined[4], dodge=combined[5],
                hp_regeneration=0, speed=combined[6],
            )
        )

        excel_marginal = combined_excel - base_excel
        service_marginal = combined_service - base_service

        delta = abs(excel_marginal - service_marginal)
        # Tolérance 2 : deux arrondis (base + combined) cumulables.
        assert delta < 2, (
            f"Divergence formule MARGINALE Excel ↔ service pour item {item} : "
            f"Excel marginal={excel_marginal:.2f}, service marginal={service_marginal}, "
            f"delta={delta:.2f}."
        )
