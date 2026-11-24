# VPFA spinoff handoff kit

The source of the handoff bundle for the VPFA spinoff
([`../VPFA-SPINOFF-PLAN.md`](../VPFA-SPINOFF-PLAN.md)). **No Bank data is in git.** The
snapshot is SFU job-description content and travels only in the bundle (USB or a temporary
share, per `START-HERE.md` Part T).

| file | what |
|---|---|
| [`START-HERE.md`](START-HERE.md) | the single instruction set: Part A on the parent box (verify v9, export, package), Part T (transfer), Part B on the new machine (setup + the Claude Code kickoff prompt) |
| [`tools/export_snapshot.py`](tools/export_snapshot.py) | the read-only snapshot exporter, run inside a throwaway container from the Bank's checkout; the prototype of `make bank-snapshot` (plan §5.1) |
| [`tools/package.ps1`](tools/package.ps1) | puts a snapshot in the bundle, rebuilds the parent git bundle (`main` + `bank/v9`), hashes every file, zips with a checksum |

**Where they run.** The bundle is assembled on the parent box at
`C:\repos\vpfa-handoff-bundle-2026-11-24\`, and `START-HERE.md`'s paths assume that
folder. The copies here are the reviewable record. If you change one, copy it to the bundle
folder as well, or the two drift.

Every command in `START-HERE.md` was rehearsed on 2026-11-24:
- the export, against v9's code;
- packaging, then unzip, hash check and clone with both branches present;
- the Bank-check query, verbatim.

Two defects were caught and fixed that way: a git bundle that cloned with no branches, and
an exporter that labelled every snapshot "live".
