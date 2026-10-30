-- Applied by app startup to both existing and new PostgreSQL volumes.
CREATE SEQUENCE IF NOT EXISTS graph_version_seq;
CREATE SEQUENCE IF NOT EXISTS resource_fence_seq;
CREATE TABLE IF NOT EXISTS state_versions (
    id bigserial PRIMARY KEY,
    workspace text NOT NULL REFERENCES workspaces(name) ON DELETE CASCADE,
    state_bytes bytea,
    lineage text,
    serial bigint,
    action text NOT NULL,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS state_versions_workspace_id ON state_versions(workspace,id DESC);
CREATE TABLE IF NOT EXISTS resource_versions (
    workspace text NOT NULL REFERENCES workspaces(name) ON DELETE CASCADE,
    address text NOT NULL,
    version bigint NOT NULL,
    encrypted_value bytea,
    deleted boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace,address)
);
CREATE TABLE IF NOT EXISTS resource_leases (
    workspace text NOT NULL REFERENCES workspaces(name) ON DELETE CASCADE,
    address text NOT NULL,
    holder uuid NOT NULL,
    fence bigint NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (workspace,address)
);
CREATE INDEX IF NOT EXISTS resource_leases_expiry ON resource_leases(expires_at);
CREATE TABLE IF NOT EXISTS graph_operations (
    id uuid PRIMARY KEY,
    workspace text NOT NULL REFERENCES workspaces(name) ON DELETE CASCADE,
    actor text NOT NULL,
    label text NOT NULL,
    status text NOT NULL CHECK(status IN ('planned','committed','aborted','expired','recovery_required')),
    read_set jsonb NOT NULL,
    write_set jsonb NOT NULL,
    lock_set jsonb NOT NULL,
    expected_versions jsonb NOT NULL,
    fences jsonb NOT NULL,
    notes text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS graph_operations_workspace_time ON graph_operations(workspace,created_at DESC);
CREATE TABLE IF NOT EXISTS audit_events (
    id bigserial PRIMARY KEY,
    workspace text NOT NULL,
    actor text NOT NULL,
    event_type text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_events_workspace_id ON audit_events(workspace,id DESC);
ALTER TABLE graph_operations ADD COLUMN IF NOT EXISTS base_state_serial bigint;
ALTER TABLE graph_operations DROP CONSTRAINT IF EXISTS graph_operations_status_check;
ALTER TABLE graph_operations ADD CONSTRAINT graph_operations_status_check
    CHECK(status IN ('planned','committed','aborted','expired','recovery_required','reconciled'));
CREATE TABLE IF NOT EXISTS graph_value_history (
    id bigserial PRIMARY KEY,
    workspace text NOT NULL REFERENCES workspaces(name) ON DELETE CASCADE,
    address text NOT NULL,
    version bigint NOT NULL,
    encrypted_value bytea,
    deleted boolean NOT NULL,
    operation_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS graph_value_history_idx ON graph_value_history(workspace,address,id DESC);
