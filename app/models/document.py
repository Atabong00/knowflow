from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    content = Column(Text, nullable=False)  # Stores Markdown text
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    author_keycloak_id = Column(String, ForeignKey("users.keycloak_id", ondelete="SET NULL"), nullable=True)
    status = Column(String, default="published", nullable=False)  # "draft" or "published"
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    category = relationship("Category", back_populates="documents", passive_deletes=True)
    author = relationship("User")

    def __repr__(self):
        return f"<Document title={self.title} slug={self.slug}>"
