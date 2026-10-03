"""Shared pytest fixtures for the backend test suite.

No fixtures live here yet — `run_db_test` in backend/tests/db.py (added
in Sprint 1A) is a plain helper function, not a pytest fixture, imported
directly by each module's model tests. A fixture-based equivalent (e.g.
an HTTP test client, once real API routes with database dependencies
exist) is a natural future addition here.
"""
