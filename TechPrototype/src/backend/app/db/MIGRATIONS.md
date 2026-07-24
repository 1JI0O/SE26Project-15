# Trace/Agent database migration

The authoritative migration path is Alembic under `app/db/migrations`.

Integration requirements:

1. Add Alembic to backend runtime/startup dependencies.
2. Keep `app.db.session.init_db()` as the startup entrypoint.
3. Existing iteration-1 databases without `alembic_version` are stamped at
   `0001_legacy_baseline`, then upgraded to `0002_trace_agent`.
4. Empty databases execute both revisions normally.

Legacy trace rows cannot meet the new evidence/version contract. They are preserved with deterministic
`trace-legacy-{id}` IDs, `source=legacy`, `status=stale`, and
`stale_reason=legacy_missing_version_evidence`.

Until the integration owner adds Alembic, SQLite uses a narrow compatibility upgrader containing the
same additions. Non-SQLite databases fail startup without Alembic rather than silently using
`create_all`. Once Alembic is installed it is selected automatically.

Downgrading `0002_trace_agent` removes new trace metadata and the Agent audit table and therefore loses
their data. Back up the database before downgrade.
