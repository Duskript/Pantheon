"""Ichor schema migrations package.

Each migration is a self-contained, idempotent module that adds new
schema elements (columns, indexes, tables) without touching existing
ones. Migrations are tracked in the `ichor_settings` key/value table —
the row `<MIGRATION_KEY>` → "applied" is set on successful completion.

Run from /home/konan/pantheon:

    python3 -c "
    import sys; sys.path.insert(0, '.')
    from lib.ichor.migrations.v2_temporal import run_migration
    run_migration()
    "

Or import the re-export from the ichor package root:

    from lib.ichor import run_migration
    run_migration()
"""
