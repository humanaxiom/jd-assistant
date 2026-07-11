"""JD Bank — the standalone JD dedup / harmonization / composer system.

This package holds JD Bank's own persistence layer (Postgres ORM + Neo4j
vector index), built on the shared harness ``Base`` so a single metadata
covers both the harness ledger and the JD Bank domain tables.
"""
