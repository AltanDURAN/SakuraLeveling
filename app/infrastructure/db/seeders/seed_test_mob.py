from app.infrastructure.db.session import get_db_session
from app.infrastructure.db.repositories.mob_repository import MobRepository


def main() -> None:
    with get_db_session() as session:
        mob_repository = MobRepository(session)

        slime = mob_repository.get_by_code("slime")
        if slime is None:
            mob_repository.create(
                code="slime",
                name="Slime",
                description="Une créature gélatineuse faible.",
                max_hp=30,
                attack=6,
                defense=1,
                xp_reward=10,
                gold_reward=5,
                loot_table=[
                    {
                        "item_code": "slime_gel",
                        "drop_rate": 0.75,
                        "min_quantity": 1,
                        "max_quantity": 2,
                    }
                ],
                image_url="https://i.imgur.com/tLYX58K.jpeg"
            )
            print("Slime créé.")
        else:
            print("Slime déjà présent.")


if __name__ == "__main__":
    main()