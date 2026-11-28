"""Image et VIDÉO d'un combat de zone : scène, rendu (file `render_queue`),
lecture dans le message du monstre. Méthodes d'`EncounterCog` (mixin), sorties
d'`encounter_cog.py` le 28/11/2026 (audit) : texte inchangé."""

import asyncio
import logging
import discord
from app.bot.embeds.encounter_embeds import (
    build_encounter_embed,
)
from app.bot.rendering.fight_scene import compose_players_banner
from app.bot.rendering.render_queue import video_slot
from app.domain.value_objects.stats import Stats
from app.shared.paths import (
    LANDSCAPES_ASSETS_DIR,
)
from app.bot.rendering.fight_animation import MAX_UPLOAD_BYTES as _VIDEO_MAX_BYTES
_logger = logging.getLogger("app.bot.cogs.encounter_cog")


class EncounterVideoMixin:
    def _scene_inputs(self, channel_id: int, encounter) -> tuple[dict | None, dict | None]:
        """(spot, placement) pour le rendu : décor du couple (zone, élément
        spawné) + placement propre au monstre. None/None → rendu automatique."""
        from app.infrastructure.encounters import farm_zone_loader, mob_placement_loader
        element = getattr(encounter.mob_state, "element", "") or ""
        spot = farm_zone_loader.get_spot(channel_id, element) if element else None
        placement = mob_placement_loader.get_placement(encounter.mob_state.code, element)
        return spot, placement

    def _mob_payload(self, state: dict, element: str) -> dict:
        """Monstre à dessiner (état d'un tour ou du spawn) + élément + puissance."""
        payload = dict(state)
        payload["element"] = element
        payload["power_score"] = self.power_score_service.format_score(
            self.power_score_service.calculate_from_stats(Stats(
                max_hp=payload["max_hp"], attack=payload["attack"], defense=payload["defense"],
                crit_chance=payload.get("crit_chance", 0), crit_damage=payload.get("crit_damage", 100),
                dodge=payload.get("dodge", 0), hp_regeneration=payload.get("hp_regeneration", 0),
                speed=payload.get("speed", 1),
            )))
        return payload

    def _render_kwargs(self, channel_id: int, encounter, turn_log=None) -> dict:
        """Arguments de rendu de la scène : un monstre (`mob`, `placement`) ou
        une meute (`mobs`, `placements`, `formation` de la zone). `turn_log` :
        l'état d'un tour du combat, sinon celui du spawn."""
        from app.infrastructure.encounters import mob_formation_loader, mob_placement_loader

        element = encounter.mob_state.element
        spot, placement = self._scene_inputs(channel_id, encounter)
        if turn_log is not None:
            states = turn_log.enemies_state or [turn_log.mob_state]
        else:
            states = [{
                "code": m.code, "name": m.name, "image_name": m.image_name,
                "current_hp": m.current_hp, "max_hp": m.max_hp, "attack": m.attack,
                "defense": m.defense, "speed": m.speed, "crit_chance": m.crit_chance,
                "crit_damage": m.crit_damage, "dodge": m.dodge, "hp_regeneration": m.hp_regeneration,
            } for m in encounter.mobs]
        payloads = [self._mob_payload(s, element) for s in states]
        # Chiffres de dégâts et effets de l'action (cf. combat_fx).
        fx = {"events": turn_log.events, "fx_seed": turn_log.turn_number} if turn_log is not None else {}
        if len(payloads) == 1:
            payloads[0]["code"] = encounter.mob_state.code
            return {"mob": payloads[0], "spot": spot, "placement": placement, **fx}
        return {
            "mob": None, "spot": spot, "mobs": payloads, **fx,
            "placements": [mob_placement_loader.get_placement(p.get("code"), element) for p in payloads],
            "formation": mob_formation_loader.get_formation(str(channel_id), len(payloads)),
        }

    def _render_fight_video(self, channel_id: int, encounter, result, background_path):
        """Le GIF du combat (cf. `fight_animation`), ou None si le rendu
        échoue ou dépasse la taille d'un envoi Discord même réduit."""
        from app.application.services.encounter_service import EncounterService
        from app.bot.rendering.fight_animation import WIDTH, animate_fight
        from app.bot.rendering.fight_scene import build_scene

        if not result.turn_logs:
            return None
        first = result.turn_logs[0]
        players = [dict(p) for p in first.players_state]
        by_user = {p.user_id: p for p in encounter.participants.values()}
        start_players = {}
        for p in players:
            part = by_user.get(p.get("user_id"))
            start = (EncounterService._scaled_hp(part.current_hp, part.max_hp, p["max_hp"])
                     if part is not None else p["current_hp"])
            start_players[f"p{p['player_id']}"] = (start, p["max_hp"])
        kwargs = self._render_kwargs(channel_id, encounter)
        scene = build_scene(players=players, background_path=str(background_path),
                            **{k: v for k, v in kwargs.items() if k in (
                                "mob", "spot", "placement", "mobs", "placements", "formation")})
        first_enemies = first.enemies_state or [first.mob_state]
        start_enemies = {
            f"e{i}": (m.current_hp, m.max_hp, int((first_enemies[i] if i < len(first_enemies) else {})
                                                   .get("shield", 0) or 0))
            for i, m in enumerate(encounter.mobs)
        }
        out = self.generated_dir / f"encounter_{encounter.message_id}_combat.gif"
        for width in (WIDTH, 440):
            anim = animate_fight(scene, start_enemies, start_players, result.turn_logs, out, width=width)
            if anim.size_bytes <= _VIDEO_MAX_BYTES:
                return anim
        out.unlink(missing_ok=True)
        return None

    async def _play_fight_video(self, channel_id: int, encounter, message, result, background_path) -> None:
        """Joue la vidéo du combat dans le message du monstre, le temps qu'elle
        dure (best effort : sans vidéo, on passe directement au récapitulatif)."""
        try:
            await message.edit(embed=discord.Embed(
                title=f"⚔️ Le combat s'engage — {encounter.mob_names}",
                description="_Les coups pleuvent…_", color=discord.Color.orange()), view=None)
        except discord.HTTPException:
            pass
        try:
            # Une vidéo à la fois (mémoire) ; file trop longue ⇒ récapitulatif direct.
            async with video_slot() as granted:
                if not granted:
                    _logger.warning("file des vidéos trop longue : combat sans vidéo")
                    return
                anim = await asyncio.to_thread(self._render_fight_video, channel_id, encounter, result,
                                               background_path)
        except Exception:
            _logger.exception("vidéo du combat échouée")
            return
        if anim is None:
            return
        embed = discord.Embed(title=f"⚔️ {encounter.mob_names}", color=discord.Color.orange())
        embed.set_image(url=f"attachment://{anim.path.name}")
        try:
            await message.edit(embed=embed, attachments=[discord.File(anim.path, filename=anim.path.name)],
                               view=None)
            await asyncio.sleep(anim.duration_s + 1.0)
        except discord.HTTPException:
            _logger.warning("envoi de la vidéo du combat échoué", exc_info=True)
        finally:
            anim.path.unlink(missing_ok=True)   # Discord garde sa copie

    async def refresh_encounter_scene(self, channel_id: int) -> None:
        encounter = self.active_encounters.get(channel_id)
        if encounter is None or encounter.message_id is None:
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return

        try:
            message = await channel.fetch_message(encounter.message_id)
        except discord.NotFound:
            return

        players = [
            {
                "name": participant.display_name,
                "avatar_url": participant.avatar_url,
                "current_hp": participant.current_hp,
                "max_hp": participant.max_hp,
                "attack": participant.stats.attack,
                "defense": participant.stats.defense,
                "speed": participant.stats.speed,
                "crit_chance": participant.stats.crit_chance,
                "crit_damage": participant.stats.crit_damage,
                "dodge": participant.stats.dodge,
                "hp_regeneration": participant.stats.hp_regeneration,
            }
            for participant in encounter.participants.values()
        ]

        filename = f"encounter_{encounter.message_id}_current.jpg"
        output_full = self.generated_dir / filename
        output_relative = f"generated_encounters/{filename}"
        background_path = self._zone_bg.get(
            channel_id, str(LANDSCAPES_ASSETS_DIR / "clairiere_sinistre.png")
        )

        players_stats_for_score = [
            Stats(
                max_hp=player["max_hp"],
                attack=player.get("attack", 1),
                defense=player.get("defense", 0),
                crit_chance=player.get("crit_chance", 0),
                crit_damage=player.get("crit_damage", 100),
                dodge=player.get("dodge", 0),
                hp_regeneration=player.get("hp_regeneration", 0),
                speed=player.get("speed", 1),
            )
            for player in players
        ]

        players_power_score = self.power_score_service.calculate_and_format_party_score(
            players_stats_for_score
        ) if players_stats_for_score else "0"

        await asyncio.to_thread(
            compose_players_banner,
            players=players,
            output_path=str(output_full),
            background_path=str(background_path),
            players_power_score=players_power_score,
            **self._render_kwargs(channel_id, encounter),
        )

        embed, file = build_encounter_embed(
            image_name=output_relative,
        )
        embed.description = self._spawn_description(encounter)

        await message.edit(embed=embed, attachments=[file])
