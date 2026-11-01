from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings


def test_existing_sessions_keep_tenant_binding_through_upgrade_and_downgrade(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "0004")
    engine = create_engine(url)
    try:
        with engine.begin() as db:
            for name in ("a", "b"):
                db.execute(text("INSERT INTO admins (id,tenant_id,email,password_hash) VALUES (:id,:tenant,:email,:hash)"),
                           {"id": name, "tenant": f"tenant-{name}", "email": f"{name}@example.invalid", "hash": "synthetic-hash"})
                db.execute(text("INSERT INTO login_sessions (token_hash,admin_id,csrf_hash,expires_at) VALUES (:token,:admin,:csrf,:expires)"),
                           {"token": name * 64, "admin": name, "csrf": "c" * 64,
                            "expires": datetime(2030, 1, 1, tzinfo=timezone.utc)})
            db.execute(text("INSERT INTO login_sessions (token_hash,admin_id,csrf_hash,expires_at) VALUES (:token,:admin,:csrf,:expires)"),
                       {"token": "d" * 64, "admin": "missing", "csrf": "c" * 64,
                        "expires": datetime(2030, 1, 1, tzinfo=timezone.utc)})
        command.upgrade(config, "head")
        with engine.connect() as db:
            rows = db.execute(text("SELECT admin_id,tenant_id,csrf_hash FROM login_sessions ORDER BY admin_id")).all()
            assert rows == [("a", "tenant-a", "c" * 64), ("b", "tenant-b", "c" * 64)]
        columns = {column["name"]: column for column in inspect(engine).get_columns("login_sessions")}
        assert not columns["tenant_id"]["nullable"]
        assert "ix_login_sessions_tenant_id" in {index["name"] for index in inspect(engine).get_indexes("login_sessions")}
        command.downgrade(config, "0004")
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert db.execute(text("SELECT COUNT(*) FROM login_sessions")).scalar_one() == 2
    finally:
        engine.dispose()
