from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.auth.dependencies import require_user, RoleRequirement, AuthenticatedUser
from app.models.category import Category
from app.models.document import Document
from app.utils import slugify, log_audit, Paginator
from app.core.logging_config import log_business_event, log_error
from app.schemas import CategoryCreate, CategoryUpdate, form_parser

router = APIRouter(prefix="/categories", tags=["Categories"])
templates = Jinja2Templates(directory="app/templates")

# Admin role restriction guard
require_admin = RoleRequirement(allowed_roles=["Admin"])

@router.get("")
def list_categories(
    request: Request,
    page: int = 1,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Lists all active document categories and includes management options for administrators."""
    db_categories_query = db.query(Category).order_by(Category.name)
    paginator = Paginator(page=page, per_page=20)
    pagination = paginator.paginate(db_categories_query)
    db_categories = pagination["items"]
    
    # Bulk count documents per category to avoid N+1 queries
    category_counts = dict(
        db.query(Document.category_id, func.count(Document.id))
        .filter(Document.category_id.isnot(None))
        .group_by(Document.category_id)
        .all()
    )
    
    categories = [
        {
            "id": cat.id,
            "name": cat.name,
            "slug": cat.slug,
            "description": cat.description,
            "document_count": category_counts.get(cat.id, 0)
        }
        for cat in db_categories
    ]

    return templates.TemplateResponse(
        request,
        "categories/list.html",
        {
            "request": request,
            "user": user,
            "categories": categories,
            "pagination": pagination,
            "active_page": "categories"
        }
    )

@router.post("/new")
async def create_category(
    form: CategoryCreate = Depends(form_parser(CategoryCreate)),
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Creates a new category (Administrators only)."""
    name = form.name
    description = form.description
    slug = slugify(name)

    existing = db.query(Category).filter(Category.slug == slug).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Category already exists."
        )

    cat = Category(name=name, slug=slug, description=description)
    db.add(cat)
    db.commit()
    db.refresh(cat)

    log_audit(
        db=db,
        action="CREATE_CATEGORY",
        user_id=user.keycloak_id,
        target_id=cat.id,
        details=f"Created category '{name}' (slug: {slug})"
    )
    log_business_event("category_created", f"name='{name}' slug='{slug}'", user.keycloak_id)

    return RedirectResponse(url="/categories", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/{slug}/edit")
async def edit_category(
    slug: str,
    form: CategoryUpdate = Depends(form_parser(CategoryUpdate)),
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Updates an existing category (Administrators only)."""
    cat = db.query(Category).filter(Category.slug == slug).first()
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")

    old_name = cat.name
    cat.name = form.name if form.name is not None else cat.name
    cat.description = form.description if form.description is not None else cat.description
    cat.slug = slugify(cat.name)
    db.commit()

    log_audit(
        db=db,
        action="UPDATE_CATEGORY",
        user_id=user.keycloak_id,
        target_id=cat.id,
        details=f"Updated category name from '{old_name}' to '{cat.name}'"
    )
    log_business_event("category_updated", f"name='{cat.name}' slug='{cat.slug}'", user.keycloak_id)

    return RedirectResponse(url="/categories", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/{slug}/delete")
def delete_category(
    slug: str,
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Deletes category, setting referencing documents' category_id to NULL (Administrators only)."""
    cat = db.query(Category).filter(Category.slug == slug).first()
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")

    cat_id = cat.id
    cat_name = cat.name

    db.delete(cat)
    db.commit()

    log_audit(
        db=db,
        action="DELETE_CATEGORY",
        user_id=user.keycloak_id,
        target_id=cat_id,
        details=f"Deleted category '{cat_name}'"
    )
    log_business_event("category_deleted", f"name='{cat_name}'", user.keycloak_id)

    return RedirectResponse(url="/categories", status_code=status.HTTP_303_SEE_OTHER)
