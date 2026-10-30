# Architectural decisions and future implementation contract

## ADR-001: Keep standard Terraform/OpenTofu HTTP backend safe

Terraform's `http` backend treats the state as one object, supports GET/POST/DELETE plus LOCK/UNLOCK, and sends lock ID on updates. We preserve this contract and never suppress locks. An independent graph metadata engine **cannot** change that contract. Attempting optimistic field-level state merge at the backend layer alone would be unsafe because the CLI refreshes and writes the entire prior state snapshot.

## ADR-002: Separate state snapshots from experimental graph records

`workspaces.state_bytes` is the authoritative encrypted raw state. `resource_nodes` and `resource_edges` are only a projected inventory. `resource_versions` stores separately encrypted experimental metadata; it does **not** represent Terraform `instances`. Never round-trip parsed metadata back into Terraform state.

## ADR-003: Lease and optimistic conflict protocol

A graph operation acquires resource lease rows atomically, with DB advisory transaction locks sorted by SHA-256 of workspace+resource to handle absent-key races. A fence sequence distinguishes old and new lease owners. Plans record the version of each written node, its known prerequisites, and explicit read set; commits reject changes to any recorded version. A Terraform snapshot serial change also invalidates graph operations. Dependents are conservatively protected by default. Lease renewal and explicit recovery mode support testing fail/retry behavior. External cloud API effects require independent verification; metadata fencing alone cannot prevent them.

## ADR-004: Secure-by-default local credentials and encryption

Static scoped tokens authorize API calls; Basic (Terraform-compatible) and Bearer are supported. Fernet encrypts state snapshot and metadata values before PostgreSQL storage, including archived snapshots. `.env` and backups are never checked into source control. TLS termination, HA, OIDC, KMS and granular workspace policies are explicitly out of scope for this laboratory version.

## Next architecture milestone: real graph execution

Building a true Stategraph-equivalent requires a Terraform/OpenTofu-aware execution layer capable of planning and applying independent graph segments with provider-specific behavior, stable resource identity and explicit read/write sets for dependencies, data sources, outputs, imports, moved blocks, dynamic for_each/count, replace/deposed and partial failure. Merge cannot be based on Terraform's JSON state alone without validating all provider-private semantics. Implementation should first be prototyped against a restricted set of providers/resources with failure injection and differential tests against native Terraform/OpenTofu; only then broaden support. The current experimental metadata API intentionally does **not** claim those semantics.


## v1.0 Standalone central project control plane

The HTTP backend remains the source of truth for canonical Terraform state and uses Terraform's normal whole-state locking. Project registration maps a display name to a unique state workspace, runner id, engine and host-local directory. Server never gets direct access to host project directories. A standalone host runner polls an authenticated queue, verifies paths lie under an explicit root, requires an HTTP backend without mismatched existing state metadata, and runs only fixed argv sequences (`init`, `plan -out`, and `apply <saved-plan>`).

Plan and apply are split by a durable approval state; a run can have only one active operation at a time, with a unique partial PostgreSQL index. A plan's SHA-256 and a root-config fingerprint must agree at apply. The runner stores saved plans only on the host. No terraform destroy endpoint, shell input, automatic state migration or lock bypass is provided. Timed-out applies block new operations until manually reconciled.

This is still NOT resource-fragment state merging, graph-aware provider reconciliation or concurrent applies within a single state. Distinct Terraform state workspaces can run independently, with normal cloud-level hazards. Current lab security uses one agent token for all runner ids, admin-only access to run details, and plaintext plan-output logs in PostgreSQL; production requires per-agent identities, fine-grained RBAC, TLS, secrets policy, workload sandboxing, resilient distributed lease semantics and reviewed migrations.
