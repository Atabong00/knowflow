import os

# Point the application database at a shared sqlite file for tests so that the
# module-level `Base.metadata.create_all()` in app/main.py (and the test
# sessions) operate on the SAME in-process database instead of the production
# postgres instance which is not reachable from the test host.
os.environ["DATABASE_URL"] = "sqlite:////tmp/ddc_test.db"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import Base, get_db, engine, SessionLocal
from app.models import User, Category, Document, Course, Module, Assessment, Question, Attempt, Progress

# Use the application's engine/session (now sqlite) so everything shares one DB.
TestingSessionLocal = SessionLocal


@pytest.fixture(scope="function")
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
