# JD Bank — an oral history

🔵 **A story, not a status page.** It tells how JD Bank came to be the way it is, so that a new
person, human or assistant, understands *why* the rules are the way they are before they try
to bend one. Every number below is **dated and historical**, kept because it explains a
decision. None of them is today's figure. For today's figures go to `/jd-bank/ui/funnel` and
[`../CURRENT.md`](../CURRENT.md), and for what to do next go to [`plan.md`](plan.md) and
[`../HANDOFF.md`](../HANDOFF.md).

Written 2026-11-20 from the repo's own records: the build record, three generations of
handoff, the findings log, the decision register and the git history. Where it says "we",
it means the owner and the assistant sessions that built this together.

---

## 1. The premise (July 2026)

SFU HR has kept roughly fourteen and a half thousand job descriptions across two decades, in
Word, legacy `.doc`, RTF and text. They are on two quite different forms, and thousands of
them are copies, near-copies and copies-with-a-new-date of each other. The question was
whether that pile could become a **bank**:
- one clean, standards-checked description per real role;
- a way for a hiring manager to write a new one that already meets SFU's standards;
- nothing reaching "published" without an HR person saying so.

The project started on **2026-07-10** from the v2 agent harness (`agent-harnesses-v2`),
vendored as a standalone repo (ADR-004). An earlier attempt, `C:\repos\jdbank`, had been
abandoned; it is still on disk and it is still stale. Three decisions were made on day one,
and none of them has moved since:

- **Postgres for everything relational, Neo4j for vectors and graph, no pgvector** (ADR-002,
  inherited). People keep proposing pgvector. The answer is still no.
- **Inference is self-hosted** (ADR-003). It started as "nothing leaves this machine". In
  practice the model runs on `aria-gb10-2`, a trusted internal host, so the real line is
  *no cloud and no third-party API, ever*. The owner ratified that reading on 2026-07-20.
- **Docker-only** (ADR-006). There is no host Python, no venv and no pip. Tests, gates,
  migrations and one-off probes all run in containers. It felt fussy at first. It is the
  reason CI and the dev box have never disagreed about what green means.

A fourth commitment came on 2026-07-11, the second day: **the rulebook is data, and every
non-trivial default is registered.** A threshold, a word list or a cut-off does not live in
Python. It lives in YAML, and it carries an entry in `decision_register.yaml` that says what
HR is being asked, what we ship meanwhile, and where that value came from. The build refuses
to load an unregistered knob. By November the register held a few hundred entries, and HR
had ratified two of them. That ratio is the project in one line: **we could build, and only
HR could decide, so we built in a way that made every undecided thing visible.**

## 2. Building the machine (July → mid-August)

The pipeline went up in the order the harness's phase plan laid out:
1. parse every file into one model (`SFUJobDescription`);
2. validate it against SFU's published JD Toolkit;
3. find duplicates in three tiers (exact, near-duplicate, same role in different words);
4. cluster the documents into roles;
5. harmonize each cluster into one **draft canonical JD**;
6. put that draft in front of a reviewer.

The **JD Builder** landed on 2026-07-24. It lets a manager write a new JD with live
compliance feedback. **CAS sign-in** and role-based access landed the next day (ADR-008),
and so did the operator guide.

The **content library** landed on 2026-08-01. The owner's instinct was right there: HR wanted
to *read job descriptions*, not statistics about them. "Lead with readable content, and make
every count click through to it" has been a standing rule ever since.

Security, deployment and navigability (Phase 9) were finished by mid-August.

Two habits formed in this period that still define the project:

- **The validator is the oracle.** A test of anything the model touches asserts what the
  validator says about the result, never the model's exact words.
- **Nothing auto-publishes.** A draft is a draft until a named reviewer approves it, and
  approving re-checks the gates at that moment.

## 3. Two forms, and a model that filled silences (mid-August)

The archive turned out not to be one form. About a third of it is SFU's APSA/APEX/Poly
description. Another third is the **CUPE 3338 Weighted Job Questionnaire**, a fourteen-section
point-factor instrument with no "Problem Solving" section at all. The remaining third states
no employee group whatsoever.

Scored through the APSA validator, **0 of 600** CUPE descriptions were approvable. The cause
was not their quality. Four rules checked for sections the WJQ simply does not have.

The fix was not a patch. It was a principle: **each form is judged against its own bar, and
the two scores are never averaged.** CUPE Phases B–E split the rules, thresholds,
harmonization and Builder per form. That is why every surface that shows both kinds of
score still says, in so many words, that they are not comparable.

The darker discovery came with the measurement tool that followed (`make bank-audit`). It
compared, section by section, what a role's **sources** said with what its **draft** said:

- Where the parser had recovered no duties from a CUPE form, the merge correctly produced
  none, and the rewrite model then **invented them**: about a thousand duties across a
  hundred drafts.
- On the APSA side, it wrote "Problem Solving" sections for roles whose sources never
  mentioned problem solving. Carry-through measured over 230%.
- In three of the four defects like this, **the invention raised the score.** That is why no
  user ever reported one.

From that came the rule that is now printed in the guide: **the model may reword, it may not
invent.** It may not write a section the sources never wrote, set the hiring bar, decide how
many duties a role has, or drop the point-factor content. When the rewrite fails, the draft
falls back to the deterministic merge rather than being lost.

## 4. The loop, and the way out of it (late August)

By **2026-08-24** the project felt like a loop, because it was one. The engineering was in
good shape. Thousands of drafts existed, hundreds of them approvable, behind about 2,900
tests. Yet **five** JDs had ever been published, and eight human review actions had ever been
taken. `docs/STATUS-2026-08-24.md` says it plainly: correctness work had become a substitute
for delivery. Optimising a proxy, draft fidelity, can run forever, because 14,500 documents
always hold one more defect.

The owner answered in two rulings that week. They are still the frame for everything:

- **Directive #1 (2026-08-28): tested, and deployable without the assistant.** A feature is
  not done when it works on this box. It is done when it is tested, ships through the
  scripts (`build.ps1`, `launch.ps1`, `teardown.ps1`, plus an offline bundle and installer
  for a fresh box with no internet), is **reachable from the UI**, and passes the CI gate
  that proves the bundle is complete. The "reachable" clause was not theoretical. The live
  funnel had shipped with no menu entry, and for a day people read the old dashboards as
  current.
- **The measure is drafts (2026-08-29).** Nothing is blocked on policy, and publishing
  happens in the final deployment, not in pilot or development. So "how many are published?"
  stopped being the question. The question became: *does this give a role a draft, or make
  an existing draft truer to its sources?* The same day HR ratified its first two decisions,
  the two approval gates, **as shipped**. The bar became signed, and nothing moved.

`CURRENT.md` was born on 2026-08-29 too, and its reason is the most-repeated lesson in this
repo. Five figures in the planning documents were wrong, and all five **agreed with each
other** across four documents, because all four had copied one unchecked source. **Agreement
between documents is a correlated failure, not corroboration.** So CURRENT.md holds almost
no facts, only where each fact lives and the command that checks it. If you find a count
written in it, that is a bug.

## 5. The archive fights back (late August → September)

Whenever a field was finally checked against the **source files**, rather than against the
database, it turned out to be wrong:

- **Employee group (parser v6).** A job was being called CUPE because it *mentioned* CUPE,
  for example an APSA manager who supervises CUPE staff. The field also had two
  provenances, read from the text for some forms and set by routing for others, with nothing
  recording which. The 24 drafts built on the mislabels were deleted.
- **Title (v7).** About half the CUPE archive had no title. The antiword render put a label
  and its value in one cell while the parser read the next cell. 805 titles came back.
- **Department (v8).** One unregistered label spelling, `Department Name/Section`, hid about
  six hundred departments.

The department story carries the lesson that cost the most. The first probe read whole
documents, while the parser reads only the identification block, so the probe "found" a
726-document read failure that did not exist. That wrong diagnosis survived three probe
fixes and a full write-up, because every number in it was consistent with every other.
**A probe must first reproduce a number the system already knows**, here `readable ≈
parser_has`, before anything else it says counts.

These months also produced the project's habit of reporting **three numbers, never one**:
matched, not matched, and could not evaluate. The IT collection had first defined "IT" by a
code present on about a third of the archive, and reported the result as the whole
function. Nothing on the page let a reader tell a small set from a blind filter.

The org units came next. **VPFA, Facilities, ITS, Finance, Safety & Risk and Campus
Services** shipped on 2026-09-09, the day before the Bank went in front of the CIO's AI task
force. Membership is an exact list from the owner, never a pattern, and every unit page
shows how many roles carry no department at all.

## 6. Directive #0 (2026-09-11)

On 2026-09-11 an assistant session merged **eight pull requests** with `make smoke` red the
whole time. Every one had green gates, green CI and a careful verification section. Every one
quoted the red as "pre-existing and unrelated."

The owner's answer is the prime directive: **ship only after a full end-to-end smoke test.**
"Ship" means merging or deploying. Red blocks shipping even when you are certain your change
did not cause it. There is no exemption, including for editing the directive itself; its
first draft tried to give itself one.

Making smoke deserve that trust took its own work:

- **Smoke was database-only** while calling itself end to end: six Postgres tests, no HTTP,
  no search. Meanwhile 703 roles had no vector and were invisible to Builder search.
- **The document-vector gate could not pass, by construction.** The skip-first embed was
  skipping the provenance label along with the vector (#199), so the gate could never go
  green.
- Since then, **every feature PR adds a live check of its own to smoke.** That is why the
  smoke file is the one every parallel PR conflicts on.

The same month produced two pieces of operational knowledge that are still live:

- **`--resume` is the wrong flag for a re-baseline.** It skips any draft that already has
  rewritten prose, which on a re-baseline is nearly all of them. It would have processed 9 of
  the 1,048 clusters that needed redoing and exited green. `--refreshed-since <T0>` exists
  because of that near-miss.
- **The stack did not survive a reboot.** One reboot killed a 19-hour pass at 825 of 2,453
  clusters. The services have restarted themselves since 2026-10-08. One-shot producer runs
  still do not.

Also in September: CAS origins. Sign-in broke twice in one day because the browser had
arrived at an address spelled slightly differently from any on the allowlist, and the
**port is part of the address**. `docs/NETWORK-SETUP.md` exists for the network admins who
will one day host this.

## 7. October: search, HR's own forms, and a second Bank

October turned outward, toward what HR actually uses (Tracks I, J and K,
[`plans/TRACKS-IJK-SEARCH-HR-FORMS-COMPREQ.md`](plans/TRACKS-IJK-SEARCH-HR-FORMS-COMPREQ.md)):

- **Search** got a hybrid of title and meaning, typo tolerance, and a fallback for when the
  embedding host is down.
- A **model-read query plan** was built and left switched **off** until HR and ITS choose the
  model.
- **Exports** now follow HR's forms: CUPE drafts print on HR's own WJQ form, and APSA drafts
  follow HR's 2024 template and read back cleanly.
- **SFU's Compensation Requisition Form** is filled from a role.

A deliberate measurement kept recurring: **role similarity has no threshold.** Over the live
index, a role's nearest *unrelated* neighbour scores higher than a genuine twin. So the Bank
ranks results and never shows a percentage.

A **second Bank** was made possible (#217), and the owner used it at once. Parser v9/v10 and
a hardened, fidelity-checked rewrite were built on `bank/v9`, in a separate checkout with
separate images and ports, leaving the live Bank alone. The owner ruled that two caps go:
the 600-character cap on supervisory text and the 400-character cap on qualifications. The
v9 Bank was then rebuilt from scratch. A full model pass over it took most of the first week
of November.

Two traps from this period still bite:
- An external agent's folder shares the v9 checkout's git record, so its branch switches
  switch ours. Check the branch before every v9 action, and leave that agent's work alone.
- The dev API does not hot-reload on a Windows bind mount, so the running server could be
  hours staler than the code that the in-process smoke had just declared green.

## 8. November: hand it to HR

By mid-November the goal had become concrete: **put the Bank in front of HR testers.** On
2026-11-19 the owner asked for a full readiness review. It found a real exposure first.

- **The incident.** The live `.env` had run with CAS off since 2026-11-08, with the dev
  fallback role set to admin, on ports open to the LAN and the tailnet. Anyone nearby was an
  administrator with no sign-in, and one v9 role had in fact been approved by
  `dev-anonymous`. CAS went back on within the hour.
- **The backup.** A full backup was taken before testers arrived, and its restore was
  rehearsed into an empty database.

It also found something better than a defect. **The archive's file names are PeopleSoft
records.** The owner noticed that every file is named `<As-Of date>_<user file name>`, and
that the user file name begins with the position numbers it is filed under. That made the
file name, not the text inside the document, the join key for the PeopleSoft data HR has not
yet exported. It now feeds the Compensation Requisition Form, the source-document page and
position-number search.

The review's other findings became #219–#224, merged on 2026-11-20:
- **Plain language** on every page a tester sees, with a smoke check that fails on internal
  ids, repository paths and pipeline words.
- **Builder drafts labelled** so they cannot pass for archive roles.
- **A review queue** that pages instead of rendering 2,499 rows at once.
- **An IT collection page** that loads in under a second instead of twenty-five.

Every one shipped with `make smoke` green on its own merged head. The owner then ran
`launch.ps1`, and smoke went green again on the deployed `main`.

## 9. What the project learned, in the words it kept using

These recur because they were each paid for more than once. The full set with its evidence
is in the archived handoffs and [`HARNESS_LESSONS.md`](HARNESS_LESSONS.md).

- **Check the Bank, not the counter.** A run's summary says what the run *did*; the Bank
  says what is *true*. `refreshed=95` was printed over 84 drafts that actually gained prose.
- **Agreement is not corroboration.** Only the system and the archive are second opinions.
- **A fixture cannot be stale.** Green unit tests prove nothing about the live system, which
  is why smoke runs against the real Bank and must cover the change.
- **A guard you have not broken is decoration.** Break it once and watch it go red. A
  one-directional guard is decoration too: assert both ways.
- **A placeholder is not a null.** `Untitled Position` passes `title <> ''` and reads as
  100% coverage.
- **A zero from a wrong query looks exactly like a zero from a guard that never fired.**
  Prove the query can return non-zero first.
- **A measurement has a shelf life.** Numbers recovered from a parked branch must be
  re-derived. Three of four had moved in a week.
- **Measure before designing a score.** Twice, the obvious design turned out undeliverable
  once it was measured over the whole archive.
- **Ask what the audience will look for.** ITS directors scan for their own department, not
  for SFU's classification of "IT". HR testers want readable JDs, not dashboards. And they
  should never see `HR-225`.
- **Green that does not mean what it sounds like** is the most expensive kind. Before you
  quote a suite as evidence, say what it covers.

## 10. Rulings worth knowing by heart

| when | ruling |
|---|---|
| 2026-07-20 | "Keep content local" means not cloud or third-party; the internal inference host is fine |
| 2026-08-28 | **Directive #1**: tested, and deployable through the scripts with no assistant in the loop |
| 2026-08-29 | The measure is **drafts**; publishing happens in the final deployment; nothing is blocked on policy |
| 2026-08-29 | HR-042 and HR-052 ratified **as shipped**, with attribution deliberately thin |
| 2026-09-11 | **Directive #0**: ship only after a full end-to-end smoke test, with no exemption |
| 2026-10-20 | v9 gets **its own Bank**; leave the live one alone |
| 2026-10-29 | Remove the supervisory and qualification caps (HR-324, HR-308) |
| 2026-11-19 | CAS on now; testers use the **live** Bank with the **author** role, after a backup |
| standing | Deliverables live in the repo and are never published elsewhere. The owner merges; the assistant does not |

## 11. Where the rest is written down

| for | read |
|---|---|
| where every fact lives | [`../CURRENT.md`](../CURRENT.md) |
| what is half-done and what bites | [`../HANDOFF.md`](../HANDOFF.md) |
| what we do next | [`plan.md`](plan.md) |
| everything measured, with its working | [`FINDINGS.md`](FINDINGS.md), [`audit/`](audit/) |
| the full build record, phases 0–9 and A–G | [`archive/BUILD-RECORD-phases-0-9-A-G.md`](archive/BUILD-RECORD-phases-0-9-A-G.md) |
| earlier handoffs, verbatim | [`archive/HANDOFF-ARCHIVE-2026-07-10-to-08-24.md`](archive/HANDOFF-ARCHIVE-2026-07-10-to-08-24.md), [`archive/HANDOFF-ARCHIVE-2026-08-29-to-11-20.md`](archive/HANDOFF-ARCHIVE-2026-08-29-to-11-20.md) |
| the re-evaluation that reset priorities | [`STATUS-2026-08-24.md`](STATUS-2026-08-24.md) |
| what HR must decide | [`decisions/HR-DECISION-MATRIX.md`](decisions/HR-DECISION-MATRIX.md) |
