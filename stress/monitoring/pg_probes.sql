-- PostgreSQL probes for the TraceLab stress plan.
-- Each block is tagged so collect_server.sh can split the output into per-probe CSVs.
-- The lock-wait probe is the primary evidence for H1 (workspace-row FOR UPDATE
-- serializing all pushes into one workspace).

-- probe: connections
-- Connection-pool pressure. The engine uses SQLAlchemy defaults (5 + 10 overflow)
-- per uvicorn worker, so 2 workers cap out around 30 backends (H2).
SELECT
    now() AS sampled_at,
    state,
    wait_event_type,
    count(*) AS backends
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY state, wait_event_type
ORDER BY backends DESC;

-- probe: lock_waits
-- Blocked/blocking chains. Under S2-A this should show pushes queued behind a
-- single ExclusiveLock on the workspace row.
SELECT
    now() AS sampled_at,
    blocked.pid AS blocked_pid,
    blocked.wait_event_type,
    blocked.wait_event,
    blocking.pid AS blocking_pid,
    blocked_locks.locktype,
    blocked_locks.relation::regclass AS relation,
    left(blocked.query, 120) AS blocked_query
FROM pg_locks blocked_locks
JOIN pg_stat_activity blocked ON blocked.pid = blocked_locks.pid
JOIN pg_locks blocking_locks
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.pid <> blocked_locks.pid
    AND blocking_locks.granted
JOIN pg_stat_activity blocking ON blocking.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;

-- probe: lock_wait_count
-- Single scalar for time-series plotting of contention depth.
SELECT
    now() AS sampled_at,
    count(*) AS waiting_backends
FROM pg_locks
WHERE NOT granted;

-- probe: table_sizes
SELECT
    now() AS sampled_at,
    relname,
    n_live_tup,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 15;

-- probe: slow_statements
-- Requires pg_stat_statements. Reset it before each scenario:
--   SELECT pg_stat_statements_reset();
SELECT
    now() AS sampled_at,
    calls,
    round(mean_exec_time::numeric, 2) AS mean_ms,
    round(max_exec_time::numeric, 2) AS max_ms,
    round(total_exec_time::numeric, 2) AS total_ms,
    rows,
    left(query, 160) AS query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
