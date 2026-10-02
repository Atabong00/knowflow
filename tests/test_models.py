import pytest
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.category import Category
from app.models.document import Document
from app.utils import slugify


class TestModels:
    def test_create_user(self, db: Session):
        user = User(keycloak_id="test-id", email="test@example.com", display_name="Test User")
        db.add(user)
        db.commit()
        db.refresh(user)
        
        assert user.keycloak_id == "test-id"
        assert user.email == "test@example.com"
        assert user.display_name == "Test User"

    def test_create_category(self, db: Session):
        category = Category(name="Test Category", slug="test-category", description="Test desc")
        db.add(category)
        db.commit()
        db.refresh(category)
        
        assert category.name == "Test Category"
        assert category.slug == "test-category"

    def test_create_document(self, db: Session):
        category = Category(name="Test Category", slug="test-category")
        db.add(category)
        db.commit()
        
        user = User(keycloak_id="user-id", email="user@example.com")
        db.add(user)
        db.commit()
        
        doc = Document(
            title="Test Doc",
            slug="test-doc",
            content="Test content",
            category_id=category.id,
            author_keycloak_id=user.keycloak_id,
            status="published"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        assert doc.title == "Test Doc"
        assert doc.category.name == "Test Category"

    def test_delete_category_uncategorizes_documents(self, db: Session):
        category = Category(name="To Delete", slug="to-delete")
        db.add(category)
        db.commit()
        
        doc = Document(
            title="Doc to keep",
            slug="doc-to-keep",
            content="Content",
            category_id=category.id,
            status="published"
        )
        db.add(doc)
        db.commit()
        
        db.delete(category)
        db.commit()
        
        db.refresh(doc)
        assert doc.category_id is None
        assert doc.category is None
