import sqlite3
from contextlib import contextmanager
from pathlib import Path

from job_search.config import settings

# Columns added after the original `jobs` schema shipped. `CREATE TABLE IF NOT
# EXISTS` cannot add columns to a pre-existing table, so these are applied via
# idempotent ALTER TABLE on every init. (New *tables* are handled by schema.sql.)
_JOBS_ADDED_COLUMNS: dict[str, str] = {
    "llm_grade": "TEXT",
    "llm_fit_score": "REAL",
    "llm_rationale": "TEXT",
    "llm_graded_at": "TEXT",
    "llm_model": "TEXT",
}


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Idempotently add any missing `jobs` columns. Safe to run every init."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    for col, decl in _JOBS_ADDED_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")


def init_db(db_path: str | None = None) -> None:
    path = Path(db_path or settings.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = Path(__file__).parent / "schema.sql"
    with sqlite3.connect(path) as conn:
        conn.executescript(schema.read_text())
        _apply_migrations(conn)


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
