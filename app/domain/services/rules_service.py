"""Règlement du serveur (07/11/2026, demande de l'auteur : on accepte le
règlement avant d'avoir accès au bot).

Le texte vit dans `rules.json` ; ici, les règles pures : qui doit (ré)accepter,
et ce que Discord accepte d'afficher.

Version : on ne l'augmente que pour un changement IMPORTANT. Tout joueur dont
la version acceptée est plus ancienne doit alors accepter à nouveau ; une
coquille corrigée sans changer la version ne redemande rien.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Limites d'un embed Discord.
FIELD_VALUE_MAX = 1024
FIELD_NAME_MAX = 256
TITLE_MAX = 256
DESCRIPTION_MAX = 4096
FOOTER_MAX = 2048
FIELDS_MAX = 25
#: Total d'un embed (titre, description, champs, pied), avec une marge pour
#: le numéro de version et la date ajoutés au pied.
EMBED_TOTAL_MAX = 6000 - 200


@dataclass(frozen=True)
class RuleSection:
    emoji: str
    title: str
    rules: tuple[str, ...]

    @property
    def heading(self) -> str:
        return f"{self.emoji} {self.title}".strip()

    @property
    def body(self) -> str:
        return "\n".join(f"• {rule}" for rule in self.rules)


@dataclass(frozen=True)
class Rules:
    version: int
    updated: str                     # date ISO de la dernière version
    title: str
    intro: str
    sections: tuple[RuleSection, ...] = field(default_factory=tuple)
    footer: str = ""


def needs_acceptance(accepted_version: int | None, rules: Rules) -> bool:
    """Vrai tant que le joueur n'a pas accepté cette version (ou une plus récente)."""
    return accepted_version is None or accepted_version < rules.version


def validate(rules: Rules) -> list[str]:
    """Les problèmes qui empêcheraient Discord d'afficher le règlement."""
    problems = []
    if rules.version < 1:
        problems.append("La version doit valoir au moins 1.")
    if not rules.title.strip():
        problems.append("Le titre est vide.")
    if len(rules.title) > TITLE_MAX:
        problems.append(f"Titre trop long ({len(rules.title)} > {TITLE_MAX}).")
    if len(rules.intro) > DESCRIPTION_MAX:
        problems.append(f"Introduction trop longue ({len(rules.intro)} > {DESCRIPTION_MAX}).")
    if not rules.sections:
        problems.append("Aucune section.")
    if len(rules.sections) > FIELDS_MAX:
        problems.append(f"Trop de sections ({len(rules.sections)} > {FIELDS_MAX}).")
    for section in rules.sections:
        if not section.rules:
            problems.append(f"Section « {section.title} » sans règle.")
        if len(section.heading) > FIELD_NAME_MAX:
            problems.append(f"Titre de section trop long : « {section.title[:40]}… ».")
        if len(section.body) > FIELD_VALUE_MAX:
            problems.append(f"Section « {section.title} » trop longue ({len(section.body)} > {FIELD_VALUE_MAX}).")
    if len(rules.footer) > FOOTER_MAX - 80:
        problems.append("Pied de page trop long.")
    total = (len(rules.title) + len(rules.intro) + len(rules.footer)
             + sum(len(s.heading) + len(s.body) for s in rules.sections))
    if total > EMBED_TOTAL_MAX:
        problems.append(f"Règlement trop long pour un message ({total} > {EMBED_TOTAL_MAX} caractères).")
    return problems
