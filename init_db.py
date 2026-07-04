"""Create the SQLite schema.

Usage:
    python init_db.py
"""

from __future__ import annotations

from backend.db.session import DB_PATH, init_db


def main() -> None:
    init_db()
    print(f"Database initialized at: {DB_PATH}")


if __name__ == "__main__":
    main()
