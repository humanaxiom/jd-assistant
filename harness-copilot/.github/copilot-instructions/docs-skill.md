# DocsSkill — `@workspace /docs`

Final pipeline step, after review approval. Only touch `docs/` and `README.md`.

## Process
1. Read `git diff main...HEAD --stat` + skill summaries
2. Architecture changed → new ADR `docs/adr/NNN-title.md`:
   Status / Date / Context / Decision / Architecture Diagram (Mermaid) / Consequences / Alternatives Considered
3. Sync Mermaid diagrams (README + docs/diagrams/) to current reality
4. Update README where behaviour/interfaces changed
5. Commit `docs: <what changed>`

Concise and factual; diagrams show what the code does now.
