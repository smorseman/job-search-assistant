import sqlite3
from contextlib import contextmanager
from pathlib import Path

from job_search.config import settings


def init_db(db_path: str | None = None) -> None:
    path = Path(db_path or settings.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = Path(__file__).parent / "schema.sql"
    with sqlite3.connect(path) as conn:
        conn.executescript(schema.read_text())


@contextmanager
def get_db(db_path: str | None = None):
    path = db_path or settings.DB_PATH
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
