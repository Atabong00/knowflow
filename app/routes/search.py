from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.auth.dependencies import require_user, AuthenticatedUser
from app.models.document import Document
from app.models.category import Category
from app.utils import Paginator

router = APIRouter(prefix="/search", tags=["Search"])
templates = Jinja2Templates(directory="app/templates")

@router.get("")
def search_documentation(
    request: Request,
    q: str = "",
    category_id: int = None,
    page: int = 1,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """
    Search database for documents containing the search term.
    Uses case-insensitive ILIKE filters on title and content.
    """
    categories = db.query(Category).order_by(Category.name).all()
    results = []
    pagination = None

    # Execute search only if query is not empty
    if q.strip():
        query = db.query(Document).filter(Document.status == "published")

        # Build search criteria matching title OR content
        term_filter = (Document.title.ilike(f"%{q}%") | Document.content.ilike(f"%{q}%"))
        query = query.filter(term_filter)

        # Apply category filter if specified
        if category_id and category_id > 0:
            query = query.filter(Document.category_id == category_id)

        paginator = Paginator(page=page, per_page=20)
        pagination = paginator.paginate(query.order_by(Document.title))
        results = pagination["items"]

    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "request": request,
            "user": user,
            "q": q,
            "category_id": category_id,
            "categories": categories,
            "results": results,
            "pagination": pagination,
            "active_page": "search"
        }
    )
