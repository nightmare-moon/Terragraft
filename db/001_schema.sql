CREATE TABLE IF NOT EXISTS workspaces (
    name text PRIMARY KEY,
    state_bytes bytea,
    lineage text,
    serial bigint,
    lock_info jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS resource_nodes (
    workspace text NOT NULL REFERENCES workspaces(name) ON DELETE CASCADE,
    address text NOT NULL,
    provider text NOT NULL,
    resource_type text NOT NULL,
    mode text NOT NULL,
    PRIMARY KEY (workspace, address)
);
CREATE TABLE IF NOT EXISTS resource_edges (
    workspace text NOT NULL REFERENCES workspaces(name) ON DELETE CASCADE,
    source_address text NOT NULL,
    target_address text NOT NULL,
    PRIMARY KEY (workspace, source_address, target_address)
);
CREATE INDEX IF NOT EXISTS edge_reverse_lookup
    ON resource_edges(workspace, target_address);
CREATE TABLE IF NOT EXISTS demo_leases (
    workspace text NOT NULL,
    address text NOT NULL,
    owner text NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (workspace, address)
);
CREATE INDEX IF NOT EXISTS lease_expiry ON demo_leases(expires_at);
