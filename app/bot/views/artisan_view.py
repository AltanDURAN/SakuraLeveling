"""Écran d'un artisan : portrait, menus en cascade, boutons d'action.

Le joueur ne tape jamais de code. Il choisit une CATÉGORIE, puis un OBJET ;
la fiche se met à jour à chaque choix et le bouton d'action ne s'active que
si le travail est réellement possible.

Tout le rendu Pillow passe par `asyncio.to_thread` — règle du projet : jamais
d'image générée dans la boucle d'événements.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC

import discord

from app.bot.rendering.npc_panel import compose_npc_panel, panel_path
from app.domain.entities.artisan import ArtisanDefinition
from app.infrastructure.db.models.work_order_model import STATUS_READY
from app.shared.enums import CATEGORY_ICONS, ITEM_CATEGORY_LABELS
from app.shared.formatters import format_int


def _category_label(category: str) -> str:
    icon = CATEGORY_ICONS.get(category, "📦")
    return f"{icon} {ITEM_CATEGORY_LABELS.get(category, category)}"


def _duration_label(seconds: int) -> str:
    if seconds <= 0:
        return "immédiat"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d}"
    return f"{minutes} min" if minutes else f"{sec} s"


class ArtisanView(discord.ui.View):
    """Vue éphémère (par joueur) d'un artisan."""

    def __init__(
        self,
        *,
        definition: ArtisanDefinition,
        player_id: int,
        session_factory,
        use_case_factory,
        artisan_service,
        upgrade_factory=None,
        channel_id: int = 0,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.definition = definition
        self.player_id = player_id
        self._session_factory = session_factory
        self._use_case_factory = use_case_factory
        self._upgrade_factory = upgrade_factory
        self.artisans = artisan_service
        self.channel_id = channel_id

        # Deux modes : « fabriquer » (commandes) et « améliorer » (fusion).
        self.mode = "craft"
        self.upgrade_code: str | None = None
        self._upgrade_candidates: list = []
        self._upgrade_preview = None

        self.category: str | None = None
        self.recipe_code: str | None = None
        self._recipes_by_category: dict[str, list] = {}
        self._preview = None
        self._active_order = None
        self._orders_completed = 0

        self._build_components()

    # ------------------------------------------------------------ données --
    def refresh_data(self) -> None:
        """Recharge recettes, commande en cours et maîtrise depuis la base."""
        with self._session_factory() as session:
            use_case = self._use_case_factory(session)
            recipes = use_case.recipes_for(self.definition)

            grouped: dict[str, list] = {}
            for recipe in recipes:
                item = use_case.items.get_by_code(recipe.result_item_code)
                if item is None:
                    continue
                grouped.setdefault(item.category, []).append((recipe, item))
            for entries in grouped.values():
                entries.sort(key=lambda pair: pair[1].name.lower())
            self._recipes_by_category = grouped

            self._orders_completed = use_case.orders.orders_completed(
                self.player_id, self.definition.code,
            )
            order = use_case.orders.get_active(self.player_id, self.definition.code)
            self._active_order = self._describe_order(session, order, use_case)

            if self.category and self.category not in grouped:
                self.category = None
                self.recipe_code = None
            if self.recipe_code:
                self._preview = use_case.preview(
                    self.definition, self.player_id, self.recipe_code,
                )
            else:
                self._preview = None

            if self._upgrade_factory is not None:
                upgrades = self._upgrade_factory(session)
                self._upgrade_candidates = upgrades.candidates(
                    self.definition, self.player_id,
                )
                codes = {c.item_code for c in self._upgrade_candidates}
                if self.upgrade_code not in codes:
                    self.upgrade_code = None
                self._upgrade_preview = (
                    upgrades.preview(self.definition, self.player_id, self.upgrade_code)
                    if self.upgrade_code else None
                )

    def _describe_order(self, session, order, use_case) -> dict | None:
        if order is None:
            return None
        item = use_case.items.get_by_id(order.result_item_definition_id)
        now = datetime.now(UTC)
        started = order.started_at
        ready_at = order.ready_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if ready_at.tzinfo is None:
            ready_at = ready_at.replace(tzinfo=UTC)

        total = max(1.0, (ready_at - started).total_seconds())
        elapsed = (now - started).total_seconds()
        ready = order.status == STATUS_READY or now >= ready_at
        remaining = max(0, int((ready_at - now).total_seconds()))
        return {
            "id": order.id,
            "item_name": item.name if item else order.recipe_code,
            "progress": 1.0 if ready else max(0.0, min(1.0, elapsed / total)),
            "ready": ready,
            "ready_label": "prêt" if ready else f"dans {_duration_label(remaining)}",
            "ready_at": ready_at,
        }

    # -------------------------------------------------------- composition --
    def _build_components(self) -> None:
        self.clear_items()
        if self.mode == "upgrade":
            if self._upgrade_candidates:
                self.add_item(_UpgradeSelect(self, self._upgrade_candidates))
            preview = self._upgrade_preview
            self.add_item(_FuseButton(self, enabled=bool(preview and preview.can_upgrade)))
            self.add_item(_ModeButton(self))
            self.add_item(_CloseButton(self))
            return

        categories = sorted(self._recipes_by_category)
        if categories:
            self.add_item(_CategorySelect(self, categories))
        if self.category:
            entries = self._recipes_by_category.get(self.category, [])
            if entries:
                self.add_item(_RecipeSelect(self, entries))

        order = self._active_order
        if order is not None:
            self.add_item(_CollectButton(self, enabled=order["ready"]))
            self.add_item(_CancelButton(self))
        else:
            can = bool(self._preview and self._preview.can_start)
            self.add_item(_StartButton(self, enabled=can))
        if self._upgrade_factory is not None:
            self.add_item(_ModeButton(self))
        self.add_item(_CloseButton(self))

    def _upgrade_info_rows(self) -> list[tuple[str, str]]:
        from app.domain.services.item_upgrade_service import MAX_ITEM_LEVEL

        fusable = sum(1 for c in self._upgrade_candidates if c.owned >= 2)
        return [
            ("Amélioration", f"+10 % des bonus de la pièce par niveau, jusqu'à +{MAX_ITEM_LEVEL}"),
            ("Il lui faut", "une copie identique de la pièce, qu'il fusionne"),
            ("Pièces possédées", f"{len(self._upgrade_candidates)} · {fusable} en double"),
            ("Forge sacrée", "offre aussi un niveau gratuit quand elle s'allume"),
        ]

    def _info_rows(self) -> list[tuple[str, str]]:
        tier = self.artisans.tier_for(self.definition, self._orders_completed)
        cats = " · ".join(
            _category_label(c) for c in self.definition.categories
        )
        total = sum(len(v) for v in self._recipes_by_category.values())
        reachable = 0
        for entries in self._recipes_by_category.values():
            for _, item in entries:
                power = self._power_of(item)
                if tier.accepts_power(power):
                    reachable += 1
        ceiling = (
            f"puissance ≤ {tier.max_item_power}"
            if tier.max_item_power
            else "aucune limite de puissance"
        )
        discount = (
            f"−{tier.gold_discount_pct} % d'or"
            if tier.gold_discount_pct
            else "pas de remise"
        )
        return [
            ("Il travaille", cats),
            ("À ce palier", f"{ceiling} · {discount}"),
            ("Recettes accessibles", f"{reachable} sur {total}" if total else "aucune"),
            ("Sa règle", f"une {self.definition.work_noun} à la fois"),
        ]

    def _power_of(self, item) -> int:
        from app.domain.services.item_power_service import ItemPowerService

        return ItemPowerService().marginal_power(item.stat_bonuses)

    def _upgrade_payload(self) -> dict | None:
        p = self._upgrade_preview
        if p is None:
            return None
        return {
            "kind": "upgrade",
            "item_code": p.item_code,
            "item_name": f"{p.item_name}  +{p.level}",
            "category_label": ITEM_CATEGORY_LABELS.get(p.item_category, p.item_category),
            "result_quantity": 1,
            "bonuses_now": p.bonuses_now,
            "bonuses_next": p.bonuses_next,
            "ingredients": [{
                "name": "copie identique fusionnée",
                "required": p.required,
                "owned": p.owned,
            }],
            "gold_cost": p.gold_cost,
            "can_afford": p.can_afford,
            "level": p.level,
            "maxed": p.maxed,
            "blocking_reason": p.blocking_reason,
        }

    def _selection_payload(self) -> dict | None:
        if self.mode == "upgrade":
            return self._upgrade_payload()
        preview = self._preview
        if preview is None:
            return None
        return {
            "item_code": preview.item_code,
            "item_name": preview.item_name,
            "category_label": ITEM_CATEGORY_LABELS.get(
                preview.item_category, preview.item_category,
            ),
            "result_quantity": preview.result_quantity,
            "stat_bonuses": preview.stat_bonuses,
            "ingredients": [
                {
                    "name": i.item_name,
                    "required": i.required,
                    "owned": i.owned,
                }
                for i in preview.ingredients
            ],
            "gold_cost": preview.quote.gold_cost,
            "duration_s": preview.quote.duration_seconds,
            "item_power": preview.quote.item_power,
            "can_afford": preview.can_afford,
            "blocking_reason": preview.blocking_reason,
        }

    async def render(self) -> tuple[discord.Embed, discord.File]:
        tier = self.artisans.tier_for(self.definition, self._orders_completed)
        path = panel_path(self.definition.code, self.player_id)
        selection = self._selection_payload()
        await asyncio.to_thread(
            compose_npc_panel,
            path,
            npc_name=self.definition.name,
            npc_title=self.definition.title,
            image_name=self.definition.image,
            accent=self.definition.accent,
            greeting=tier.quote or self.definition.greeting,
            tier_name=tier.name,
            tier_level=tier.level,
            tier_total=len(self.definition.tiers),
            tier_progress=self.artisans.tier_progress(
                self.definition, self._orders_completed,
            ),
            orders_completed=self._orders_completed,
            orders_to_next=self.artisans.orders_until_next_tier(
                self.definition, self._orders_completed,
            ),
            selection=selection,
            info_rows=(
                None if selection is not None
                else self._upgrade_info_rows() if self.mode == "upgrade"
                else self._info_rows()
            ),
            active_order=(
                self._active_order
                if selection is None and self.mode == "craft" else None
            ),
            seed=self.player_id,
        )
        filename = path.rsplit("/", 1)[-1]
        embed = discord.Embed(color=discord.Color.from_rgb(*self.definition.accent))
        embed.set_image(url=f"attachment://{filename}")
        return embed, discord.File(path, filename=filename)

    async def refresh(self, interaction: discord.Interaction) -> None:
        await asyncio.to_thread(self.refresh_data)
        self._build_components()
        embed, file = await self.render()
        await interaction.response.edit_message(
            embed=embed, attachments=[file], view=self,
        )


# --------------------------------------------------------------- éléments --
class _CategorySelect(discord.ui.Select):
    def __init__(self, view: ArtisanView, categories: list[str]) -> None:
        options = [
            discord.SelectOption(
                label=ITEM_CATEGORY_LABELS.get(c, c),
                value=c,
                emoji=CATEGORY_ICONS.get(c),
                description=f"{len(view._recipes_by_category[c])} recette(s)",
                default=(c == view.category),
            )
            for c in categories[:25]
        ]
        super().__init__(placeholder="1️⃣  Choisis une catégorie", options=options)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._owner.category = self.values[0]
        self._owner.recipe_code = None
        await self._owner.refresh(interaction)


class _RecipeSelect(discord.ui.Select):
    def __init__(self, view: ArtisanView, entries: list) -> None:
        options = []
        for recipe, item in entries[:25]:
            power = view._power_of(item)
            tier = view.artisans.tier_for(view.definition, view._orders_completed)
            quote = view.artisans.quote(
                view.definition, power, view._orders_completed,
            )
            lock = "" if tier.accepts_power(power) else "🔒 "
            options.append(
                discord.SelectOption(
                    label=f"{lock}{item.name}"[:100],
                    value=recipe.code,
                    description=(
                        f"{format_int(quote.gold_cost)} or · "
                        f"{_duration_label(quote.duration_seconds)} · "
                        f"puissance {power}"
                    )[:100],
                    default=(recipe.code == view.recipe_code),
                )
            )
        super().__init__(placeholder="2️⃣  Choisis un objet", options=options)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._owner.recipe_code = self.values[0]
        await self._owner.refresh(interaction)


class _StartButton(discord.ui.Button):
    def __init__(self, view: ArtisanView, enabled: bool) -> None:
        super().__init__(
            label=f"{view.definition.verb.capitalize()}",
            style=discord.ButtonStyle.success,
            emoji="⚒️",
            disabled=not enabled,
            row=2,
        )
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self._owner
        if parent.recipe_code is None:
            await interaction.response.defer()
            return

        def _run():
            with parent._session_factory() as session:
                use_case = parent._use_case_factory(session)
                result = use_case.start(
                    parent.definition,
                    parent.player_id,
                    parent.recipe_code,
                    notify_channel_id=parent.channel_id,
                )
                if result.success:
                    session.commit()
                return result

        result = await asyncio.to_thread(_run)
        if not result.success:
            await interaction.response.send_message(result.message, ephemeral=True)
            return

        parent.recipe_code = None
        parent.category = None
        await parent.refresh(interaction)
        verb = parent.definition.verb
        if result.instant:
            await interaction.followup.send(
                f"⚒️ {parent.definition.name} a terminé sur-le-champ. "
                f"Récupère ton objet.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"⚒️ {parent.definition.name} se met à {verb}. "
                f"Reviens dans **{_duration_label(result.ready_in_seconds)}**.",
                ephemeral=True,
            )


class _CollectButton(discord.ui.Button):
    def __init__(self, view: ArtisanView, enabled: bool) -> None:
        super().__init__(
            label="Récupérer",
            style=discord.ButtonStyle.success,
            emoji="📦",
            disabled=not enabled,
            row=2,
        )
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self._owner

        def _run():
            with parent._session_factory() as session:
                use_case = parent._use_case_factory(session)
                result = use_case.collect(parent.definition, parent.player_id)
                if result.success:
                    session.commit()
                return result

        result = await asyncio.to_thread(_run)
        if not result.success:
            await interaction.response.send_message(result.message, ephemeral=True)
            return
        await parent.refresh(interaction)
        await interaction.followup.send(
            f"📦 Récupéré ! {parent.definition.name} range ses outils.",
            ephemeral=True,
        )


class _CancelButton(discord.ui.Button):
    def __init__(self, view: ArtisanView) -> None:
        super().__init__(
            label="Annuler le travail",
            style=discord.ButtonStyle.danger,
            row=2,
        )
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self._owner

        def _run():
            with parent._session_factory() as session:
                use_case = parent._use_case_factory(session)
                result = use_case.cancel(parent.definition, parent.player_id)
                if result.success:
                    session.commit()
                return result

        result = await asyncio.to_thread(_run)
        await parent.refresh(interaction)
        await interaction.followup.send(result.message, ephemeral=True)


class _CloseButton(discord.ui.Button):
    def __init__(self, view: ArtisanView) -> None:
        super().__init__(label="Fermer", style=discord.ButtonStyle.secondary, row=2)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        for child in self._owner.children:
            child.disabled = True
        await interaction.response.edit_message(view=self._owner)
        self._owner.stop()


# ------------------------------------------------------------ amélioration --
class _ModeButton(discord.ui.Button):
    """Bascule entre « fabriquer » et « améliorer »."""

    def __init__(self, view: ArtisanView) -> None:
        upgrading = view.mode == "upgrade"
        super().__init__(
            label=view.definition.verb.capitalize() if upgrading else "Améliorer",
            emoji="⚒️" if upgrading else "🔨",
            style=discord.ButtonStyle.primary,
            row=2,
        )
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self._owner
        parent.mode = "craft" if parent.mode == "upgrade" else "upgrade"
        parent.upgrade_code = None
        await parent.refresh(interaction)


class _UpgradeSelect(discord.ui.Select):
    def __init__(self, view: ArtisanView, candidates: list) -> None:
        # Les pièces fusionnables d'abord : c'est ce que le joueur cherche.
        ordered = sorted(candidates, key=lambda c: (c.owned < 2, c.item_name.lower()))
        options = [
            discord.SelectOption(
                label=f"{c.item_name}  +{c.level}"[:100],
                value=c.item_code,
                emoji=CATEGORY_ICONS.get(c.category),
                description=(
                    f"{c.owned} exemplaire(s)"
                    + (" · fusion possible" if c.owned >= 2 else " · il en faut 2")
                )[:100],
                default=(c.item_code == view.upgrade_code),
            )
            for c in ordered[:25]
        ]
        super().__init__(placeholder="🔨  Choisis une pièce à améliorer", options=options)
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self._owner.upgrade_code = self.values[0]
        await self._owner.refresh(interaction)


class _FuseButton(discord.ui.Button):
    def __init__(self, view: ArtisanView, enabled: bool) -> None:
        super().__init__(
            label="Fusionner", emoji="✨", style=discord.ButtonStyle.success,
            disabled=not enabled, row=2,
        )
        self._owner = view

    async def callback(self, interaction: discord.Interaction) -> None:
        parent = self._owner
        if parent.upgrade_code is None or parent._upgrade_factory is None:
            await interaction.response.defer()
            return

        def _run():
            with parent._session_factory() as session:
                result = parent._upgrade_factory(session).upgrade(
                    parent.definition, parent.player_id, parent.upgrade_code,
                )
                if result.success:
                    session.commit()
                return result

        result = await asyncio.to_thread(_run)
        if not result.success:
            await interaction.response.send_message(result.message, ephemeral=True)
            return
        await parent.refresh(interaction)
        await interaction.followup.send(result.message, ephemeral=True)
