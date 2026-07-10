# Task: Artifact semantic search endpoint with pagination

**Task ID:** T-102
**Branch:** agent/T-102-artifact-search

## Goal
Expose paginated semantic search over Neo4j artifact memory: `GET /memory/artifacts?q=<text>&page=1&size=10`, replacing the unbounded `/memory/similar`.

## Acceptance Criteria
- [ ] Pydantic response model `ArtifactSearchPage` (items, page, size, total)
- [ ] `size` capped at 50 (422 beyond), `q` min length 3
- [ ] Neo4j vector query bounded — no full scans
- [ ] Unit tests: validation bounds, pagination math, empty results
- [ ] Integration test: real Neo4j (testcontainers), embedding mocked
- [ ] Security subagent MUST run: input validation + injection audit on the Cypher
- [ ] All gates green; ADR only if the memory interface changes shape

## Subagent Sequence
planner → tester → coder(loop) → reviewer + security → docs
