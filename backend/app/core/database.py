from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

DATABASE_URL = settings.DATABASE_URL

# SQLite fix
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True
)

if DATABASE_URL.startswith("sqlite"):
    # WAL mode lets background tasks and stream workers read the DB
    # concurrently with API writers instead of hitting "database is locked".
    # busy_timeout makes any residual contention retry for 30s instead of
    # raising immediately.
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cameras'")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(cameras)")
                existing_cols = {row[1] for row in cursor.fetchall()}
                if "record_depth" not in existing_cols:
                    cursor.execute("ALTER TABLE cameras ADD COLUMN record_depth BOOLEAN DEFAULT 1")
                if "recording_video_testing_path" not in existing_cols:
                    cursor.execute("ALTER TABLE cameras ADD COLUMN recording_video_testing_path VARCHAR")
                if "recording_format" not in existing_cols:
                    cursor.execute("ALTER TABLE cameras ADD COLUMN recording_format VARCHAR(20) DEFAULT 'MP4'")
                if "clip_duration_minutes" not in existing_cols:
                    cursor.execute("ALTER TABLE cameras ADD COLUMN clip_duration_minutes INTEGER DEFAULT 1")
        except Exception:
            pass
        cursor.close()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()
