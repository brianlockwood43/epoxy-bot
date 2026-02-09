from __future__ import annotations

import sqlite3

from controller.store import seed_default_controller_configs


def upgrade(conn: sqlite3.Connection) -> None:
    seed_default_controller_configs(conn)

