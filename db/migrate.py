from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


MIGRATION_RE = re.compile(r"^(\d{4})_([a-zA-Z0-9_]+)\.(sql|py)$")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _checksum_file(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at_utc TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _load_applied(conn: sqlite3.Connection) -> dict[str, tuple[str, str, str]]:
    cur = conn.cursor()
    cur.execute("SELECT version, name, checksum, applied_at_utc FROM schema_migrations")
    out: dict[str, tuple[str, str, str]] = {}
    for version, name, checksum, applied_at_utc in cur.fetchall():
        out[str(version)] = (str(name), str(checksum), str(applied_at_utc))
    return out


def _run_sql(conn: sqlite3.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    conn.executescript(sql)


def _run_py(conn: sqlite3.Connection, path: Path) -> None:
    mod_name = f"epoxy_migration_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load migration module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    upgrade = getattr(module, "upgrade", None)
    if not callable(upgrade):
        raise RuntimeError(f"Python migration missing upgrade(conn): {path}")
    upgrade(conn)


def apply_sqlite_migrations(conn: sqlite3.Connection, migrations_dir: str) -> None:
    _ensure_migration_table(conn)
    applied = _load_applied(conn)
    base = Path(migrations_dir)
    if not base.exists():
        raise RuntimeError(f"Migrations directory not found: {migrations_dir}")

    files: list[tuple[str, str, str, Path]] = []
    for p in sorted(base.iterdir()):
        if not p.is_file():
            continue
        m = MIGRATION_RE.match(p.name)
        if not m:
            continue
        version, name, ext = m.group(1), m.group(2), m.group(3)
        files.append((version, name, ext, p))

    cur = conn.cursor()
    for version, name, ext, path in files:
        checksum = _checksum_file(path)
        existing = applied.get(version)
        if existing:
            old_name, old_checksum, _applied_at = existing
            if old_name != name or old_checksum != checksum:
                raise RuntimeError(
                    f"Migration version {version} already applied with different content "
                    f"(existing name={old_name}, file name={name})."
                )
            continue

        print(f"[DB] Applying migration {version}_{name}.{ext}")
        if ext == "sql":
            _run_sql(conn, path)
        elif ext == "py":
            _run_py(conn, path)
        else:
            raise RuntimeError(f"Unsupported migration extension: {path.name}")

        cur.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at_utc)
            VALUES (?, ?, ?, ?)
            """,
            (version, name, checksum, _utc_now_iso()),
        )
        conn.commit()

