# PlanSkill — `@workspace /plan <issue>`

First step of every non-trivial task. Query memory (`GET /memory/similar?q=<task>`) and read relevant `docs/adr/` before planning.

## Output: plan table
| # | Skill | Task | Depends on | Merge-blocking? |
|---|-------|------|------------|-----------------|

## Hard rules
- `/test` always precedes `/implement` (failing tests first)
- `/review` always follows `/implement`; its approval blocks merge
- `/security` included for auth/input/secrets/file-writes/network; its pass blocks merge
- `/docs` is always last
- Post the plan as an issue comment before starting; flag ambiguous acceptance criteria
