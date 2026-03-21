from app.infrastructure.db.session import get_db_session
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


def main() -> None:
    discord_id = 701782195844546662  # remplace par ton vrai discord id si besoin

    with get_db_session() as session:
        player_repository = PlayerRepository(session)
        item_repository = ItemRepository(session)
        inventory_repository = InventoryRepository(session)

        profile = player_repository.get_by_discord_id(discord_id)
        if profile is None:
            print("Player introuvable.")
            return

        item = item_repository.get_by_code("slime_gel")
        if item is None:
            item = item_repository.create(
                code="slime_gel",
                name="Gelée de Slime",
                description="Une matière gélatineuse récupérée sur un slime.",
                category="resource",
                rarity="common",
                stackable=True,
                sell_price=2,
            )

        inventory_repository.add_item(
            player_id=profile.player.id,
            item_definition_id=item.id,
            quantity=5,
        )
        
        print("Item ajouté à l'inventaire.")
        
        item = item_repository.get_by_code("wood_sword")
        if item is None:
            item = item_repository.create(
                code="wood_sword",
                name="Épée en bois",
                description="Une arme basique pour débuter.",
                category="weapon",
                rarity="common",
                stackable=False,
                sell_price=5,
            )

        inventory_repository.add_item(
            player_id=profile.player.id,
            item_definition_id=item.id,
            quantity=1,
        )

        print("épée ajoutée à l'inventaire.")


if __name__ == "__main__":
    main()