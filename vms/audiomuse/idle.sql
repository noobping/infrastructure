-- AudioMuse 3.6.3: task_status is both the durable queue and its status log.
-- Reject every non-terminal/unknown status, including delayed NEW children and
-- hidden control/migration jobs omitted by /api/active_tasks. Missing schema fails.
SELECT CASE WHEN
    EXISTS (SELECT 1 FROM task_status
            WHERE status IS NULL OR status NOT IN ('SUCCESS', 'FAIL', 'REVOKED'))
    OR EXISTS (SELECT 1 FROM pg_stat_activity
               WHERE datname = current_database() AND pid <> pg_backend_pid()
                 AND (state IS DISTINCT FROM 'idle')
                 AND backend_type = 'client backend')
    OR EXISTS (SELECT 1 FROM pg_stat_progress_vacuum WHERE datname = current_database())
    OR EXISTS (SELECT 1 FROM pg_stat_progress_create_index WHERE datname = current_database())
THEN 'busy' ELSE 'idle' END;
