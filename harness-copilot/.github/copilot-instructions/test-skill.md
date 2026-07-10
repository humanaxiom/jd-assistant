# TestSkill — `@workspace /test <module>`

Write FAILING tests only, under `core/tests/`. Never touch `core/src/`.

## Process
1. Read spec + existing patterns (`core/tests/unit/`, `core/tests/integration/test_stores.py` for testcontainers)
2. Cover happy path, edge cases, error cases; parametrize where natural
3. Unit tests mock ALL external I/O (Ollama, Postgres, Neo4j, Redis); integration uses testcontainers
4. `cd core && pytest tests/unit -q` → MUST FAIL; if green, strengthen
5. Commit `red: failing tests for <task>`

≥ 5 tests per new public class; `@pytest.mark.asyncio` for async; ruff/black/mypy --strict clean; never weaken existing tests.
