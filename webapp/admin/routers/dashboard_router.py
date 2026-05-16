"""Routes du dashboard admin (home + stubs des entités à venir)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from webapp.admin.auth import AdminUser, require_admin


router = APIRouter(prefix="/admin", tags=["admin-dashboard"])


def get_templates():
    from webapp.main import templates
    return templates


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, user: AdminUser = Depends(require_admin),
):
    """Page d'accueil de l'admin : grille des entités gérables.

    V1 : seuls Items et Mobs sont actifs. Les autres sont des stubs
    qui mènent à une page 'À venir' pour matérialiser le périmètre.
    """
    from app.infrastructure.db.repositories.item_repository import ItemRepository
    from app.infrastructure.db.repositories.mob_repository import MobRepository
    from app.infrastructure.db.session import get_db_session

    with get_db_session() as session:
        items_count = len(ItemRepository(session).list_all())
        mobs_count = len(MobRepository(session).list_all())

    return get_templates().TemplateResponse(
        request, "admin/dashboard.html",
        context={
            "user": user,
            "items_count": items_count,
            "mobs_count": mobs_count,
        },
    )


# Stubs pour les entités non encore implémentées en V1
_STUB_ENTITIES = [
    ("classes", "🧬 Classes", "Les classes de personnage et leurs bonus."),
    ("crafts", "🛠️ Recettes", "Les recettes de craft et de forge."),
    ("skill-tree", "🌳 Arbre de compétences", "Les nœuds, prérequis, effets."),
    ("panoplies", "🌸 Panoplies", "Les sets (iron, slime, gobelin, …)."),
    ("titles", "🏷️ Titres", "Les titres exclusifs et débloquables."),
    ("quests", "📜 Quêtes", "Quêtes quotidiennes et hebdomadaires."),
    ("world-bosses", "🐉 World Bosses", "Définitions et modifiers."),
    ("shop", "🏪 Shop", "Items vendus + prix dynamique."),
    ("actions", "⚡ Actions admin", "give_gold, reset_player, spawn_encounter…"),
    ("players", "👥 Joueurs", "Voir / modifier les profils."),
]


@router.get("/{slug}", response_class=HTMLResponse)
async def stub_page(
    slug: str, request: Request,
    user: AdminUser = Depends(require_admin),
):
    """Page 'À venir' pour toutes les entités non encore CRUD."""
    label_desc = next(
        ((label, desc) for s, label, desc in _STUB_ENTITIES if s == slug),
        None,
    )
    if label_desc is None:
        # Pas un stub connu → on laisse FastAPI renvoyer 404 via le
        # mécanisme normal (route non matchée par les vrais routers).
        from fastapi import HTTPException, status
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    label, description = label_desc
    return get_templates().TemplateResponse(
        request, "admin/stub.html",
        context={
            "user": user,
            "entity_label": label,
            "entity_description": description,
        },
    )
