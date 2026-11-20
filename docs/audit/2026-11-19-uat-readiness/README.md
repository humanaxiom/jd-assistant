# UAT readiness review — 2026-11-19

🔵 **Dated record.** What was found when the owner asked for "a full review" before
handing JD Bank to HR testers (Library/search → JD Builder → Compensation Requisition
Form), with PeopleSoft position metadata still unavailable. Numbers are as measured on
this date; re-measure rather than quote them later.

**Method.** Four independent Opus reviewers, read-only against both Banks: (A) an HR
tester's walkthrough of live (25800) over HTTP, inspecting the filled PDFs; (B) a code
review of PR #219 (K3 CRF download + I3 query plan), with `make gates-fast` and
`register-check`; (C) a measured design for reading PeopleSoft facts from archive
filenames; (D) operational readiness — which Bank, access, backup, feedback, smoke. Every
blocker was re-checked by the orchestrator against the system before acting.

## Verdict

**Not ready on the morning of the review; ready to hand over once the items marked ✅
below are merged and `make smoke` is green on the merged head.** One blocker was a live
security exposure and was closed the same hour.

## Blockers

| # | Finding (verified) | Disposition |
|---|---|---|
| B1 | Live **and** v9 served every visitor as **admin with no sign-in** from the LAN IP and the Tailscale IP: `.env` `CAS_ENABLED=false` (since 2026-11-08), `CAS_DEV_DEFAULT_ROLE=admin`, ports on `0.0.0.0`, Wi-Fi on the Public firewall profile. A v9 role was already approved as `dev-anonymous` (2026-11-09). | ✅ Owner: "turn CAS on now". `CAS_ENABLED=true` + `launch.ps1`; `/queue` → 303 login from both addresses. v9 API container stopped. |
| B2 | A tester's Builder **Submit** becomes a role in the Library indistinguishable from an archive role ("distilled from 0 source JDs"); 5 such roles exist on live, one titled with a whole paragraph. No delete. | Owner: testers on live with the `author` role, after a backup. ✅ Backup + restore drill done. Library labelling/filtering on `fix/library-uat`. |

## Compensation Requisition Form (CRF)

| Finding | Disposition |
|---|---|
| Section A listed **every** position in the role as "based on" — 58 ids for one role — and the overflow was written into the requester's own *Reason for request* box | ✅ Only the requester's pick is listed |
| "Leave blank — I'll type it" was ignored for single-position roles (the one position was written anyway) | ✅ The position is pre-selected but written only if left picked |
| Department came from the role family, whichever position was picked (one role's sources span Lifelong Learning, Continuing Studies, Physics, Chemistry…) | ✅ From the picked position's own files when they agree — **HR-337**, registered `open` |
| Contact box would hold a bare computing ID: CAS supplies no name/email (all 8 live users) | ✅ Editable name-and-title / email boxes, prefilled from the session |
| The page promised a tick and a contact even with HR-311/HR-313 switched off; the CUPE note showed for every no-group role | ✅ Page follows the knobs; note reworded |
| Majority tie broken by database row order | ✅ Broken by name |
| 371 of 2,498 roles flagged "position list may be incomplete" because ~993 filenames carry unpadded ids | ✅ Filename position reader (below) — on `feat/filename-positions` |
| Grade, job code, union / department code, Reg/Temp, hours stay blank | By design until the PeopleSoft export (K1) — testers are told |

## Filename metadata (the owner's discovery)

Archive filename = `<PeopleSoft As-Of Date>_<User File Name>`; the modern user file name
is `<position list>_JDFN_<group>_<JD date>`, e.g.
`20200601_61,_30785,_208,_975_JDFN_APSA_20211117.docx` = positions 61, 30785, 208, 975,
As-Of 2020-06-01. Measured over all 14,565 names (lane C):

| | padded reader (today) | new reader |
|---|---|---|
| files with ≥1 position | 13,572 | 14,379 |
| files with none | 993 | 186 |
| CRF roles "may be incomplete" (live) | 371 | 75 |

False-positive audit: random 45 new pairs all real; grade numbers (`Gr._7`, `gr_6`) 0;
3 template-name false positives and 16 ambiguous truncated 7-digit tokens removed by a
corroboration gate (an id must also appear padded elsewhere when it is short). Position
00000061 appears in 8 files on 6 distinct leading dates — matching PeopleSoft's "1 of 6".
The leading-date = As-Of equivalence rests on **one** confirmed sample.

Design decisions: a **separate** reader (the padded `segmentation.position_id_pattern`
also feeds the baseline and near-dedup; widening it would move registered numbers),
computed on read from `source_documents.filename` (no migration, no re-parse, no
`PARSER_VERSION` bump), knobs HR-325–331. **The filename position is the join key for
the future PeopleSoft export**: `canonical_jds.content.position_number` — which
`scripts/import_grades.py` joins on today — is set on 1 of 2,504 roles (and that one
value is a faculty name); the parsed body field disagrees with the filename on 1,228
files where both exist.

## Library / search

| Finding | Disposition |
|---|---|
| Builder-written roles look like archive roles | on `fix/library-uat` |
| Nonsense query (`zzzqqq`) → 100 confident "related by meaning" results, no notice | banner when nothing matches by title — on `fix/library-uat` (no similarity threshold: see FINDINGS) |
| 12 identical "Manager, Academic and Administrative Services" rows — no way to tell them apart | Department column — on `fix/library-uat` |
| No way for a tester to report a problem | "Report a problem" mailto link (`FEEDBACK_EMAIL`) — on `fix/library-uat` |
| Review queue: one 1.36 MB page of 2,499 rows, raw UUIDs, 6-decimal scores | deferred — testers have no reviewer role |
| 1,245 parsed files "Untitled Position"; source page shows "Position # —" while the filename has it | deferred — follows from the filename reader |
| Exported .docx spells the territorial acknowledgement in ASCII (HR-105, `open`) | testers told; HR ruling |
| `/collection/it` takes 24–26 s | deferred |
| Internal jargon on HR pages (HR-225, doc paths, "Tier 1/2/3", "Parse confidence") | deferred |

## Operations

- **Which Bank: LIVE.** Live: parser v8, 2,503 roles, 2,435/2,499 drafts with rewritten
  prose, has the CRF. v9: parser v10 but 641 of 2,257 drafts failed their rewrite, role
  vectors stale, no CRF route. v9 needs `--resume` (~26 h on the GPU), `embed-roles`,
  `bank-audit`, smoke, then a merge of #219 (3 conflicts).
- **Backup:** `C:\repos\jd-bank-backups\harness-20261119-pre-uat.dump`, restore drill
  passed (fingerprint identical). There is no `make backup` target.
- **Smoke on live: 31 passed, 1 skipped** (I3, flag off). It covers the CRF download
  through the role page and Builder search/check/export/clone; it does **not** cover
  Builder submit, assist, review, the CAS login, real HTTP to the container, or
  several users at once.
- **Access:** `ALLOWED_SERVICE_ORIGINS` still lists the old LAN IP `192.168.1.80`
  (now `.73`); an origin not on the list falls back to the Tailscale hostname after
  CAS. Plain http on the LAN — `SESSION_COOKIE_SECURE=false`. Give testers **one** URL
  that is on the list.
- **GPU:** Library/role/CRF/export do not need `aria-gb10-2`; search embeds every query
  (falls back to titles if the host is down) and Builder *assist* is a 60 s chat call —
  slow while a rewrite pass holds the GPU.

## I3 (query understanding, flag OFF) — must fix before HR-315 is switched on

With the flag on, the model's `semantic_query` *replaces* the typed words in the meaning
search, so "it can only add results" is false. Embed both and union. Not a UAT issue
while the flag is off.

## Decisions only the owner can make

1. Tester URL (one origin, on the allowlist; TLS?) and whether off-campus/tailnet access is allowed.
2. `FEEDBACK_EMAIL` — where "Report a problem" goes.
3. The v9 role published by `dev-anonymous`.
4. When to run the v9 `--resume` (holds the GPU ~26 h).
5. HR-105 (acknowledgement spelling) — testers will circulate exports.
