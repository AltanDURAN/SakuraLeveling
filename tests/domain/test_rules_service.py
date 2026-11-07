"""Règlement (07/11/2026) : qui doit (ré)accepter, et un texte que Discord
peut afficher."""

from app.domain.services.rules_service import (
    EMBED_TOTAL_MAX,
    FIELD_VALUE_MAX,
    RuleSection,
    Rules,
    needs_acceptance,
    validate,
)
from app.infrastructure.rules.rules_loader import get_rules, parse


def _rules(version=2, sections=None):
    sections = sections if sections is not None else (RuleSection("🤝", "Respect", ("Sois courtois.",)),)
    return Rules(version=version, updated="2026-11-07", title="Règlement", intro="Bienvenue.", sections=sections)


def test_on_accepte_une_fois_puis_a_chaque_changement_important():
    rules = _rules(version=2)
    assert needs_acceptance(None, rules)
    assert needs_acceptance(1, rules)            # version plus ancienne : à relire
    assert not needs_acceptance(2, rules)
    assert not needs_acceptance(3, rules)


def test_le_reglement_du_jeu_tient_dans_un_message():
    rules = get_rules()
    assert validate(rules) == []
    assert rules.version >= 1 and len(rules.sections) >= 4
    total = len(rules.title) + len(rules.intro) + sum(len(s.heading) + len(s.body) for s in rules.sections)
    assert total < EMBED_TOTAL_MAX
    text = " ".join(rule for s in rules.sections for rule in s.rules).lower()
    for subject in ("compte", "script", "bug", "argent réel", "discord"):
        assert subject in text, subject


def test_un_reglement_trop_long_ou_vide_est_refuse():
    assert any("sans règle" in p for p in validate(_rules(sections=(RuleSection("⚔️", "Vide", ()),))))
    long = RuleSection("⚔️", "Long", ("x" * (FIELD_VALUE_MAX + 10),))
    assert any("trop longue" in p for p in validate(_rules(sections=(long,))))
    assert any("Aucune section" in p for p in validate(_rules(sections=())))
    assert any("version" in p for p in validate(_rules(version=0)))


def test_lecture_du_fichier():
    rules = parse({"version": 3, "title": "T", "intro": "I",
                   "sections": [{"emoji": "🤝", "title": "Respect", "rules": ["A", "B"]}]})
    assert rules.version == 3 and rules.sections[0].body == "• A\n• B"
    assert rules.sections[0].heading == "🤝 Respect"
