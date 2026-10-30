# Terragraft v1.0 — Standalone Windows installation

- Repackaged as a single fresh-install ZIP. No upgrades, legacy state migrations or old credentials required.
- Dedicated Docker Compose project name `terragraft` and private-only PostgreSQL port.
- One-time installer (`INSTALL.ps1`/`INSTALL.cmd`) creates credentials and starts API + Windows runner.
- Central project registration (`CONNECT-PROJECT.ps1`) generates a plaintext-safe backend config **only for new, state-free Terraform projects** and creates a server project entry.
- Dashboard project management, saved-plan approval, encrypted state, graphs and audit history retained from earlier lab version.
- Restart/stop scripts, copy-token helper and optional separately confirmed old-stack cleanup.
- Unit tests for backend generation, safety checks, project directory allowlisting.

**Non-goal:** same-state parallel applies. This uses the standard HTTP backend and its whole-state lock semantics.
