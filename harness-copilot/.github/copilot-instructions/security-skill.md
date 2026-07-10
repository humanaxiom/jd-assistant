# SecuritySkill — `@workspace /security` (merge-blocking when triggered)

Trigger when the diff touches auth, input handling, secrets, file writes, subprocess, or network.

## Audit `git diff main...HEAD` for
- SQL/Cypher injection (flag any string interpolation into queries)
- Hardcoded secrets/credentials
- FastAPI routes missing Pydantic validation
- Path traversal in file-writing code (agents write files — verify allowlists + `..` rejection)
- New external URLs (offline violation)
- Unbounded resources: missing timeouts, Redis keys without EXPIRE, unpaginated queries

## Verdict
**PASS** or **FAIL** with findings table (category · severity · file:line · remediation).
Critical or high = FAIL. Hand remediations to `/implement`.
