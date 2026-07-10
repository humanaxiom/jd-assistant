# ReviewSkill — `@workspace /review` (merge-blocking)

Review `git diff main...HEAD`. Read-only — suggest, never edit.

## Checklist (pass/fail with file:line evidence)
1. Data placement: Postgres=transactions, Neo4j=graph/vector only, Redis=queue only
2. Type safety: no unjustified `# type: ignore`, no bare `Any`
3. Async correctness: no blocking I/O in async paths
4. Test integrity: diff shows tests added, not weakened/deleted
5. Config discipline: no scattered `os.environ`
6. Offline rule: no new external URLs
7. Migrations present for schema changes

## Verdict
**APPROVED** (zero critical/major) or **CHANGES REQUIRED** with a findings table
(severity critical/major/minor/nit · file:line · issue · fix). Hand findings to `/implement`.
