import re
import random
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.auth.dependencies import require_user, RoleRequirement, AuthenticatedUser
from app.models.document import Document
from app.models.category import Category
from app.models.audit_log import AuditLog
from app.core.security import render_markdown_safely
from app.utils import slugify, log_audit, Paginator
from app.core.logging_config import log_business_event, log_error
from app.schemas import DocumentCreate, DocumentUpdate, form_parser

router = APIRouter(prefix="/documents", tags=["Documents"])
templates = Jinja2Templates(directory="app/templates")

# Role Dependency Guards
require_editor = RoleRequirement(allowed_roles=["Editor", "Admin"])
require_admin = RoleRequirement(allowed_roles=["Admin"])

@router.get("")
def list_documents(
    request: Request,
    category_slug: str = None,
    page: int = 1,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Retrieve lists of published documents, optionally filtered by category."""
    query = db.query(Document).filter(Document.status == "published")
    
    current_category = None
    if category_slug:
        current_category = db.query(Category).filter(Category.slug == category_slug).first()
        if current_category:
            query = query.filter(Document.category_id == current_category.id)

    categories = db.query(Category).order_by(Category.name).all()
    
    paginator = Paginator(page=page, per_page=20)
    pagination = paginator.paginate(query.order_by(Document.title))
    documents = pagination["items"]

    return templates.TemplateResponse(
        request,
        "documents/list.html",
        {
            "request": request,
            "user": user,
            "documents": documents,
            "categories": categories,
            "current_category": current_category,
            "pagination": pagination,
            "active_page": "documents"
        }
    )

@router.get("/new")
def new_document_form(
    request: Request,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Renders the document creation form (Editors/Admins)."""
    categories = db.query(Category).order_by(Category.name).all()
    return templates.TemplateResponse(
        request,
        "documents/edit.html",
        {
            "request": request,
            "user": user,
            "categories": categories,
            "document": None,
            "active_page": "documents"
        }
    )

@router.post("/new")
async def create_document(
    request: Request,
    form: DocumentCreate = Depends(form_parser(DocumentCreate)),
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Saves new documents to database and registers audit logs."""
    title = form.title
    content = form.content
    category_id = form.category_id if form.category_id and form.category_id > 0 else None
    status_str = form.status_str
    slug = slugify(title)
    
    # Check if slug is unique
    existing = db.query(Document).filter(Document.slug == slug).first()
    if existing:
        # Append unique tag to keep slugs distinct
        slug = f"{slug}-{random.randint(100, 999)}"

    doc = Document(
        title=title,
        slug=slug,
        content=content,
        category_id=category_id,
        author_keycloak_id=user.keycloak_id,
        status=status_str
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    log_audit(
        db=db,
        action="CREATE_DOCUMENT",
        user_id=user.keycloak_id,
        target_id=doc.id,
        details=f"Created document '{title}' (slug: {slug})"
    )
    log_business_event("document_created", f"title='{title}' slug='{slug}'", user.keycloak_id)

    return RedirectResponse(url=f"/documents/{doc.slug}", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/{slug}")
def view_document(
    request: Request,
    slug: str,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Renders a single document, converting its Markdown to clean HTML."""
    doc = db.query(Document).filter(Document.slug == slug).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Render Markdown to secure HTML
    rendered_content = render_markdown_safely(doc.content)

    return templates.TemplateResponse(
        request,
        "documents/view.html",
        {
            "request": request,
            "user": user,
            "document": doc,
            "rendered_content": rendered_content,
            "active_page": "documents"
        }
    )

@router.get("/{slug}/edit")
def edit_document_form(
    request: Request,
    slug: str,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Renders editing interface for an existing article (Editors/Admins)."""
    doc = db.query(Document).filter(Document.slug == slug).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    categories = db.query(Category).order_by(Category.name).all()
    return templates.TemplateResponse(
        request,
        "documents/edit.html",
        {
            "request": request,
            "user": user,
            "categories": categories,
            "document": doc,
            "active_page": "documents"
        }
    )

@router.post("/{slug}/edit")
async def update_document(
    request: Request,
    slug: str,
    form: DocumentUpdate = Depends(form_parser(DocumentUpdate)),
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Processes document edits, logs diff audits."""
    doc = db.query(Document).filter(Document.slug == slug).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Keep track of old details for audit logs
    old_title = doc.title
    
    doc.title = form.title if form.title is not None else doc.title
    doc.content = form.content if form.content is not None else doc.content
    doc.category_id = form.category_id if form.category_id is not None else doc.category_id
    if doc.category_id is not None and doc.category_id == 0:
        doc.category_id = None
    doc.status = form.status_str if form.status_str is not None else doc.status
    
    # Regenerate slug only if title changes
    new_slug = slugify(doc.title)
    if new_slug != doc.slug:
        # Check slug uniqueness
        existing = db.query(Document).filter(Document.slug == new_slug).first()
        if not existing:
            doc.slug = new_slug
        else:
            doc.slug = f"{new_slug}-{random.randint(100, 999)}"

    db.commit()
    db.refresh(doc)

    log_audit(
        db=db,
        action="UPDATE_DOCUMENT",
        user_id=user.keycloak_id,
        target_id=doc.id,
        details=f"Updated document (previously '{old_title}', now '{doc.title}')"
    )
    log_business_event("document_updated", f"title='{doc.title}' slug='{doc.slug}'", user.keycloak_id)

    return RedirectResponse(url=f"/documents/{doc.slug}", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/{slug}/delete")
def delete_document(
    slug: str,
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Deletes documents (Restricted to Administrators)."""
    doc = db.query(Document).filter(Document.slug == slug).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_id = doc.id
    doc_title = doc.title

    db.delete(doc)
    db.commit()

    log_audit(
        db=db,
        action="DELETE_DOCUMENT",
        user_id=user.keycloak_id,
        target_id=doc_id,
        details=f"Deleted document '{doc_title}'"
    )
    log_business_event("document_deleted", f"title='{doc_title}'", user.keycloak_id)

    return RedirectResponse(url="/documents", status_code=status.HTTP_303_SEE_OTHER)
