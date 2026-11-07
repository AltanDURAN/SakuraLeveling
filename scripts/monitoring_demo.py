"""Base de DÉMONSTRATION de la surveillance : des joueurs fictifs et des
semaines de jeu simulées, pour voir et tester les pages Surveillance du site
sans attendre que de vrais joueurs remplissent le journal.

    .venv/bin/python -m scripts.monitoring_demo --db /tmp/demo.db
    DATABASE_URL=sqlite:////tmp/demo.db .venv/bin/python -m webapp.main

⚠️ N'écrit QUE dans la base indiquée (créée de zéro) ; refuse la vraie base.

Profils simulés : acharnés, réguliers, occasionnels, joueurs du week-end, de
midi, départs en cours de route, nouveaux venus — et des cas SUSPECTS plantés
exprès pour vérifier que les alertes les trouvent : un script (actions
régulières jour et nuit), un compte nourri par trois multi-comptes, de l'or
apparu sans passer par le jeu, des rafales de clics.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PARIS = ZoneInfo("Europe/Paris")

NAMES = """Akira Yumeko Hikari Ren Sakura Kaito Mei Haru Suzu Kenji Aiko Daichi Emi Hoshi Isamu Kiyo
Mio Nao Rin Sora Taiga Yui Asuka Botan Chiyo Fubuki Ginji Hotaru Izumi Jun Kaede Kohaku Masaru Nanami
Oboro Riku Shiori Tsubaki Umi Wakana Yamato Zen Ayame Benika Chika Daisuke Eiko Fumi Goro Hana""".split()

COMMANDS = ["profil", "stats", "inventaire", "equipement", "quetes", "arbre", "cd", "or", "equipement_liste",
            "classement niveau", "affinites", "tour", "defi", "marchand", "forgeron", "alchimiste", "boss moi",
            "lune", "quetes_hebdo", "panoplie", "bestiaire", "utiliser", "equiper", "help"]
CMD_WEIGHTS = [10, 8, 7, 6, 8, 5, 6, 4, 3, 3, 2, 3, 3, 2, 2, 2, 2, 1, 2, 1, 1, 3, 3, 1]

ARCHETYPES = {
    #           jours joués, minutes/session, sessions/jour, heures préférées
    "acharne": (0.95, (90, 220), (1, 3), [12, 13, 18, 19, 20, 21, 22, 23]),
    "regulier": (0.78, (35, 80), (1, 2), [19, 20, 21, 22]),
    "occasionnel": (0.40, (15, 40), (1, 1), [13, 18, 20, 21]),
    "weekend": (0.95, (60, 180), (1, 2), [10, 11, 14, 15, 16, 21]),
    "midi": (0.70, (20, 45), (1, 2), [12, 13]),
}


@dataclass
class Sim:
    pid: int
    discord_id: int
    name: str
    archetype: str
    created: datetime
    stop: datetime | None = None
    build: str = "equilibre"          # dps / tank / soutien / equilibre
    level: int = 1
    xp: int = 0
    gold: int = 0
    kills: int = 0
    combats: int = 0
    wins: int = 0
    gold_earned: int = 0
    streak: int = 0
    rank: str = "F"
    gear: dict = field(default_factory=dict)       # code → rareté
    tower: int = 0
    sessions: list = field(default_factory=list)   # (début, fin) UTC naïf
    bot: bool = False
    spammer: bool = False
    feeder_of: int | None = None
    exploit: bool = False
    strong: float = 1.0


def _naive(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(tzinfo=None)


def build_db(path: Path) -> None:
    # La base ET ses fichiers WAL : un ancien journal appliqué à la nouvelle
    # base la corromprait (arrêter la webapp qui la lit avant de régénérer).
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if p.exists():
            p.unlink()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path}"}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True,
                   capture_output=True)
    subprocess.run([sys.executable, "-m", "app.infrastructure.db.seeders.seed_content"], cwd=ROOT, env=env,
                   check=True, capture_output=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--players", type=int, default=46)
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    db = args.db.resolve()
    if db.name == "lita_v2.db" or db == (ROOT / "lita_v2.db").resolve():
        sys.exit("Refusé : la démo ne touche jamais la vraie base.")
    print(f"Base de démo : {db}")
    build_db(db)
    os.environ["DATABASE_URL"] = f"sqlite:///{db}"
    simulate(args.players, args.days, random.Random(args.seed))


def simulate(n_players: int, n_days: int, rng: random.Random) -> None:
    from sqlalchemy import update

    from app.domain.services.gear_service import roll_drop
    from app.domain.services.mob_ability_service import is_group_elite
    from app.domain.services.monitoring import kinds
    from app.domain.services.monitoring.progression import ZONE_LEVELS, total_xp
    from app.domain.services.progression_service import ProgressionService
    from app.infrastructure.db.models.gear_model import PlayerGearModel
    from app.infrastructure.db.models.item_model import ItemDefinitionModel
    from app.infrastructure.db.models.monitoring_model import GameEventModel, PlayerDailySnapshotModel
    from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel
    from app.infrastructure.db.models.player_model import PlayerModel
    from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel
    from app.infrastructure.db.models.progression_model import PlayerProgressionModel
    from app.infrastructure.db.models.resource_model import PlayerResourceModel
    from app.infrastructure.db.repositories.player_repository import PlayerRepository
    from app.infrastructure.db.session import get_db_session
    from app.infrastructure.encounters.farm_zone_loader import list_zones
    from app.infrastructure.skill_tree.skill_tree_loader import get_definition

    progression = ProgressionService()
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(days=n_days)

    mobs = json.loads((ROOT / "app/infrastructure/content/mobs.json").read_text(encoding="utf-8"))
    mobs = mobs if isinstance(mobs, list) else mobs.get("mobs", [])
    zones = [z for z in list_zones() if z.get("channel_id")]
    by_rank = {}
    for z in zones:
        members = [m for m in mobs if m["family"] in z["families"]]
        for m in members:
            elite = is_group_elite(m["code"])
            m["_level"] = max(1, round(m["xp_reward"] / 6.25 / (3 if elite else 1)))
            m["_elite"] = elite
        by_rank[z.get("rank", "F")] = (str(z["channel_id"]), members)
    ranks = [r for r in ("F", "E", "D", "C", "B", "A") if r in by_rank]

    with get_db_session() as session:
        item_ids = {it.code: it.id for it in session.query(ItemDefinitionModel).all()}
        tree_codes = [c for c, node in get_definition().skills.items() if not node.start]

    # ------------------------------------------------------------- joueurs
    archetypes = (["acharne"] * 6 + ["regulier"] * 14 + ["occasionnel"] * 10 + ["weekend"] * 6 + ["midi"] * 4)
    sims: list[Sim] = []
    with get_db_session() as session:
        repo = PlayerRepository(session)
        for i in range(n_players):
            name = NAMES[i % len(NAMES)] + ("" if i < len(NAMES) else str(i))
            profile = repo.get_or_create_by_discord_id(900_000_000_000_000 + i, name.lower(), name)
            arch = archetypes[i % len(archetypes)]
            # Arrivées : la moitié au lancement, le reste au fil des semaines.
            offset = 0 if i < n_players // 2 else rng.uniform(0, n_days - 2)
            if i >= n_players - 3:            # multi-comptes : arrivés il y a 10 jours
                arch, offset = "occasionnel", n_days - 10 + (n_players - i) * 0.3
            created = start + timedelta(days=offset, hours=rng.uniform(8, 22))
            sim = Sim(profile.player.id, 900_000_000_000_000 + i, name, arch, created,
                      build=rng.choice(["dps", "dps", "tank", "soutien", "equilibre"]))
            if i % 9 == 4 and offset < n_days / 2:
                sim.stop = created + timedelta(days=rng.uniform(6, 16))     # départ
            sims.append(sim)
            session.execute(update(PlayerModel).where(PlayerModel.id == sim.pid).values(created_at=_naive(created)))
        session.commit()
    # Cas suspects plantés.
    sims[0].strong = 1.9                                    # puissance hors norme
    sims[3].bot = True
    sims[5].spammer = True
    sims[8].exploit = True
    main_alt = sims[1]
    for k in (n_players - 1, n_players - 2, n_players - 3):
        sims[k].feeder_of = main_alt.pid

    # ------------------------------------------------------------ sessions
    for s in sims:
        frac, minutes, per_day, hours = ARCHETYPES[s.archetype]
        day = s.created.astimezone(PARIS).date()
        while True:
            d0 = datetime.combine(day, datetime.min.time(), PARIS)
            if d0 > now or (s.stop and d0 > s.stop):
                break
            weekend = day.weekday() >= 5
            p = frac if s.archetype != "weekend" else (0.95 if weekend else 0.15)
            if s.archetype == "occasionnel" and weekend:
                p += 0.2
            if rng.random() < p:
                for _ in range(rng.randint(*per_day)):
                    h = rng.choice(hours)
                    begin = d0 + timedelta(hours=h, minutes=rng.uniform(0, 59))
                    length = rng.uniform(*minutes) * (1.3 if weekend else 1.0)
                    end = begin + timedelta(minutes=length)
                    if s.created <= begin <= now:
                        s.sessions.append((_naive(begin), _naive(min(end, now))))
            day += timedelta(days=1)
        if s.bot:   # 3 jours presque non-stop, très réguliers
            b0 = now - timedelta(days=5)
            s.sessions.append((_naive(b0), _naive(b0 + timedelta(hours=70))))
        s.sessions.sort()

    events: list[tuple] = []     # (at, kind, pid, discord_id, zone, ref, gold, xp, qty, data)

    def ev(at, kind, sim=None, zone=None, ref=None, gold=0, xp=0, qty=0, data=None, discord_id=None):
        events.append((at, kind, sim.pid if sim else None, discord_id or (sim.discord_id if sim else None),
                       zone, ref, int(gold), int(xp), int(qty), data))

    def gold(sim, at, amount, source):
        before = sim.gold
        sim.gold = max(0, sim.gold + amount)
        if sim.gold != before:
            ev(at, kinds.GOLD, sim, ref=source, gold=sim.gold - before)

    def grant_xp(sim, at, amount):
        r = progression.apply_level_up(current_level=sim.level, current_xp=sim.xp, gained_xp=amount,
                                       current_skill_points=0, current_stat_points=0)
        if r.level > sim.level:
            ev(at, kinds.LEVEL_UP, sim, qty=r.level, data={"from": sim.level})
            for rank in ranks:
                low = ZONE_LEVELS[rank][0]
                if sim.level < low <= r.level and ranks.index(rank) > ranks.index(sim.rank):
                    role = {"dps": "dps", "tank": "tank"}.get(sim.build, "soutien")
                    trial_at = at + timedelta(minutes=rng.uniform(5, 300))
                    if rng.random() < 0.35:
                        ev(trial_at - timedelta(minutes=2), kinds.RANK_TRIAL, sim, ref=rank, qty=rng.randint(800, 4000),
                           data={"role": role, "passed": False})
                    ev(trial_at, kinds.RANK_TRIAL, sim, ref=rank, qty=rng.randint(4000, 9000),
                       data={"role": role, "passed": True})
                    ev(trial_at + timedelta(seconds=5), kinds.RANK_UP, sim, ref=rank, qty=r.level)
                    sim.rank = rank
        sim.level, sim.xp = r.level, r.xp

    def zone_for(sim):
        best = "F"
        for rank in ranks:
            if ranks.index(rank) <= ranks.index(sim.rank):
                best = rank
        return best

    def online(sim, t):
        i = bisect_right(sim.sessions, (t, datetime.max)) - 1
        return i >= 0 and sim.sessions[i][0] <= t <= sim.sessions[i][1]

    # Une seule chronologie : intentions des joueurs (daily, quêtes) et
    # apparitions de monstres, traitées dans l'ordre (niveaux bien datés).
    timeline: list[tuple] = []
    for s in sims:
        last_daily = None
        for begin, end in s.sessions:
            d = begin.replace(tzinfo=UTC).astimezone(PARIS).date()
            if last_daily != d and not s.bot:
                timeline.append((begin, 0, "daily", s))
                last_daily = d
            t = begin
            step = (40, 52) if s.bot else (60, 420)
            while t < end:                       # interactions : sans effet sur l'état
                t += timedelta(seconds=rng.uniform(*step))
                if s.bot:
                    ev(t, kinds.INTERACTION, s, ref="bouton:encounter_join")
                    continue
                ev(t, kinds.INTERACTION, s, ref=rng.choices(COMMANDS, CMD_WEIGHTS)[0])
                if s.spammer and rng.random() < 0.02:
                    for k in range(45):
                        ev(t + timedelta(seconds=k * 1.1), kinds.INTERACTION, s, ref="bouton:encounter_join")
            if (end - begin).total_seconds() > 1200 and rng.random() < 0.6:
                timeline.append((end, 1, "quest", s))
    for rank in ranks:
        t = _naive(start)
        while t < _naive(now):
            t += timedelta(minutes=rng.uniform(2, 5))
            timeline.append((t, 2, "spawn", rank))
    timeline.sort(key=lambda x: (x[0], x[1]))

    for t, _, what, arg in timeline:
        if what == "daily":
            s = arg
            ev(t, kinds.INTERACTION, s, ref="daily")
            d = t.replace(tzinfo=UTC).astimezone(PARIS).date()
            prev = getattr(s, "_last_daily", None)
            s.streak = s.streak + 1 if prev == d - timedelta(days=1) else max(1, s.streak // 2)
            s._last_daily = d
            g = round(20 * s.level * (1 + min(30, s.streak) * 0.03))
            ev(t, kinds.DAILY, s, qty=s.streak, gold=g)
            gold(s, t, g, "daily")
            continue
        if what == "quest":
            s = arg
            q_gold, q_xp = round(45 * s.level), round(60 * s.level)
            ev(t, kinds.INTERACTION, s, ref="quetes")
            ev(t, kinds.QUEST, s, ref="kill_any", gold=q_gold, xp=q_xp, data={"type": "kill"})
            gold(s, t, q_gold, "quete")
            grant_xp(s, t, q_xp)
            continue
        rank = arg
        channel, members = by_rank[rank]
        here = [s for s in sims if s.sessions and online(s, t) and zone_for(s) == rank and not s.bot]
        if rank == "F":
            here += [s for s in sims if s.bot and online(s, t)]
        joined = [s for s in here if rng.random() < 0.85]
        avg_level = sum(s.level for s in joined) / len(joined) if joined else 1
        fit = [m for m in members if (m["_level"] <= avg_level + 4 or m is members[0])]
        mob = rng.choice(fit[-6:]) if fit else members[0]
        if mob["_elite"] and len(joined) < 2:
            mob = fit[-2] if len(fit) > 1 else members[0]
        pack = 1 if rng.random() > 0.1 else rng.choice([2, 3])
        if not joined:
            ev(t, kinds.FLEE, zone=channel, ref=mob["code"], qty=pack)
            continue
        key = f"{channel}:{int(t.timestamp())}"
        gap = avg_level - mob["_level"]
        win_p = min(0.995, max(0.25, 0.86 + 0.03 * gap + 0.04 * (len(joined) - 1)))
        if mob["code"] in ("succube", "liche_maudite"):
            win_p *= 0.55
        won = rng.random() < win_p
        turns = max(3, round(rng.gauss(28 if won else 45, 8) / (1 + 0.2 * (len(joined) - 1))))
        pool = mob["gold_reward"] * pack
        fight_at = t + timedelta(minutes=2.5)
        for s in joined:
            ev(t + timedelta(seconds=rng.uniform(5, 100)), kinds.INTERACTION, s, ref="bouton:encounter_join")
            dead = won and rng.random() < (0.06 if len(joined) > 1 else 0.03)
            res = "loss" if not won else ("death" if dead else "win")
            share_ = 1 / len(joined)
            g = round(pool * share_ * rng.uniform(0.8, 1.2)) if res == "win" else 0
            xp = round(mob["xp_reward"] * pack * 1.1) if won else 0
            s.combats += 1
            if res == "win":
                s.wins += 1
                s.kills += pack
                s.gold_earned += g
            ev(fight_at, kinds.COMBAT, s, zone=channel, ref=mob["code"], gold=g, xp=xp,
               qty=pack if res == "win" else 0,
               data={"mobs": [mob["code"]] * pack, "res": res, "n": len(joined), "turns": turns, "enc": key,
                     "dmg": rng.randint(200, 900) * s.level, "share": round(share_, 3)})
            if g:
                gold(s, fight_at, g, "combat")
            if xp:
                grant_xp(s, fight_at, xp)
            if res != "win":
                continue
            rarity = roll_drop(rng)
            if rarity is not None and mob.get("gear_item_code"):
                code = mob["gear_item_code"]
                ev(fight_at, kinds.GEAR_DROP, s, ref=code, data={"rarity": rarity.value})
                order = ["common", "uncommon", "rare", "epic", "legendary", "mythic"]
                if code not in s.gear or order.index(rarity.value) > order.index(s.gear[code]):
                    s.gear[code] = rarity.value
            if rng.random() < 0.012 and s.gold > 1500:
                item = rng.choice(["cor_chasse_f", "sceau_souffle_e", "parchemin_oubli", "sablier_fidelite"])
                cost = {"cor_chasse_f": 1000, "sceau_souffle_e": 700, "parchemin_oubli": 150 * s.level,
                        "sablier_fidelite": 2000}[item]
                if s.gold >= cost:
                    ev(fight_at, kinds.SHOP_BUY, s, ref=item, qty=1, gold=-cost)
                    gold(s, fight_at, -cost, "boutique")
            if rng.random() < 0.01 and s.gear:
                code = rng.choice(list(s.gear))
                fee = {"common": 200, "uncommon": 1000, "rare": 6000}.get(s.gear[code])
                if fee and s.gold >= fee:
                    ev(fight_at, kinds.FUSION, s, ref=code, gold=-fee, data={"from": s.gear[code], "to": "x"})
                    gold(s, fight_at, -fee, "fusion")
            if rng.random() < 0.01 and s.gold > 400:
                fee = 8 * s.level * 3
                ev(fight_at, kinds.BREW, s, ref="potion_soin", qty=3, gold=-fee)
                gold(s, fight_at, -fee, "alchimie")

    # Multi-comptes : les alts versent leur or au compte principal.
    for s in sims:
        if s.feeder_of is None:
            continue
        for begin, end in s.sessions[-3:]:
            amount = max(0, s.gold - 50)
            if amount > 200:
                ev(end, kinds.TRANSFER, s, ref="virement", gold=amount, data={"to": s.feeder_of})
                gold(s, end, -amount, "virement")
                gold(main_alt, end, amount, "virement")
    # Brocante : quelques ventes, dont une à prix délirant.
    sellers = [s for s in sims if s.gear]
    gear_id = item_ids.get("perle_de_gelee", 1)
    for k in range(14):
        buyer, seller = rng.sample(sellers, 2)
        at = _naive(now - timedelta(days=rng.uniform(0, 20)))
        price = rng.randint(380, 520) if k else 25_000
        if buyer.gold < price:
            continue
        ev(at, kinds.MARKET_SALE, buyer, ref=str(gear_id), qty=1, gold=price, data={"seller": seller.pid, "fee": price // 20})
        gold(buyer, at, -price, "brocante")
        gold(seller, at, price - price // 20, "brocante")
    # Offrandes, voyante, tour, défis, raid, erreurs, tutoriel.
    for s in sims:
        for begin, end in s.sessions:
            if rng.random() < 0.05:
                ev(end, kinds.TOWER, s, qty=s.tower + 1, data={"won": rng.random() < 0.6})
                s.tower += 1 if events[-1][9]["won"] else 0
            if rng.random() < 0.04 and s.gold > 3000:
                g = rng.choice([1000, 1000, 10000]) if s.gold > 12000 else 1000
                ev(end, kinds.OFFERING, s, gold=g)
                gold(s, end, -g, "offrande")
            if rng.random() < 0.03:
                ev(end, kinds.ROLE_TRIAL, s, ref=rng.choice(["dps", "tank", "soutien"]), qty=rng.randint(2000, 20000))
        if s.sessions:
            first = s.sessions[0][0]
            ev(first + timedelta(minutes=3), kinds.TUTORIAL, s, ref=rng.choice(["termine", "termine", "passe"]), qty=9)
            ev(first + timedelta(minutes=8), kinds.SEER, s, ref=rng.choice(["feu", "eau", "plante"]), qty=rng.randint(0, 10))
    for k in range(9):
        s = rng.choice(sims)
        ev(_naive(now - timedelta(hours=rng.uniform(0, 20))), kinds.ERROR, s, ref=rng.choice(["boss moi", "tour"]))
    admin_target = sims[10]
    ev(_naive(now - timedelta(days=3)), kinds.GOLD, admin_target, ref="admin", gold=60000)
    admin_target.gold += 60000

    events.sort(key=lambda e: e[0])
    times = [e[0] for e in events]
    # Arrivées sur le serveur (avant le profil).
    for s in sims:
        events.append((_naive(s.created) - timedelta(minutes=2), kinds.MEMBER_JOIN, None, s.discord_id, None, None, 0, 0, 0, None))
    events.sort(key=lambda e: e[0])
    times = [e[0] for e in events]

    # ---------------------------------------------- écriture et photos
    print(f"{len(events)} événements, {len(sims)} joueurs")
    with get_db_session() as session:
        session.bulk_insert_mappings(GameEventModel, [
            {"at": e[0], "kind": e[1], "player_id": e[2], "discord_id": e[3], "zone": e[4], "ref": e[5],
             "gold": e[6], "xp": e[7], "qty": e[8], "data": json.dumps(e[9], separators=(",", ":")) if e[9] else None}
            for e in events])
        session.commit()

    # Rejoue les événements jour par jour pour reconstituer l'état du soir.
    order = ["common", "uncommon", "rare", "epic", "legendary", "mythic"]
    by_pid = {s.pid: s for s in sims}
    state = {s.pid: {"level": 1, "xp_total": 0, "gold": 0, "kills": 0, "combats": 0, "wins": 0, "earned": 0,
                     "gear": {}, "rank": "F", "tower": 0} for s in sims}
    snapshots = []
    i = 0
    day = start.astimezone(PARIS).date()
    end_day = now.astimezone(PARIS).date()
    xp_of = {}
    while day <= end_day:
        cut = _naive(datetime.combine(day + timedelta(days=1), datetime.min.time(), PARIS)) - timedelta(minutes=5)
        cut = min(cut, _naive(now))
        while i < len(events) and events[i][0] <= cut:
            at, kind, pid, _, zone, ref, g, xp, qty, data = events[i]
            st = state.get(pid)
            if st is not None:
                if kind == kinds.GOLD:
                    st["gold"] += g          # somme exacte du journal (pas de plancher)
                    if kinds.flow_of(ref, g) == kinds.CREATION:
                        st["earned"] += g
                elif kind == kinds.COMBAT:
                    st["combats"] += 1
                    st["xp_total"] += xp
                    if data["res"] == "win":
                        st["wins"] += 1
                        st["kills"] += qty
                elif kind == kinds.QUEST:
                    st["xp_total"] += xp
                elif kind == kinds.LEVEL_UP:
                    st["level"] = qty
                elif kind == kinds.RANK_UP:
                    st["rank"] = ref
                elif kind == kinds.GEAR_DROP:
                    if ref not in st["gear"] or order.index(data["rarity"]) > order.index(st["gear"][ref]):
                        st["gear"][ref] = data["rarity"]
                elif kind == kinds.TOWER and data.get("won"):
                    st["tower"] = max(st["tower"], qty)
            i += 1
        eid = i     # ids 1..N dans l'ordre d'insertion
        for s in sims:
            if _naive(s.created) > cut:
                continue
            st = state[s.pid]
            if s.exploit and day == end_day - timedelta(days=2):
                st["gold"] += 48_000              # or apparu sans mouvement enregistré
                s.gold += 48_000
            lvl = st["level"]
            split = {"dps": [0.7, 0.1, 0.2], "tank": [0.15, 0.45, 0.4], "soutien": [0.45, 0.2, 0.35],
                     "equilibre": [0.34, 0.33, 0.33]}[s.build]
            pts = [round(lvl * x) for x in split]
            spec = ""
            if lvl >= 31:
                spec = {"dps": "Assassin", "tank": "Rempart", "soutien": "Soigneur"}.get(s.build, "")
            classes = ["Guerrier", "Gardien", "Clerc"][: 1 + lvl // 15] + ([spec] if spec else [])
            worn = sorted(st["gear"].items(), key=lambda kv: -order.index(kv[1]))[:7]
            power = int(110 * lvl ** 2.15 * s.strong * rng.uniform(0.9, 1.1) * (1 + 0.08 * len(worn)))
            snapshots.append({
                "day": day, "player_id": s.pid, "taken_at": cut, "level": lvl, "xp_total": st["xp_total"],
                "gold": st["gold"], "power": power, "rank": st["rank"], "kills": st["kills"],
                "combats": st["combats"], "wins": st["wins"], "gold_earned": st["earned"],
                "data": json.dumps({"eid": eid, "pts": pts, "free": [rng.choice([0, 0, 0, 1, 12]), 0], "classes": classes,
                                    "spec": spec, "tactic": rng.choice(["pragmatique", "egoiste", "egoiste", "all_in"]),
                                    "panoplie": rng.choice(["attack", "attack", "defense", "max_hp", "crit_chance"]),
                                    "gear": [[c, r] for c, r in worn], "tree": lvl, "tower": st["tower"]},
                                   separators=(",", ":")),
            })
            xp_of[s.pid] = (lvl, st)
        day += timedelta(days=1)

    with get_db_session() as session:
        session.bulk_insert_mappings(PlayerDailySnapshotModel, snapshots)
        for s in sims:
            lvl, st = xp_of.get(s.pid, (1, state[s.pid]))
            prog = session.get(PlayerProgressionModel, s.pid)
            prog.level, prog.xp = s.level, s.xp
            split = {"dps": [0.7, 0.1, 0.2], "tank": [0.15, 0.45, 0.4], "soutien": [0.45, 0.2, 0.35],
                     "equilibre": [0.34, 0.33, 0.33]}[s.build]
            prog.points_attack, prog.points_defense, prog.points_max_hp = (round(s.level * x) for x in split)
            prog.stat_points = 14 if s.pid % 11 == 0 else 0
            session.get(PlayerResourceModel, s.pid).gold = s.gold
            career = session.get(PlayerCareerStatsModel, s.pid)
            if career is None:
                career = PlayerCareerStatsModel(player_id=s.pid)
                session.add(career)
            career.combats_fought, career.combats_won = s.combats, s.wins
            career.combats_lost, career.gold_earned_total = s.combats - s.wins, s.gold_earned
            last = s.sessions[-1][1] if s.sessions else _naive(s.created)
            session.execute(update(PlayerModel).where(PlayerModel.id == s.pid).values(last_seen_at=last))
            for slot, (code, rarity) in zip(["arme_1", "corps", "tete", "accessoire_1", "accessoire_2", "arme_2",
                                             "accessoire_3"], sorted(s.gear.items(), key=lambda kv: -order.index(kv[1]))):
                if code in item_ids:
                    session.add(PlayerGearModel(player_id=s.pid, item_definition_id=item_ids[code], rarity=rarity,
                                                forge_level=0, equipped_slot=slot, source="drop", listed=False))
            for code in rng.sample(tree_codes, min(len(tree_codes), max(1, s.level // 2))):
                session.add(PlayerSkillAllocationModel(player_id=s.pid, skill_code=code, level=1))
        session.commit()
    _ = total_xp, by_pid, times
    print("Démo prête.")


if __name__ == "__main__":
    main()
