import pytest
import tempfile
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.db import Base, get_db
from app.core.config import settings
from app.main import app

# SQLite in-memory database URL
DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(autouse=True)
def mock_storage_path(monkeypatch):
    """
    Redirects LOCAL_STORAGE_PATH to a temporary folder during tests
    to prevent pollution of local dev directories.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        monkeypatch.setattr(settings, "LOCAL_STORAGE_PATH", temp_dir)
        # Also clear the global cached storage instance in the factory
        # so that each test gets a fresh LocalDiskStorage pointing to the new temp directory.
        import app.services.storage.factory as storage_factory
        monkeypatch.setattr(storage_factory, "_storage_instance", None)
        yield temp_dir

@pytest.fixture(name="db_engine")
def fixture_db_engine():
    """
    Initializes an isolated SQLite in-memory engine and creates all tables.
    """
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(name="db")
def fixture_db(db_engine):
    """
    Creates a new database session for a test, wrapped in a transaction that rolls back.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = SessionLocal()
    
    yield session
    
    session.close()
    # Check if the connection transaction is still active before rolling back
    if transaction.is_active:
        transaction.rollback()
    connection.close()

@pytest.fixture(name="client")
def fixture_client(db):
    """
    Returns a TestClient with database session overrides.
    """
    def override_get_db():
        try:
            yield db
        finally:
            pass
            
    app.dependency_overrides[get_db] = override_get_db
    # Disable raising server exceptions to allow testing our global exception handler
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def mock_tasks_db_session(db, monkeypatch):
    """
    Injects the test's DB session into background tasks, and disables db.close()
    inside tasks so the shared test transaction is not prematurely destroyed.
    """
    import app.workers.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "_TESTING", True)
    monkeypatch.setattr(tasks_mod, "SessionLocal", lambda: db)

