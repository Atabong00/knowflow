from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.auth.dependencies import require_user, AuthenticatedUser
from app.models.category import Category
from app.models.document import Document
from app.utils import Paginator

router = APIRouter(tags=["Dashboard"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/dashboard")
def dashboard(
    request: Request,
    page: int = 1,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Renders the dashboard. Restricts access to authenticated users only."""
    # Retrieve all categories
    db_categories = db.query(Category).order_by(Category.name).all()

    # Bulk count documents per category to avoid N+1 queries
    category_counts = dict(
        db.query(Document.category_id, func.count(Document.id))
        .filter(Document.status == "published", Document.category_id.isnot(None))
        .group_by(Document.category_id)
        .all()
    )

    categories = [
        {
            "name": cat.name,
            "slug": cat.slug,
            "document_count": category_counts.get(cat.id, 0)
        }
        for cat in db_categories
    ]

    # Retrieve recently updated published documents with pagination
    recent_query = db.query(Document).filter(
        Document.status == "published"
    ).order_by(Document.updated_at.desc())
    
    paginator = Paginator(page=page, per_page=5)
    recent_pagination = paginator.paginate(recent_query)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "categories": categories,
            "recent_documents": recent_pagination["items"],
            "recent_pagination": recent_pagination,
            "active_page": "dashboard"
        }
    )
