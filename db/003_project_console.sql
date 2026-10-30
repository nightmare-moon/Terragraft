-- Central project registry and host-runner execution queue. Safe to reapply.
CREATE TABLE IF NOT EXISTS managed_projects (
  id uuid PRIMARY KEY,
  name text NOT NULL UNIQUE,
  workspace text NOT NULL UNIQUE REFERENCES workspaces(name),
  runner_id text NOT NULL,
  local_path text NOT NULL,
  engine text NOT NULL CHECK (engine IN ('terraform','tofu')),
  enabled boolean NOT NULL DEFAULT true,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS managed_runs (
  id uuid PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES managed_projects(id) ON DELETE RESTRICT,
  status text NOT NULL CHECK(status IN
    ('queued','running_plan','plan_ready','approved','running_apply',
     'succeeded','failed','canceled','needs_reconciliation')),
  requestor text NOT NULL,
  approver text,
  plan_digest text,
  config_digest text,
  plan_has_changes boolean,
  output_text text NOT NULL DEFAULT '',
  error_message text NOT NULL DEFAULT '',
  claim_token uuid,
  lease_until timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS managed_runs_project_time ON managed_runs(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS managed_runs_queue ON managed_runs(status,created_at);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_managed_run_per_project
  ON managed_runs(project_id) WHERE status IN
  ('queued','running_plan','plan_ready','approved','running_apply','needs_reconciliation');
