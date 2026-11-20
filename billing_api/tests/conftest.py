"""Test fixtures. Tests use an in-memory SQLite database purely for isolation and speed, so they
run with no cloud, no Postgres and no LLM. The deployed system uses PostgreSQL."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config

config.PBKDF2_ITERATIONS = 1000  # fast password hashing in tests

from app.database import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Subscriber  # noqa: E402
from app.security import create_token, hash_password  # noqa: E402

PERIOD = {"year": 2026, "month": 10}


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add_all(
        [
            Subscriber(subscriber_no="ADMIN", name="Admin", role="admin",
                       password_hash=hash_password("admin-pw")),
            Subscriber(subscriber_no="5551001", name="Ayse", role="subscriber",
                       password_hash=hash_password("ayse-pw")),
            Subscriber(subscriber_no="5551002", name="Mehmet", role="subscriber",
                       password_hash=hash_password("mehmet-pw")),
        ]
    )
    session.commit()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    app = create_app(auto_create_tables=False)

    def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c


def _headers(subscriber_no: str, role: str) -> dict:
    token, _ = create_token(subscriber_no, role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_h():
    return _headers("ADMIN", "admin")


@pytest.fixture()
def ayse_h():
    return _headers("5551001", "subscriber")


@pytest.fixture()
def mehmet_h():
    return _headers("5551002", "subscriber")


@pytest.fixture()
def add_usage(client, admin_h):
    def _add(subscriber_no, usage_type, count, **period):
        p = {**PERIOD, **period}
        return client.post(
            "/api/v1/usage",
            json={"subscriberNo": subscriber_no, "usageType": usage_type, "count": count, **p},
            headers=admin_h,
        )

    return _add


@pytest.fixture()
def calculated_bill(client, admin_h, add_usage):
    """Ayse, Oct 2026: 1,350 minutes + 35 GB -> phone $10 + internet $70 = $80 (guide 4.3)."""
    assert add_usage("5551001", "Phone", 135).status_code == 201
    assert add_usage("5551001", "Internet", 35_000).status_code == 201
    r = client.post(
        "/api/v1/bills/calculate",
        json={"subscriberNo": "5551001", **PERIOD},
        headers=admin_h,
    )
    assert r.status_code == 200
    return r.json()
