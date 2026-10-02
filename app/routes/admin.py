from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.auth.dependencies import RoleRequirement, AuthenticatedUser
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.category import Category
from app.models.user import User
from app.utils import Paginator

router = APIRouter(prefix="/admin", tags=["Administration"])
templates = Jinja2Templates(directory="app/templates")

# Enforce Administrator privileges
require_admin = RoleRequirement(allowed_roles=["Admin"])

@router.get("")
def admin_panel(
    request: Request,
    page: int = 1,
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Renders the administrative dashboard displaying system health and recent audit logs."""
    # Retrieve system stats
    user_count = db.query(User).count()
    doc_count = db.query(Document).count()
    category_count = db.query(Category).count()

    # Load recent activity logs with pagination
    audit_query = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
    paginator = Paginator(page=page, per_page=30)
    pagination = paginator.paginate(audit_query)
    audit_logs = pagination["items"]

    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "request": request,
            "user": user,
            "user_count": user_count,
            "doc_count": doc_count,
            "category_count": category_count,
            "audit_logs": audit_logs,
            "pagination": pagination,
            "active_page": "admin"
        }
    )
