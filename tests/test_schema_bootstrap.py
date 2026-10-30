"""Verify SQL bootstrap order without requiring a PostgreSQL service."""
import unittest
from contextlib import nullcontext
from app.migration import upgrade


class _FakeConnection:
    def __init__(self):
        self.queries = []

    def transaction(self):
        return nullcontext()

    def execute(self, query, params=None):
        self.queries.append(query)
        return []


class BootstrapTests(unittest.TestCase):
    def test_new_database_schema_precedes_hardening(self):
        db = _FakeConnection()
        upgrade(db)
        self.assertIn('pg_advisory_xact_lock', db.queries[0])
        self.assertIn('CREATE TABLE IF NOT EXISTS workspaces', db.queries[1])
        self.assertIn('CREATE TABLE IF NOT EXISTS state_versions', db.queries[2])
        self.assertIn('CREATE TABLE IF NOT EXISTS managed_projects', db.queries[3])
        self.assertIn('SELECT name,state_bytes FROM workspaces', db.queries[4])


if __name__ == '__main__':
    unittest.main()
