"""Plan d'accès aux salons (08/11/2026) : l'accueil et le règlement pour tous
en lecture seule, le tutoriel / la tour / la première zone au Rang F, chaque
zone à son rang, tout le reste aux aventuriers ; seuls @everyone, les rangs et
Aventurier sont touchés, les salons d'équipe jamais."""

from app.bot import access_plan as ap

GUILD = 1000
RANKS = {rank: 10 + i for i, rank in enumerate(ap.RANK_ORDER)}       # F=10 … SSS=18
ADV = 99
STAFF = 500
ROLES = ap.Roles(everyone=GUILD, ranks=RANKS, adventurer=ADV)
VIEW = ap.VIEW_CHANNEL

WELCOME, RULES, TUTO, TOWER, GENERAL, ZONE_F, ZONE_E, ZONE_D, ANNOUNCES, STAFF_ROOM = range(1, 11)
AUDIENCES = ap.channel_audiences(welcome=WELCOME, rules=RULES, tutorial=TUTO, tower=TOWER,
                                 zones=[(ZONE_F, "F"), (ZONE_E, "E"), (ZONE_D, "D")])


def _plan(channel_id: int, current: dict) -> ap.Change | None:
    audience = AUDIENCES.get(channel_id, ap.ADVENTURERS)
    return ap.plan_channel(channel_id, f"salon{channel_id}", "text", current, audience, ROLES)


def _applied(change: ap.Change, current: dict) -> dict:
    after = dict(current)
    for target, overwrite in change.updates:
        if overwrite == ap.EMPTY:
            after.pop(target, None)
        else:
            after[target] = overwrite
    return after


def _ranks_from(rank: str) -> dict:
    start = ap.RANK_ORDER.index(rank)
    return {RANKS[r]: (VIEW, 0) for r in ap.RANK_ORDER[start:]}


def test_chaque_salon_a_son_public():
    assert AUDIENCES[WELCOME] == ap.PUBLIC and AUDIENCES[RULES] == ap.PUBLIC_NO_REACTIONS
    assert AUDIENCES[TUTO] == AUDIENCES[TOWER] == AUDIENCES[ZONE_F] == ap.rank_audience("F")
    assert AUDIENCES[ZONE_E].label == "Rang E et plus" and AUDIENCES[ZONE_D].min_rank == "D"
    assert GENERAL not in AUDIENCES                     # tout le reste : aux aventuriers
    assert ROLES.allowed(ap.rank_audience("F")) == set(RANKS.values())
    assert ROLES.allowed(ap.rank_audience("E")) == set(RANKS.values()) - {RANKS["F"]}


def test_le_general_passe_des_rangs_aux_aventuriers():
    # Aujourd'hui : caché à @everyone, ouvert aux rangs E → SSS (le Rang F oublié).
    current = {GUILD: (0, VIEW), **_ranks_from("E")}
    change = _plan(GENERAL, current)
    assert (change.before, change.after) == ("Rang E et plus", "aventuriers")
    assert change.updates[0] == (ADV, (VIEW, 0))                     # ce qui ouvre d'abord
    assert all(overwrite == ap.EMPTY for target, overwrite in change.updates[1:])
    assert _applied(change, current) == {GUILD: (0, VIEW), ADV: (VIEW, 0)}


def test_un_salon_ouvert_a_tous_se_ferme_aux_aventuriers():
    change = _plan(ANNOUNCES, {})
    assert (change.before, change.after) == ("tout le monde", "aventuriers")
    assert change.updates[-1] == (GUILD, (0, VIEW))                  # @everyone en dernier


def test_tutoriel_tour_et_premiere_zone_au_rang_f():
    tower = _plan(TOWER, {GUILD: (0, VIEW), RANKS["F"]: (VIEW, 0)})   # seul le Rang F la voyait
    assert (tower.before, tower.after) == ("Rang F", "Rang F et plus")
    zone = _plan(ZONE_F, {GUILD: (0, VIEW), **_ranks_from("E")})       # le Rang F ne voyait pas sa zone
    assert (zone.before, zone.after) == ("Rang E et plus", "Rang F et plus")
    assert _plan(TUTO, {}).after == "Rang F et plus"


def test_une_zone_deja_bonne_ne_bouge_pas():
    assert _plan(ZONE_D, {GUILD: (0, VIEW), **_ranks_from("D")}) is None


def test_accueil_et_reglement_en_lecture_seule():
    welcome = _plan(WELCOME, {})
    assert (welcome.before, welcome.after) == ("tout le monde", "tout le monde, lecture seule")
    allow, deny = dict(welcome.updates)[GUILD]
    assert allow & VIEW and deny & ap.WRITE == ap.WRITE and not deny & ap.ADD_REACTIONS   # on y réagit
    # Le règlement : réactions fermées, les autres refus déjà posés gardés.
    manage = 1 << 4
    rules = _plan(RULES, {GUILD: (VIEW, ap.SEND_MESSAGES | manage), RANKS["E"]: (VIEW | ap.SEND_MESSAGES, 0)})
    after = _applied(rules, {GUILD: (VIEW, ap.SEND_MESSAGES | manage), RANKS["E"]: (VIEW | ap.SEND_MESSAGES, 0)})
    assert after[GUILD][1] & (ap.WRITE | ap.ADD_REACTIONS | manage) == ap.WRITE | ap.ADD_REACTIONS | manage
    assert RANKS["E"] not in after                                     # aucun rôle ne rouvre l'écriture


def test_les_autres_roles_et_reglages_sont_gardes():
    attach = 1 << 15
    current = {GUILD: (0, ap.SEND_MESSAGES), STAFF: (VIEW | attach, 0), RANKS["E"]: (VIEW | attach, 0)}
    after = _applied(_plan(GENERAL, current), current)
    assert after[STAFF] == (VIEW | attach, 0)                          # rôle hors parcours : intouché
    assert after[GUILD] == (0, ap.SEND_MESSAGES | VIEW)                # lecture seule gardée
    assert after[RANKS["E"]] == (attach, 0)                            # seul « voir » est retiré
    assert _plan(GENERAL, after) is None                               # une 2e fois : rien


def test_un_salon_d_equipe_n_est_jamais_touche():
    assert ap.is_private({GUILD: (0, VIEW), STAFF: (VIEW, 0)}, ROLES)
    assert ap.is_private({GUILD: (0, VIEW)}, ROLES)                    # caché à tous : archive
    assert not ap.is_private({GUILD: (0, VIEW), RANKS["E"]: (VIEW, 0)}, ROLES)
    assert not ap.is_private({}, ROLES)


def test_on_ne_retire_jamais_un_role_a_un_membre():
    assert ap.roles_to_add(False, True, False, False) == (False, False)   # règlement d'abord
    assert ap.roles_to_add(True, False, False, False) == (True, False)
    assert ap.roles_to_add(True, True, True, False) == (False, True)
    assert ap.roles_to_add(True, True, True, True) == (False, False)
