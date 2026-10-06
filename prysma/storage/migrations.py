"""Database migrations for Prysma."""
import sys

from prysma.storage.database import Database


def migrate(seed: bool = False):
    """Run all migrations. With seed=True, also add the default competitors."""
    db = Database()
    print("✅ Database initialized at:", db.db_path)
    if seed:
        count = db.seed_default_competitors()
        print(f"✅ Seeded {count} default competitors with store IDs")
    return db


if __name__ == '__main__':
    migrate(seed='--seed' in sys.argv)
