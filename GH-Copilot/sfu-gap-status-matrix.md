# SFU gap status matrix

| Item | Status | Priority | Owner | Impact | Delivery criteria |
|---|---|---:|---|---|---|
| Define CUPE/WJQ scope boundary | Open | P0 | Product + HR | High | Scope is documented and approved before work expands |
| Define Hay authority / advisory vs formal | Open | P0 | HR + Product | High | Policy clearly states the authority boundary |
| CUPE/WJQ authoring support | Planned | P1 | Engineering + HR | High | AUthoring, validation, and approval flow exists for WJQ roles |
| Formal Hay evaluation workflow | Planned | P1 | Engineering + HR | High | Factor-by-factor evaluation and review record exists |
| Re-evaluation request management | Planned | P1 | Engineering + HR | Medium-High | Requests can be reviewed and resolved with evidence |
| Compensation requisition workflow | Planned | P2 | Engineering + HR | High | Requests are tracked and tied to JD version and approval |
| Job-change / reorganization impact tracking | Planned | P2 | Engineering + HR | Medium | Before/after role changes and rationale are stored |
| Compensation audit trail | Planned | P2 | Engineering + Audit | High | All decisions are traceable to JD version and reviewer |
| End-to-end HR lifecycle platform | Future | P3 | Architecture + Product | High | Lifecycle spans authoring through compensation action |

## Status legend

- Open: Not yet decided or unresolved
- Planned: Expected next milestone work
- Future: Longer-term roadmap item after current gaps are addressed

## Notes

This matrix is intentionally status-based rather than a pure defect list. The repo is already doing strong work on JDFN validation and archive harmonization; the gap is mainly about broader SFU HR workflow coverage and policy clarity.

## Evidence base

- [docs/OPERATOR-GUIDE.md](../docs/OPERATOR-GUIDE.md#L152-L155)
- [core/src/api/routes/compose_ui.py](../core/src/api/routes/compose_ui.py#L539-L547)
- [core/src/jd_core/parser/wjq.py](../core/src/jd_core/parser/wjq.py#L1-L40)
- [core/src/jd_core/models/bank.py](../core/src/jd_core/models/bank.py#L35-L48)
- [GH-Copilot/sfu-site-gap-analysis.md](sfu-site-gap-analysis.md)
