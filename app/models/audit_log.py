from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String, nullable=False)  # e.g., "create_document", "delete_document"
    user_keycloak_id = Column(String, ForeignKey("users.keycloak_id", ondelete="SET NULL"), nullable=True)
    target_id = Column(Integer, nullable=True)  # ID of the document/category affected
    details = Column(Text, nullable=True)  # Contextual details of the action
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User")

    def __repr__(self):
        return f"<AuditLog action={self.action} user={self.user_keycloak_id} timestamp={self.timestamp}>"
