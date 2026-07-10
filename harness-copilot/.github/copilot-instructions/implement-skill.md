# ImplementSkill — `@workspace /implement <task>`

Failing tests exist (RED confirmed). Make them pass, then make every gate green.

## Process
1. `cd core && pytest tests/unit -q` — the failures are the spec
2. Check memory: `curl -s "localhost:8000/memory/similar?q=<task>"`
3. Implement minimally under `core/src/`
4. `make gates` — iterate on exact failures only, max 5 attempts
5. Still red after 5 → stop, present the failure report verbatim + hypothesis
6. Commit `green: <task>` only when fully green

## Hard rules
Never modify tests; never add unjustified `# type: ignore`; never lower coverage; async I/O only; config via `src/settings.py`; Postgres=transactions, Neo4j=graph/vector, Redis=queue; no cloud endpoints.
