import re
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.audit_log import AuditLog


def slugify(text: str) -> str:
    """Generate URL-friendly slugs from title text."""
    slug = text.lower()
    slug = re.sub(r'[^a-z0-9\-]', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


def log_audit(db: Session, action: str, user_id: str, target_id: int, details: str):
    """Utility to register sensitive system audits."""
    log = AuditLog(
        action=action,
        user_keycloak_id=user_id,
        target_id=target_id,
        details=details
    )
    db.add(log)
    db.commit()


class Paginator:
    """Simple pagination helper for SQLAlchemy queries."""
    def __init__(self, page: int = 1, per_page: int = 20):
        self.page = max(page, 1)
        self.per_page = min(max(per_page, 1), 100)  # Clamp between 1 and 100
        self.offset = (self.page - 1) * self.per_page

    def paginate(self, query):
        """Apply pagination to a SQLAlchemy query."""
        total = query.count()
        items = query.offset(self.offset).limit(self.per_page).all()
        total_pages = (total + self.per_page - 1) // self.per_page
        return {
            "items": items,
            "total": total,
            "page": self.page,
            "per_page": self.per_page,
            "total_pages": total_pages,
            "has_next": self.page < total_pages,
            "has_prev": self.page > 1
        }
