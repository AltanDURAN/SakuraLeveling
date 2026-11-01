"""Alertes de surveillance : règles, seuils et gravité.

Chaque règle lit des FAITS déjà calculés (`PlayerFacts`, `MobFacts`,
`ServerFacts`) et rend des `Alert`. Les seuils sont réglables depuis le site
(Surveillance › Alertes, `monitoring.json`) ; une règle se désactive sans
toucher au code.

Gravité : « critique » (à regarder tout de suite : de l'or sans origine, un
script probable), « serieux » (comportement anormal, à vérifier), « attention »
(équilibrage, rétention), « info » (à savoir : méta, joueurs à relancer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.shared.formatters import format_int

CRITICAL = "critique"
SERIOUS = "serieux"
WARNING = "attention"
INFO = "info"
SEVERITY_ORDER = (CRITICAL, SERIOUS, WARNING, INFO)
SEVERITY_LABELS = {CRITICAL: "Critique", SERIOUS: "Sérieux", WARNING: "Attention", INFO: "Info"}

CHEAT = "suspect"
BALANCE = "equilibrage"
ECONOMY = "economie"
ENGAGEMENT = "engagement"
TECH = "technique"
CATEGORY_LABELS = {CHEAT: "Comportements suspects", BALANCE: "Équilibrage", ECONOMY: "Économie",
                   ENGAGEMENT: "Activité et rétention", TECH: "Technique"}


@dataclass(frozen=True)
class ThresholdSpec:
    key: str
    label: str
    default: float
    unit: str
    help: str
    rule: str           # règle qui l'utilise (pour l'afficher avec elle)


@dataclass(frozen=True)
class Rule:
    code: str
    label: str
    category: str
    severity: str
    why: str            # pourquoi c'est important (affiché sous l'alerte)


RULES: tuple[Rule, ...] = (
    Rule("unexplained_gold", "Or sans origine", CHEAT, CRITICAL,
         "Le solde a bougé sans mouvement d'or enregistré : modification directe de la base, "
         "bug de duplication ou chemin de code qui oublie le journal."),
    Rule("gold_rate", "Or par heure anormal", CHEAT, SERIOUS,
         "Gagner beaucoup plus d'or par heure de jeu que les autres signale une faille "
         "(exploit, boucle de récompense) ou une source oubliée dans l'équilibrage."),
    Rule("bot_like", "Activité de script", CHEAT, CRITICAL,
         "Des actions à intervalles quasi fixes ou une présence sur presque toutes les heures "
         "de la journée ressemblent à un programme qui joue à la place du joueur."),
    Rule("marathon", "Session marathon", CHEAT, WARNING,
         "Une session très longue sans pause : joueur très investi… ou automatisation."),
    Rule("spam", "Rafale d'actions", CHEAT, WARNING,
         "Beaucoup d'actions en une minute : macro, ou bouton qui ne répond pas assez vite."),
    Rule("level_speed", "Montée de niveau trop rapide", CHEAT, SERIOUS,
         "Plus de niveaux en 24 h que ce que le jeu permet normalement : power-leveling, "
         "XP admin oubliée ou faille d'XP."),
    Rule("power_outlier", "Puissance hors norme", CHEAT, WARNING,
         "Bien plus puissant que les joueurs de son niveau : build à étudier (méta trop forte) "
         "ou objet obtenu anormalement."),
    Rule("gold_hub", "Or reçu de nombreux joueurs", CHEAT, SERIOUS,
         "Recevoir de l'or de beaucoup de comptes différents est le signe classique des "
         "multi-comptes qui alimentent un compte principal."),
    Rule("market_price", "Prix de brocante anormal", CHEAT, WARNING,
         "Une vente très loin du prix habituel de l'objet : transfert d'or déguisé ou erreur."),
    Rule("mob_too_easy", "Monstre trop facile", BALANCE, INFO,
         "Toujours battu, très vite : il rapporte peut-être trop pour l'effort."),
    Rule("mob_too_hard", "Monstre trop difficile", BALANCE, WARNING,
         "Battu trop rarement, ou il tue beaucoup : il bloque la progression de la zone."),
    Rule("meta_gear", "Pièce omniprésente", BALANCE, INFO,
         "Une même pièce portée par presque tout le monde : son passif ou ses stats écrasent "
         "les alternatives."),
    Rule("meta_spec", "Spécialisation dominante", BALANCE, INFO,
         "Presque tous les spécialisés ont choisi la même voie : les autres manquent d'intérêt."),
    Rule("meta_stats", "Répartition des points uniforme", BALANCE, INFO,
         "La plupart des joueurs mettent presque tous leurs points dans la même stat : "
         "les autres ne valent pas le coup."),
    Rule("pace", "Rythme de progression", BALANCE, WARNING,
         "Au rythme actuel, les joueurs atteindront la fin du contenu bien plus tôt (ou plus "
         "tard) que prévu par le design."),
    Rule("content_end", "Fin du contenu proche", BALANCE, WARNING,
         "Le joueur le plus avancé va bientôt atteindre le dernier niveau des zones ouvertes."),
    Rule("stuck", "Joueur bloqué", BALANCE, INFO,
         "Actif mais au même niveau depuis plusieurs jours : mur de difficulté ou d'XP."),
    Rule("inflation", "Inflation", ECONOMY, WARNING,
         "La masse d'or grossit trop vite : les prix fixes perdent leur sens et l'or ne "
         "régule plus rien."),
    Rule("hoarding", "Or concentré", ECONOMY, INFO,
         "Une poignée de joueurs détient l'essentiel de l'or : il manque des puits d'or "
         "de fin de partie."),
    Rule("admin_gold", "Or donné par l'admin", ECONOMY, INFO,
         "Pour mémoire : l'or ajouté à la main fausse les mesures d'économie."),
    Rule("dau_drop", "Chute d'activité", ENGAGEMENT, WARNING,
         "Beaucoup moins de joueurs aujourd'hui que d'habitude."),
    Rule("retention", "Rétention à 7 jours faible", ENGAGEMENT, WARNING,
         "Peu de nouveaux joueurs reviennent la semaine suivante : le début du jeu perd du monde."),
    Rule("churn_risk", "Joueur investi absent", ENGAGEMENT, INFO,
         "Un joueur très investi ne vient plus : à relancer avant qu'il parte."),
    Rule("unspent_points", "Points non dépensés", ENGAGEMENT, INFO,
         "Beaucoup de points à placer : le joueur ne sait peut-être pas qu'il en a."),
    Rule("errors", "Erreurs de commandes", TECH, SERIOUS,
         "Des commandes plantent : le journal du bot dit pourquoi."),
)
RULES_BY_CODE = {r.code: r for r in RULES}

THRESHOLDS: tuple[ThresholdSpec, ...] = (
    ThresholdSpec("unexplained_gold_min", "Écart minimum", 2000, "or",
                  "Écart entre le solde et le journal à partir duquel on alerte.", "unexplained_gold"),
    ThresholdSpec("gold_rate_ratio", "Fois la médiane", 3, "×",
                  "Or gagné par heure de jeu, comparé à la médiane des joueurs actifs.", "gold_rate"),
    ThresholdSpec("gold_rate_min_hours", "Temps de jeu minimum", 2, "h",
                  "En dessous, trop peu de jeu pour juger (7 derniers jours).", "gold_rate"),
    ThresholdSpec("bot_regularity", "Régularité maximale", 0.15, "",
                  "Variation des écarts entre deux actions (0 = parfaitement régulier, un humain ≥ 0,5).",
                  "bot_like"),
    ThresholdSpec("bot_hours_per_day", "Heures actives dans une journée", 20, "h",
                  "Nombre d'heures différentes avec une action dans une même journée.", "bot_like"),
    ThresholdSpec("marathon_hours", "Durée de session", 6, "h",
                  "Session continue (pauses de moins de 15 min).", "marathon"),
    ThresholdSpec("spam_per_minute", "Actions par minute", 30, "",
                  "Plus grand nombre d'actions dans une même minute (7 derniers jours).", "spam"),
    ThresholdSpec("level_speed_24h", "Niveaux en 24 h", 8, "niv.",
                  "Hors niveaux donnés par l'admin.", "level_speed"),
    ThresholdSpec("power_z", "Écart à la norme", 3.5, "σ",
                  "Écart robuste de puissance avec les joueurs de ±3 niveaux.", "power_outlier"),
    ThresholdSpec("gold_hub_senders", "Donateurs distincts", 3, "joueurs",
                  "Joueurs différents qui lui ont donné de l'or en 14 jours (virement, échange).", "gold_hub"),
    ThresholdSpec("market_price_ratio", "Écart au prix habituel", 5, "×",
                  "Vente au moins N fois plus chère ou moins chère que la médiane de l'objet.", "market_price"),
    ThresholdSpec("mob_easy_win_pct", "Victoires minimum", 99, "%", "", "mob_too_easy"),
    ThresholdSpec("mob_easy_turns", "Actions maximum", 6, "", "Durée moyenne d'un combat gagné.", "mob_too_easy"),
    ThresholdSpec("mob_hard_win_pct", "Victoires maximum", 50, "%", "Taux de victoire en dessous duquel on alerte.",
                  "mob_too_hard"),
    ThresholdSpec("mob_hard_death_pct", "Morts maximum", 30, "%", "Part des participants tués.", "mob_too_hard"),
    ThresholdSpec("mob_min_fights", "Combats minimum", 20, "",
                  "Sous ce nombre de combats (30 jours), on ne juge pas un monstre.", "mob_too_hard"),
    ThresholdSpec("meta_gear_pct", "Part des joueurs", 60, "%",
                  "Part des joueurs équipés qui portent la même pièce.", "meta_gear"),
    ThresholdSpec("meta_spec_pct", "Part des spécialisés", 70, "%", "", "meta_spec"),
    ThresholdSpec("meta_stats_pct", "Part des joueurs", 70, "%",
                  "Part des joueurs qui mettent plus de 80 % de leurs points dans la même stat.", "meta_stats"),
    ThresholdSpec("pace_fast_pct", "Trop rapide si moins de", 60, "% du prévu",
                  "Jours projetés pour le niveau 100 (médiane), comparés au design (1 h / jour).", "pace"),
    ThresholdSpec("pace_slow_pct", "Trop lent si plus de", 200, "% du prévu", "", "pace"),
    ThresholdSpec("content_end_days", "Jours avant la fin", 21, "j",
                  "Jours avant que le meilleur joueur atteigne le dernier niveau des zones ouvertes.",
                  "content_end"),
    ThresholdSpec("stuck_days", "Jours au même niveau", 5, "j", "En jouant au moins 3 de ces jours.", "stuck"),
    ThresholdSpec("inflation_pct", "Hausse par jour", 8, "%",
                  "Croissance moyenne de la masse d'or sur 7 jours.", "inflation"),
    ThresholdSpec("hoarding_pct", "Part des 10 % les plus riches", 60, "%", "", "hoarding"),
    ThresholdSpec("admin_gold_min", "Or admin sur 7 jours", 50000, "or", "", "admin_gold"),
    ThresholdSpec("dau_drop_pct", "Baisse", 40, "%",
                  "Joueurs actifs aujourd'hui (jusqu'à cette heure) contre la moyenne des 7 jours à la même heure.",
                  "dau_drop"),
    ThresholdSpec("dau_min", "Moyenne minimum", 5, "joueurs", "En dessous, l'activité varie trop pour juger.",
                  "dau_drop"),
    ThresholdSpec("retention_d7_pct", "Rétention minimum", 25, "%", "Sur les 4 dernières semaines d'arrivée.",
                  "retention"),
    ThresholdSpec("churn_days", "Jours d'absence", 3, "j", "Pour un joueur du quart le plus investi.",
                  "churn_risk"),
    ThresholdSpec("unspent_points", "Points à placer", 10, "", "Points de stats ou d'arbre.", "unspent_points"),
    ThresholdSpec("errors_24h", "Erreurs en 24 h", 5, "", "", "errors"),
)
THRESHOLD_SPECS = {t.key: t for t in THRESHOLDS}


def default_thresholds() -> dict[str, float]:
    return {t.key: t.default for t in THRESHOLDS}


# ------------------------------------------------------------------- faits
@dataclass
class PlayerFacts:
    player_id: int
    name: str
    level: int = 1
    power: int = 0
    gold: int = 0
    is_admin: bool = False
    play_hours_7d: float = 0.0
    creation_gold_7d: int = 0           # or créé (combats, quêtes…) sur 7 jours
    levels_24h: int = 0
    longest_session_h: float = 0.0
    max_active_hours_day: int = 0
    regularity: float | None = None
    max_burst: int = 0
    gold_senders: int = 0                # 14 derniers jours
    gold_received: int = 0
    unexplained_gold: int = 0
    days_since_active: float | None = None
    investment_pct: float = 0.0         # centile d'investissement (0-100)
    unspent_points: int = 0
    stuck_days: int = 0                 # jours actifs au même niveau
    power_z: float = 0.0


@dataclass
class MobFacts:
    code: str
    name: str
    fights: int = 0
    wins: int = 0
    deaths: int = 0
    participants: int = 0
    avg_win_turns: float = 0.0

    @property
    def win_pct(self) -> float:
        return 100 * self.wins / self.fights if self.fights else 0.0

    @property
    def death_pct(self) -> float:
        return 100 * self.deaths / self.participants if self.participants else 0.0


@dataclass
class ServerFacts:
    now: datetime
    dau_today: int = 0
    dau_baseline: float = 0.0           # moyenne des 7 jours précédents à la même heure
    money_growth_pct: float | None = None
    top10_share_pct: float = 0.0
    holders: int = 0
    retention_d7_pct: float | None = None
    retention_d7_base: int = 0
    gear_top: tuple[str, str, float, int] | None = None   # code, nom, %, joueurs équipés
    spec_top: tuple[str, float, int] | None = None        # nom, %, spécialisés
    stat_top: tuple[str, float, int] | None = None        # stat, %, joueurs
    pace_ratio_pct: float | None = None  # projection médiane / design × 100
    pace_players: int = 0
    content_end_days: int | None = None
    content_end_level: int = 0
    content_end_reached: int = 0
    content_end_player: str = ""
    admin_gold_7d: int = 0
    errors_24h: int = 0
    error_commands: tuple[str, ...] = ()
    market: list[tuple[int, str, str, int, int]] = field(default_factory=list)  # pid, nom, objet, prix, médiane


@dataclass(frozen=True)
class Alert:
    key: str
    code: str
    severity: str
    title: str
    message: str
    player_id: int | None = None
    ref: str = ""            # monstre, pièce… (lien)

    @property
    def rule(self) -> Rule:
        return RULES_BY_CODE[self.code]

    @property
    def category(self) -> str:
        return self.rule.category


def _h(hours: float) -> str:
    return f"{hours:.1f} h".replace(".", ",")


def evaluate(players: list[PlayerFacts], mobs: list[MobFacts], server: ServerFacts,
             thresholds: dict[str, float] | None = None,
             enabled: dict[str, bool] | None = None) -> list[Alert]:
    """Toutes les alertes en cours, la plus grave d'abord. Les comptes admin
    ne déclenchent pas d'alerte de comportement (ils testent)."""
    t = {**default_thresholds(), **(thresholds or {})}
    on = (lambda code: (enabled or {}).get(code, True))
    out: list[Alert] = []

    def add(code: str, key: str, title: str, message: str, player_id=None, ref="", severity=None):
        if on(code):
            out.append(Alert(f"{code}:{key}", code, severity or RULES_BY_CODE[code].severity,
                             title, message, player_id, ref))

    rates = [p.creation_gold_7d / p.play_hours_7d for p in players
             if p.play_hours_7d >= t["gold_rate_min_hours"] and not p.is_admin]
    rates.sort()
    median_rate = rates[len(rates) // 2] if rates else 0

    for p in players:
        if p.is_admin:
            continue
        if p.unexplained_gold and abs(p.unexplained_gold) >= t["unexplained_gold_min"]:
            sign = "+" if p.unexplained_gold > 0 else "−"
            add("unexplained_gold", str(p.player_id), f"{p.name} : {sign}{format_int(abs(p.unexplained_gold))} or sans origine",
                "Son solde ne correspond pas à la somme des mouvements d'or enregistrés depuis la dernière photo.",
                p.player_id)
        if p.play_hours_7d >= t["gold_rate_min_hours"] and median_rate > 0 and len(rates) >= 3:
            rate = p.creation_gold_7d / p.play_hours_7d
            if rate >= t["gold_rate_ratio"] * median_rate:
                add("gold_rate", str(p.player_id), f"{p.name} gagne {rate / median_rate:.1f}× plus d'or par heure".replace(".", ","),
                    f"{format_int(round(rate))} or / h de jeu sur 7 jours, contre {format_int(round(median_rate))} pour "
                    f"le joueur médian ({_h(p.play_hours_7d)} de jeu).", p.player_id)
        robotic = p.regularity is not None and p.regularity <= t["bot_regularity"]
        if robotic or p.max_active_hours_day >= t["bot_hours_per_day"]:
            parts = []
            if robotic:
                parts.append(f"actions à intervalles quasi fixes (variation {p.regularity:.2f})".replace(".", ","))
            if p.max_active_hours_day >= t["bot_hours_per_day"]:
                parts.append(f"actif {p.max_active_hours_day} heures différentes dans une même journée")
            add("bot_like", str(p.player_id), f"{p.name} joue peut-être avec un script", " · ".join(parts).capitalize() + ".",
                p.player_id)
        if p.longest_session_h >= t["marathon_hours"]:
            add("marathon", str(p.player_id), f"{p.name} : session de {_h(p.longest_session_h)}",
                "Plus longue session des 7 derniers jours, sans pause de plus de 15 minutes.", p.player_id)
        if p.max_burst >= t["spam_per_minute"]:
            add("spam", str(p.player_id), f"{p.name} : {p.max_burst} actions en une minute",
                "Rafale la plus forte des 7 derniers jours.", p.player_id)
        if p.levels_24h >= t["level_speed_24h"]:
            add("level_speed", str(p.player_id), f"{p.name} : +{p.levels_24h} niveaux en 24 h",
                f"Il est maintenant niveau {p.level}.", p.player_id)
        if p.power_z >= t["power_z"]:
            add("power_outlier", str(p.player_id), f"{p.name} est bien plus puissant que son niveau",
                f"Puissance {format_int(p.power)} au niveau {p.level} : {p.power_z:.1f} écarts au-dessus des joueurs "
                f"de son niveau.".replace(".", ",", 1), p.player_id)
        if p.gold_senders >= t["gold_hub_senders"]:
            add("gold_hub", str(p.player_id), f"{p.name} reçoit de l'or de {p.gold_senders} joueurs",
                f"{format_int(p.gold_received)} or reçu en 14 jours (virements et échanges).", p.player_id)
        if p.investment_pct >= 75 and p.days_since_active is not None and p.days_since_active >= t["churn_days"]:
            add("churn_risk", str(p.player_id), f"{p.name} ne joue plus depuis {int(p.days_since_active)} jours",
                f"Il fait partie des joueurs les plus investis (centile {p.investment_pct:.0f}).", p.player_id)
        if p.stuck_days >= t["stuck_days"]:
            add("stuck", str(p.player_id), f"{p.name} bloqué au niveau {p.level}",
                f"Au même niveau depuis {p.stuck_days} jours en jouant.", p.player_id)

    hoarders = sorted((p for p in players if not p.is_admin and p.unspent_points >= t["unspent_points"]),
                      key=lambda p: -p.unspent_points)
    if hoarders:
        names = ", ".join(f"{p.name} ({p.unspent_points})" for p in hoarders[:8])
        add("unspent_points", "all", f"{len(hoarders)} joueur{'s' if len(hoarders) > 1 else ''} avec des points à placer",
            f"Points de stats (/stats) et d'arbre (/arbre) en attente : {names}"
            + (" …" if len(hoarders) > 8 else "") + ".")

    for pid, name, item, price, med in server.market:
        add("market_price", f"{pid}:{item}:{price}", f"{name} : {item} vendu {format_int(price)} or",
            f"Prix habituel : {format_int(med)} or.", pid)

    for m in mobs:
        if m.fights < t["mob_min_fights"]:
            continue
        if m.win_pct >= t["mob_easy_win_pct"] and 0 < m.avg_win_turns <= t["mob_easy_turns"]:
            add("mob_too_easy", m.code, f"{m.name} est trop facile",
                f"{m.win_pct:.0f} % de victoires en {m.avg_win_turns:.1f} actions en moyenne ({m.fights} combats).".replace(".", ",", 1),
                ref=m.code)
        if m.win_pct <= t["mob_hard_win_pct"] or m.death_pct >= t["mob_hard_death_pct"]:
            add("mob_too_hard", m.code, f"{m.name} est trop difficile",
                f"{m.win_pct:.0f} % de victoires, {m.death_pct:.0f} % des participants tués ({m.fights} combats).",
                ref=m.code)

    s = server
    if s.gear_top and s.gear_top[2] >= t["meta_gear_pct"] and s.gear_top[3] >= 5:
        add("meta_gear", s.gear_top[0], f"{s.gear_top[1]} portée par {s.gear_top[2]:.0f} % des joueurs",
            f"Sur {s.gear_top[3]} joueurs équipés.", ref=s.gear_top[0])
    if s.spec_top and s.spec_top[1] >= t["meta_spec_pct"] and s.spec_top[2] >= 5:
        add("meta_spec", s.spec_top[0], f"{s.spec_top[0]} : {s.spec_top[1]:.0f} % des spécialisés",
            f"Sur {s.spec_top[2]} joueurs spécialisés.")
    if s.stat_top and s.stat_top[1] >= t["meta_stats_pct"] and s.stat_top[2] >= 5:
        add("meta_stats", s.stat_top[0], f"Tout le monde monte {s.stat_top[0]}",
            f"{s.stat_top[1]:.0f} % des joueurs y mettent plus de 80 % de leurs points ({s.stat_top[2]} joueurs).")
    if s.pace_ratio_pct is not None and s.pace_players >= 3:
        if s.pace_ratio_pct <= t["pace_fast_pct"]:
            add("pace", "fast", "La progression est plus rapide que prévu",
                f"Niveau 100 projeté en {s.pace_ratio_pct:.0f} % du temps prévu par le design (médiane de "
                f"{s.pace_players} joueurs actifs).")
        elif s.pace_ratio_pct >= t["pace_slow_pct"]:
            add("pace", "slow", "La progression est plus lente que prévu",
                f"Niveau 100 projeté en {s.pace_ratio_pct:.0f} % du temps prévu par le design (médiane de "
                f"{s.pace_players} joueurs actifs).")
    if s.content_end_reached:
        add("content_end", "reached", f"{s.content_end_reached} joueur{'s ont' if s.content_end_reached > 1 else ' a'} "
            f"atteint la fin du contenu", f"Niveau {s.content_end_level} ou plus : il n'y a plus de zone au-dessus "
            f"pour eux. Ouvrir la zone suivante, ou leur donner un objectif (tour, raid, défis).")
    elif s.content_end_days is not None and s.content_end_days <= t["content_end_days"]:
        add("content_end", "top", f"Fin du contenu dans {s.content_end_days} jours",
            f"{s.content_end_player} atteindra le niveau {s.content_end_level}, le dernier des zones ouvertes, "
            f"à son rythme actuel.")
    if s.money_growth_pct is not None and s.money_growth_pct >= t["inflation_pct"]:
        add("inflation", "money", f"Masse d'or : +{s.money_growth_pct:.1f} % par jour".replace(".", ","),
            "Croissance moyenne sur les 7 derniers jours.")
    if s.holders >= 10 and s.top10_share_pct >= t["hoarding_pct"]:
        add("hoarding", "top10", f"Les 10 % les plus riches ont {s.top10_share_pct:.0f} % de l'or",
            f"Sur {s.holders} joueurs.")
    if s.admin_gold_7d >= t["admin_gold_min"]:
        add("admin_gold", "7d", f"{format_int(s.admin_gold_7d)} or donné par l'admin en 7 jours",
            "Exclu des mesures d'économie.")
    if s.dau_baseline >= t["dau_min"] and s.dau_today < s.dau_baseline * (1 - t["dau_drop_pct"] / 100):
        drop = 100 * (1 - s.dau_today / s.dau_baseline)
        add("dau_drop", s.now.date().isoformat(), f"Activité en baisse de {drop:.0f} % aujourd'hui",
            f"{s.dau_today} joueurs actifs contre {s.dau_baseline:.1f} d'habitude à cette heure.".replace(".", ","))
    if s.retention_d7_pct is not None and s.retention_d7_base >= 5 and s.retention_d7_pct < t["retention_d7_pct"]:
        add("retention", "d7", f"Rétention à 7 jours : {s.retention_d7_pct:.0f} %",
            f"Sur les {s.retention_d7_base} derniers arrivés qui ont l'âge de la mesurer.")
    if s.errors_24h >= t["errors_24h"]:
        add("errors", "24h", f"{s.errors_24h} erreurs de commandes en 24 h",
            "Commandes concernées : " + ", ".join(f"/{c}" for c in s.error_commands[:6]) + ".")

    order = {sev: i for i, sev in enumerate(SEVERITY_ORDER)}
    return sorted(out, key=lambda a: (order.get(a.severity, 9), a.title))
