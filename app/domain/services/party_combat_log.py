"""Le JOURNAL du combat : instantanés, étiquettes des joueurs et événements
dessinés sur la vidéo (pur enregistrement, aucun tirage).

Méthodes de `PartyCombatService` (mixin), sorties de
`party_combat_service.py` le 28/11/2026 (audit) : texte inchangé. L'état
du combat en cours vit sur l'instance (une par combat)."""


from app.domain.value_objects.party_battle_turn_log import PartyBattleTurnLog



class LogMixin:
    def snap(self, action, players=None, focus=None):
        return self._snapshot(self.turns, players or [], action, self.alive_party, self.foes,
                              focus if focus is not None else self._focus(), self._take_events())

    def _focus(self):
        return self._player_target() or self.foes[-1]

    def _tags(self, member) -> str:
        tag = ""
        redirected = member.pop("_redirected", None)
        if redirected:
            tag += f" (🧱 {redirected[0]} encaisse {redirected[1]})"
        if member.pop("_held", False):
            tag += " — tient bon à 1 PV !"
        if member.pop("_ward", False):
            tag += " — 🛡️ coup annulé !"
        if member.pop("_revived", False):
            tag += " — 🧟 revient à la vie !"
        graced = member.pop("_graced", None)
        if graced:
            tag += f" — 😇 relevé par {graced} !"
        if member.pop("_moss", False):
            tag += " — 🌿 la mousse se réveille"
        recoil = member.pop("_recoil_dealt", 0)
        if recoil:
            tag += f" (🔁 {recoil} en contrecoup)"
        mirror = member.pop("_mirror_dealt", 0)
        if mirror:
            tag += f" (🪞 {mirror} renvoyés)"
        return tag + self._dry_note(member)

    def _dry_note(self, member) -> str:
        """« à court de mana », une fois par combat et par joueur."""
        note = ""
        if member.pop("_blood", False):
            note += " — 🩸 pacte de sang"
        ability = member.pop("_dry", None)
        return note + (f" — 💧 à court de mana ({ability})" if ability else "")

    def _emit(self, kind: str, target: str, amount: int = 0, source: str | None = None,
              **extra) -> None:
        """Note un événement de l'action en cours pour l'affichage (chiffres,
        effets) : `kind` hit / crit / dodge / immune / block / heal / shield /
        dot / recoil / mirror / stun / ko / revive / hold / execute / enrage ;
        `target` / `source` = "p<joueur>" ou "e<index de l'ennemi>"."""
        events = getattr(self, "_events", None)
        if events is None:
            return
        event = {"kind": kind, "target": target, "amount": int(amount)}
        if source:
            event["source"] = source
        event.update({k: v for k, v in extra.items() if v not in (None, "", 0)})
        events.append(event)

    def _take_events(self) -> list[dict]:
        events = getattr(self, "_events", None) or []
        self._events = []
        return events

    def _snapshot(self, turns, player_actions, mob_action, alive_party, foes, focus,
                  events: list[dict] | None = None) -> PartyBattleTurnLog:
        """Construit un PartyBattleTurnLog (état complet équipe + ennemis)
        pour un tour. `mob_state` = l'ennemi concerné par l'action (le seul,
        hors meute) ; `enemies_state` = tous, dans l'ordre de la formation."""
        return PartyBattleTurnLog(
            turn_number=turns,
            player_actions=player_actions,
            mob_action=mob_action,
            players_state=[
                {
                    "player_id": member["player_id"],
                    "user_id": member["user_id"],
                    "name": member["name"],
                    "avatar_url": member["avatar_url"],
                    "current_hp": member["hp"],
                    "max_hp": member["max_hp"],
                    "current_mana": member["mana"],
                    "mana_max": member["mana_max"],
                    "attack": member["stats"].attack,
                    "defense": member["stats"].defense,
                    "speed": member["stats"].speed,
                    "crit_chance": member["stats"].crit_chance,
                    "crit_damage": member["stats"].crit_damage,
                    "dodge": member["stats"].dodge,
                    "hp_regeneration": member["stats"].hp_regeneration,
                    "stunned": member.get("stunned", False),
                    "slow": member.get("slow", 0),
                }
                for member in alive_party
            ],
            mob_state=self._enemy_state(focus),
            enemies_state=[self._enemy_state(E) for E in foes] if len(foes) > 1 else [],
            events=events or [],
        )
