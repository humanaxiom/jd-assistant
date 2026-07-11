# SFU HR Decision Register

> **Generated file — do not edit by hand.** Rendered from `core/src/jd_core/rules/decision_register.yaml` by `make register`. `make register-check` (and CI) fails the build if this file drifts from it.

Rulebook version `jd_rules_sfu_v3` · **81 decisions** (81 open · 0 ratified · 0 deferred) · 56 parameters explicitly exempted as trivial · 134 parameters on the decision surface, all accounted for.

## What this is

Every policy call JD Bank currently makes **by default**, because SFU HR has not made it. For each one: the question, the value we ship, exactly where that value is configured, and — the column that matters most — whether the default came from SFU's published rulebook, from the hris pipeline we inherited, or from nobody but us.

**Nothing here is a code change.** Every value below is a line in a versioned YAML file. Changing one is a data edit; `src/jd_core/quality/` is not touched.

**This document cannot rot.** The register is data, and the build checks it against the live rules three ways: every `Configured in` path must resolve; every `We ship` value must equal the real one; and every parameter on the decision surface must be either listed here or explicitly exempted as trivial. Tune a threshold without updating the register and `make gates` fails.

## Open — we defaulted these; SFU HR has not decided them

| ID | Decision | Default | Where the default came from |
|---|---|---|---|
| [HR-001](#hr-001) | What quality score must a job description reach before an HR reviewer is allowed to approve it? | `60.0` | our invention |
| [HR-002](#hr-002) | What quality grade must a job description reach before approval? | `C` | our invention |
| [HR-003](#hr-003) | At what finding severity does an outstanding problem make approval impossible, regardless of score? | `high` | our invention |
| [HR-004](#hr-004) | Which rulebook failures should make approval impossible — the "never approve if…" list? | *14 entries — see below* | our invention |
| [HR-005](#hr-005) | Which gates may a reviewer NEVER waive, even with a written justification in the audit log? | `SFU-APPROVE-MANDATORY-SECTIONS`, `SFU-APPROVE-NO-PLACEHOLDERS` | our invention |
| [HR-006](#hr-006) | Which template sections are so essential that a job description without them cannot be reviewed at all? | `SFU-COMP-SUMMARY`, `SFU-COMP-DUTIES`, `SFU-COMP-QUALS` | our invention |
| [HR-007](#hr-007) | Should a draft that still contains the template's own instructional text be un-waivably blocked? | `SFU-STRUCT-PLACEHOLDER` | our invention |
| [HR-008](#hr-008) | How many points should a HIGH-severity problem cost a job description? | `20.0` | hris calibration |
| [HR-009](#hr-009) | How many points should a MEDIUM-severity problem cost? | `10.0` | hris calibration |
| [HR-010](#hr-010) | How many points should a LOW-severity problem cost? | `5.0` | hris calibration |
| [HR-011](#hr-011) | Should advisory (INFO) findings cost any score at all? | `0.0` | hris calibration |
| [HR-012](#hr-012) | Should the second, third and fourth problem of the same severity cost less than the first? | `0.7` | hris calibration |
| [HR-013](#hr-013) | What score earns an A? | `90.0` | hris calibration |
| [HR-014](#hr-014) | What score earns a B? | `75.0` | hris calibration |
| [HR-015](#hr-015) | What score earns a C — and is C really the pass mark? | `60.0` | hris calibration |
| [HR-016](#hr-016) | What score earns a D (rather than an F)? | `40.0` | hris calibration |
| [HR-017](#hr-017) | Should a flawless job description score 100? | `100.0` | hris calibration |
| [HR-018](#hr-018) | Should the score bottom out at 0, or can it go negative? | `0.0` | hris calibration |
| [HR-019](#hr-019) | SFU's template says a Position Summary is 100–150 words. Should a SHORT summary (under 100) be flagged at all — and should it ever block approval? | `100` | SFU rulebook |
| [HR-020](#hr-020) | Is 150 words the hard maximum for a Position Summary? | `150` | SFU rulebook |
| [HR-021](#hr-021) | SFU says 3–5 major responsibilities. Should FEWER than 3 duties be flagged — and should it block? | `3` | SFU rulebook |
| [HR-022](#hr-022) | Is 5 the maximum number of major duties? | `5` | SFU rulebook |
| [HR-023](#hr-023) | Duty time-allocations must total 100%. How much rounding slack do we allow at the bottom? | `99` | our invention |
| [HR-024](#hr-024) | How much rounding slack at the top of the duty-percentage total? | `101` | our invention |
| [HR-025](#hr-025) | Should the "duties must total 100%" check run on a JD that lists only ONE time allocation? | `2` | our invention |
| [HR-026](#hr-026) | How many offending items should a single finding name before it says "and others"? | `5` | hris calibration |
| [HR-027](#hr-027) | How many rule ids may a blocked-approval reason cite? (A second, independent copy of HR-026.) | `5` | hris calibration |
| [HR-028](#hr-028) | Three words on SFU's own replace-list — "individual", "honest", "trust" — are demoted to LOW severity here. Is that right? | *6 entries — see below* | our invention |
| [HR-029](#hr-029) | NINE of these 31 "coded terms" are NOT on SFU's published list — we added them. Does SFU HR adopt them, or should they go? | *31 entries — see below* | hris calibration |
| [HR-030](#hr-030) | Should a job titled "Executive Director" that is NOT in the APEX group be blocked — and should the check even run when the employee group is unknown? | `low` | hris calibration |
| [HR-031](#hr-031) | Is "Executive Director" reserved for APEX-classified roles, and only those? | `apex` | SFU rulebook |
| [HR-032](#hr-032) | "Registrar" is reserved for AVPSI Student Services. We cannot verify that from a JD — should we still say anything? | `info` | hris calibration |
| [HR-033](#hr-033) | "Human Resources" is reserved for roles inside SFU HR (elsewhere: "personnel"). Same unverifiable-context problem — should we still say anything? | `info` | hris calibration |
| [HR-034](#hr-034) | A JD with no "Impact of Decision Making" section is incomplete. Should it be blocked from approval? | `medium` | hris calibration |
| [HR-035](#hr-035) | Same question for "Problem Solving & Level of Supervision" — should a missing section block approval? | `medium` | hris calibration |
| [HR-036](#hr-036) | SFU says a JD has 3–5 major duties. Should MORE THAN FIVE block approval? | `medium` | hris calibration |
| [HR-037](#hr-037) | Should FEWER than three duties be a defect at all? | `medium` | hris calibration |
| [HR-038](#hr-038) | Should a Position Summary shorter than 100 words be a defect at all? | `low` | hris calibration |
| [HR-039](#hr-039) | Is the territorial acknowledgement's WORDING correct — and is a missing territorial acknowledgement really only a `low` finding? | `low` | hris calibration |
| [HR-040](#hr-040) | SFU's knowledge tiers are EXCELLENT / WORKING / [NO MODIFIER]. We encode the third as the literal word "none". Is that the right representation? | `excellent`, `none`, `working` | hris calibration |
| [HR-041](#hr-041) | Should the banned-phrase check ("may include", "assets", "preferences") search the WHOLE document, or only the Qualifications section? | `may include`, `assets`, `preferences` | SFU rulebook |
| [HR-042](#hr-042) | Must a JD contain the literal phrase "equivalent combination" — or is any equivalency wording acceptable? | `equivalent combination` | SFU rulebook |
| [HR-043](#hr-043) | SFU's action-verb glossary lists "accountable" — an adjective, not a verb. Should a duty be allowed to start with it? | `true` | SFU rulebook |
| [HR-044](#hr-044) | Same for "responsible" — an adjective in SFU's action-verb glossary. | `true` | SFU rulebook |
| [HR-045](#hr-045) | Should only PARENTHESIZED percentages — "(40%)" — count as duty time allocations? | `\((\d{1,3})\s*%\)` | our invention |
| [HR-046](#hr-046) | Should a Position Summary that mentions parking, housing or relocation be BLOCKED from approval? | *11 entries — see below* | our invention |
| [HR-047](#hr-047) | Should the phrase "action verb" appearing anywhere in a JD un-waivably block it as an unfinished draft? | *7 entries — see below* | our invention |
| [HR-048](#hr-048) | A JD is blocked for "incumbent-focused language" if its summary contains "my", "myself" or "I am". Is that the right test? | `\bmy\b|\bmyself\b|\bi am\b` | our invention |
| [HR-049](#hr-049) | A "Senior" title with no stated supervisory scope is blocked. Should the test be the bare word "senior" anywhere in the title? | `\bsenior\b` | our invention |
| [HR-050](#hr-050) | What counts as "a degree requirement" in a JD? | `\b(bachelor|master|phd|doctorate|degree)\b` | hris calibration |
| [HR-051](#hr-051) | What wordings count as "allows a related or relevant discipline"? | `(related|relevant)\s+(discipline|field)|or\s+other\s+relevant` | hris calibration |
| [HR-052](#hr-052) | Qualifications must run Knowledge -> Skills -> Abilities. This mapping IS that order. Is it right? | `knowledge` → 0; `skill` → 1; `ability` → 2 | SFU rulebook |
| [HR-053](#hr-053) | Are BASIC / INTERMEDIATE / ADVANCED / EXPERT the only accepted skill levels? | `advanced`, `basic`, `expert`, `intermediate` | SFU rulebook |
| [HR-054](#hr-054) | Must an ability literally start with "Ability to" / "Able to" to count as observable behaviour? | `ability to`, `able to` | hris calibration |
| [HR-055](#hr-055) | Is SFU's 116-verb action-verb glossary the right list — and should a duty that starts with a good verb NOT on it be flagged? | *116 entries — see below* | SFU rulebook |
| [HR-056](#hr-056) | Must every JD's Relationships section open with SFU's standard sentence, verbatim? | `establishes and maintains relationships and alliances` | SFU rulebook |
| [HR-057](#hr-057) | Which rules are severe enough that their mere presence blocks approval — whatever the score, and without being named in any gate? | `SFU-COMP-DUTIES`, `SFU-COMP-QUALS`, `SFU-COMP-SUMMARY` | our invention |
| [HR-058](#hr-058) | SFU's mandatory, "do not edit" About SFU paragraph contains the word "compassionate" — which our lexicon flags as a coded term. Every compliant JD is penalised. What should give? | `"caring"` | hris calibration |
| [HR-059](#hr-059) | What are SFU's job-title seniority levels — the ladder every title is classified onto (and, later, compared and de-duplicated by)? | *7 entries — see below* | hris calibration |
| [HR-060](#hr-060) | When a job title carries TWO seniority words — "Associate Director" is both an associate and a director — which one decides the family? | *7 entries — see below* | hris calibration |
| [HR-061](#hr-061) | Which title words signal each seniority family? | *7 entries — see below* | hris calibration |
| [HR-062](#hr-062) | SFU writes a supervisory title as "Manager, Laboratory Operations" and a non-supervisory one as "Laboratory Operations Manager" (Part 3.4). WHICH families, written first and followed by a comma, actually signal supervision? | *5 entries — see below* | hris calibration |
| [HR-063](#hr-063) | What are the functional title types — SFU's Job-Title Application Table? | *10 entries — see below* | SFU rulebook |
| [HR-064](#hr-064) | "Executive Director" and "Associate Director" both contain "Director". Which functional type wins? | *10 entries — see below* | hris calibration |
| [HR-065](#hr-065) | Which words in a title map it onto each functional type? | *10 entries — see below* | SFU rulebook |
| [HR-066](#hr-066) | Which words in a JD's education requirement mean "graduate-level"? | `phd`, `doctora`, `master` | hris calibration |
| [HR-067](#hr-067) | Which words in a JD's education requirement mean "undergraduate"? | `bachelor`, `undergraduate`, `degree` | hris calibration |
| [HR-068](#hr-068) | Which language in the Problem Solving section signals independent, non-routine thinking? | *14 entries — see below* | hris calibration |
| [HR-069](#hr-069) | Which language in the Problem Solving section signals routine, closely supervised work — and should it really SUBTRACT? | *8 entries — see below* | hris calibration |
| [HR-070](#hr-070) | Which language in the Impact of Decision Making section signals freedom to act and magnitude of impact? | *15 entries — see below* | hris calibration |
| [HR-071](#hr-071) | Which Toolkit skill modifiers count as "advanced" depth for the Know-How signal? | `advanced`, `expert` | hris calibration |
| [HR-072](#hr-072) | Which Toolkit knowledge modifiers count as top-level knowledge? | `excellent` | hris calibration |
| [HR-073](#hr-073) | How much is each Know-How signal worth? | *7 entries — see below* | hris calibration |
| [HR-074](#hr-074) | How many advanced skills is "many", and how many qualification kinds is "broad"? | `advanced_skills_for_many` → 3; `qualification_kinds_for_broad` → 4 | hris calibration |
| [HR-075](#hr-075) | At what Know-How score does a role read as moderate, and at what score high? | `moderate` → 3.0; `high` → 5.0 | hris calibration |
| [HR-076](#hr-076) | How much is each Problem-Solving signal worth — and how much does routine language cost? | `section_item` → 0.5; `challenge_hit` → 1.0; `routine_hit` → -1.0 | hris calibration |
| [HR-077](#hr-077) | How many Problem Solving entries are worth scoring before length stops counting? | `section_items_scored` → 3 | hris calibration |
| [HR-078](#hr-078) | At what Problem-Solving score does a role read as moderate, and at what score high? | `moderate` → 1.5; `high` → 3.0 | hris calibration |
| [HR-079](#hr-079) | How much is each Accountability signal worth? | `section_item` → 0.5; `autonomy_hit` → 1.0; `supervisory_scope` → 2.0; `external_breadth` → 1.0 | hris calibration |
| [HR-080](#hr-080) | How many Impact-of-Decision-Making entries are scored, and how many external relationships count as "breadth of impact"? | `section_items_scored` → 3; `external_for_breadth` → 3 | hris calibration |
| [HR-081](#hr-081) | At what Accountability score does a role read as moderate, and at what score high? | `moderate` → 2.0; `high` → 4.0 | hris calibration |

### Our invention — nobody has ratified these

JD Bank made these up because the system needed *a* value. There is no SFU or hris precedent behind any of them. **Start here.**

#### HR-001 — What quality score must a job description reach before an HR reviewer is allowed to approve it?

- **We ship:** `60.0`
- **Configured in:** `gates.yaml` → `gates.SFU-APPROVE-SCORE-FLOOR.min_score`
- **Where the default came from:** our invention
- **Why it matters:** This is the single number that decides how much of the archive is even presentable for review. It is OUR roll-up of the rulebook, not a number SFU published anywhere — SFU's rulebook names conditions ("never approve if…"), never a score. We chose 60 to line up with the C grade band.
- **If it changes:** Directly sets the size of the review queue. Raising it to 70 turns every C-grade JD into a blocked draft; lowering it to 50 lets D-grade JDs through to a reviewer. Should be ratified against the Phase-2.5 archive baseline (what score does the median SFU JD actually get?), not in the abstract.

#### HR-002 — What quality grade must a job description reach before approval?

- **We ship:** `C`
- **Configured in:** `gates.yaml` → `gates.SFU-APPROVE-GRADE-FLOOR.min_grade`
- **Where the default came from:** our invention
- **Why it matters:** A second, independent floor next to the score floor (HR-001). The grade letter is what a reviewer actually sees, so this is the bar in the language the dashboard speaks. Also not an SFU number.
- **If it changes:** Deliberately a separate knob from HR-001 and today aligned with it (grade C starts at 60.0 — HR-015). They can be tuned apart, but if they disagree the stricter one silently wins, which is confusing to a reviewer. Ratify them together.

#### HR-003 — At what finding severity does an outstanding problem make approval impossible, regardless of score?

- **We ship:** `high`
- **Configured in:** `gates.yaml` → `gates.SFU-APPROVE-SEVERITY-FLOOR.min_severity`
- **Where the default came from:** our invention
- **Why it matters:** The backstop: any finding at this severity or worse blocks approval even if the JD scores well. It is also the only gate that catches findings with no rule id at all — i.e. the Phase-5 LLM pass. Today only three rules are `high` (no summary / no duties / no qualifications).
- **If it changes:** Lowering it to `medium` would block on missing Decision-Making, missing Problem-Solving, banned qualification phrases, leftover placeholders and any coded term flagged `medium` — a very large share of the archive at once.

#### HR-004 — Which rulebook failures should make approval impossible — the "never approve if…" list?

- **We ship:** `SFU-AUTH-SUMMARY-CONDITIONS`, `SFU-AUTH-SUMMARY-INCUMBENT`, `SFU-COMP-DUTIES`, `SFU-COMP-EDI`, `SFU-COMP-QUALS`, `SFU-COMP-SUMMARY`, `SFU-COMP-TERRITORIAL`, `SFU-GATE-DUTY-PCT`, `SFU-GATE-KSA-ORDER`, `SFU-GATE-SENIOR-TITLE`, `SFU-QUAL-BANNED-PHRASE`, `SFU-QUAL-EQUIVALENT`, `SFU-STRUCT-PLACEHOLDER`, `SFU-STRUCT-SUMMARY-TOO-LONG`
- **Configured in:** `gates.yaml` → `gates.blocking_rule_ids`
- **Where the default came from:** our invention
- **Why it matters:** THE master list, and the most reviewable line in the whole system: it is the complete set of rule failures that disable the approve button. The selection is ours. Notably ABSENT and therefore NOT blocking today — each a live question for HR: coded/gendered terms (SFU-LANG-CODED, HR-028/HR-029), a JD with more than five duties (SFU-STRUCT-DUTIES-TOO-MANY, HR-036), a missing Impact-of-Decision-Making or Problem-Solving section (HR-034/HR-035), and the three restricted-title rules (HR-030/HR-032/HR-033).
- **If it changes:** Adding one id to a gate's `rule_ids` promotes that rule to blocking with no code change. This register entry is what makes such a promotion visible: the build fails until this list is updated, so a rule can never quietly start — or stop — blocking approval.

#### HR-005 — Which gates may a reviewer NEVER waive, even with a written justification in the audit log?

- **We ship:** `SFU-APPROVE-MANDATORY-SECTIONS`, `SFU-APPROVE-NO-PLACEHOLDERS`
- **Configured in:** `gates.yaml` → `gates.non_overridable_gate_ids`
- **Where the default came from:** our invention
- **Why it matters:** Every other gate is overridable: a reviewer who judges a block to be a false positive waives it WITH A WRITTEN REASON, which is exactly the audit trail CLAUDE.md §1 asks for. These two are absolute — a JD with no summary, duties or qualifications, and a draft still carrying the template's own instructional text. We asserted that no override could reasonably speak to either.
- **If it changes:** Removing a gate from this set hands reviewers discretion they do not have today; adding one takes discretion away. Flipping ANY gate's `overridable` flag moves this list and breaks the build until HR is told.

#### HR-006 — Which template sections are so essential that a job description without them cannot be reviewed at all?

- **We ship:** `SFU-COMP-SUMMARY`, `SFU-COMP-DUTIES`, `SFU-COMP-QUALS`
- **Configured in:** `gates.yaml` → `gates.SFU-APPROVE-MANDATORY-SECTIONS.rule_ids`
- **Where the default came from:** our invention
- **Why it matters:** This is the un-waivable gate (HR-005), so its membership is the strongest claim in the policy. SFU's Part 2 template makes ALL its sections mandatory; restricting the absolute bar to these three is our call. Impact of Decision Making and Problem Solving — both Hay evaluation inputs — are deliberately NOT here (HR-034 / HR-035).
- **If it changes:** Anything added here becomes un-waivable: no reviewer, no reason, no override. A large slice of the legacy archive would become permanently un-approvable until rewritten.

#### HR-007 — Should a draft that still contains the template's own instructional text be un-waivably blocked?

- **We ship:** `SFU-STRUCT-PLACEHOLDER`
- **Configured in:** `gates.yaml` → `gates.SFU-APPROVE-NO-PLACEHOLDERS.rule_ids`
- **Where the default came from:** our invention
- **Why it matters:** The second un-waivable gate (HR-005). It fires on the literal placeholder markers in markers.yaml — and one of those markers is the phrase "action verb" (HR-047). A real JD that happens to contain that phrase is therefore blocked with NO override available. That combination is a trap worth HR's attention.
- **If it changes:** Making this gate overridable (or narrowing the marker list) would let a reviewer waive a false positive. Leaving it as-is keeps genuinely unfinished drafts out of review at the cost of the false positives in HR-047.

#### HR-023 — Duty time-allocations must total 100%. How much rounding slack do we allow at the bottom?

- **We ship:** `99`
- **Configured in:** `thresholds.yaml` → `thresholds.duty_allocation_total_min`
- **Where the default came from:** our invention
- **Why it matters:** SFU says 100%, full stop (Part 11.6, an explicit never-approve condition). The 99–101 tolerance is a rounding window WE invented so that a JD whose duties are 33/33/33 is not blocked over 1%.
- **If it changes:** Tightening to exactly 100 would block every JD whose percentages were written by hand and round; widening it lets genuinely wrong allocations through a gate SFU explicitly named.

#### HR-024 — How much rounding slack at the top of the duty-percentage total?

- **We ship:** `101`
- **Configured in:** `thresholds.yaml` → `thresholds.duty_allocation_total_max`
- **Where the default came from:** our invention
- **Why it matters:** The upper half of the invented rounding window in HR-023.
- **If it changes:** See HR-023 — ratify the window as a pair.

#### HR-025 — Should the "duties must total 100%" check run on a JD that lists only ONE time allocation?

- **We ship:** `2`
- **Configured in:** `thresholds.yaml` → `thresholds.duty_allocation_min_count`
- **Where the default came from:** our invention
- **Why it matters:** It does not today. The check only runs when at least two parenthesized "(NN%)" allocations are present, so a JD with a single duty marked "(50%)" — an obviously incomplete document — SILENTLY PASSES an SFU never-approve gate. The threshold exists to avoid false positives on documents where extraction found one stray percentage; the cost is this escape.
- **If it changes:** Setting it to 1 closes the escape and will fire on legacy documents whose extraction produced a single spurious "(100%)". Worth measuring against the Phase-2.5 archive baseline before deciding.

#### HR-028 — Three words on SFU's own replace-list — "individual", "honest", "trust" — are demoted to LOW severity here. Is that right?

- **We ship:** `he/she` → "they" or "the incumbent"; `his/her` → "their" or "the incumbent's"; `honest` → "candid"; `individual` → "single"/"lone", or "position"/"role" (as "this individual"); `s/he` → "they" or "the incumbent"; `trust` → "reliable"
- **Configured in:** `coded_terms.yaml` → `coded_terms.low`
- **Where the default came from:** our invention
- **Why it matters:** SFU's Part 6 lexicon lists these as terms to replace. We demoted them to `low` because they over-fire on ordinary JD prose ("the individual is responsible for…", "maintains the trust of stakeholders"), where a `medium` finding would drag the grade on a false positive. That demotion is OUR call, not SFU's. The generic pronouns (he/she, s/he, his/her) sit here too, though those are unambiguous.
- **If it changes:** Promoting them to `medium` doubles their score cost (HR-009 vs HR-010) and would fire on a large share of the archive. Note also that NO coded term blocks approval today (HR-004) — this is only about score and the reviewer's checklist.

#### HR-045 — Should only PARENTHESIZED percentages — "(40%)" — count as duty time allocations?

- **We ship:** `\((\d{1,3})\s*%\)`
- **Configured in:** `patterns.yaml` → `patterns.duty_allocation`
- **Where the default came from:** our invention
- **Why it matters:** Our pattern, not SFU's. A JD that writes "40% of time" or "40 percent" without brackets contributes NOTHING to the total, so its allocations can never fail the "must total 100%" gate — the JD escapes an SFU never-approve condition through a formatting choice. Chosen to keep false positives low (any bare "%" would sweep up "95% uptime").
- **If it changes:** Loosening the pattern catches more real violations and more noise. Interacts with HR-025 (a JD needs ≥2 matches before the gate runs at all).

#### HR-046 — Should a Position Summary that mentions parking, housing or relocation be BLOCKED from approval?

- **We ship:** `on-call`, `on call`, `shift work`, `evenings and weekends`, `evening and weekend`, `weekends and holidays`, `standby`, `stand-by`, `housing`, `parking`, `relocation`
- **Configured in:** `markers.yaml` → `markers.working_conditions`
- **Where the default came from:** our invention
- **Why it matters:** SFU's rule (Part 2B) is that the summary states the role's PURPOSE, not its working conditions. This specific word list is ours, and it BLOCKS approval (overridable). "housing", "parking" and "relocation" are the risky entries: a Parking Services or Residence & Housing role whose summary names its own domain is blocked by a rule about shift patterns.
- **If it changes:** Removing the three domain-noun entries removes a class of false blocks that falls hardest on exactly the units named. Adding entries widens a blocking gate — do it knowingly.

#### HR-047 — Should the phrase "action verb" appearing anywhere in a JD un-waivably block it as an unfinished draft?

- **We ship:** `action verb`, `how and why`, `what by`, `spell out acronyms`, `provide a high level summary`, `____`, `[insert`
- **Configured in:** `markers.yaml` → `markers.placeholder`
- **Where the default came from:** our invention
- **Why it matters:** These are the fragments of the template's own instructional text that a writer is supposed to delete. Finding one means the draft is unfinished — and that gate is NON-OVERRIDABLE (HR-005/HR-007): no reviewer can waive it. But "action verb", "how and why" and "what by" are ordinary English. A JD for a writing-instruction role, or one whose Qualifications say "coaches staff on how and why decisions are made", is permanently un-approvable until the words are removed. The strictest gate in the system rests on the loosest markers.
- **If it changes:** Either make the gate overridable (HR-007) or make the markers more specific (e.g. require the template's full instructional sentence). Both are config edits.

#### HR-048 — A JD is blocked for "incumbent-focused language" if its summary contains "my", "myself" or "I am". Is that the right test?

- **We ship:** `\bmy\b|\bmyself\b|\bi am\b`
- **Configured in:** `patterns.yaml` → `patterns.incumbent`
- **Where the default came from:** our invention
- **Why it matters:** SFU's Part 2B rule ("describe the position, not the person") is real; this three-word regex is our entire implementation of it, and it BLOCKS approval (SFU-APPROVE-SUMMARY-INCUMBENT). It is both too narrow — "he is responsible for…", the commonest incumbent-focused phrasing in the legacy archive, sails through — and capable of false positives on "my" inside quoted text.
- **If it changes:** Widening it blocks more of the archive; narrowing it makes a blocking gate nearly inert. Either way the approval bar moves, with no change to gates.yaml.

#### HR-049 — A "Senior" title with no stated supervisory scope is blocked. Should the test be the bare word "senior" anywhere in the title?

- **We ship:** `\bsenior\b`
- **Configured in:** `patterns.yaml` → `patterns.senior_title`
- **Where the default came from:** our invention
- **Why it matters:** Blocking (SFU-APPROVE-SENIOR-TITLE). SFU Part 3.5 reserves "Senior" for roles supervising junior peers — but the pattern matches the word ANYWHERE in the title, so "Advisor, Senior Leadership Programs" or "Senior Citizens Programs Coordinator" is blocked for having no supervisory scope. The rule is about a title PREFIX; the pattern does not know that.
- **If it changes:** Anchoring it to a leading "Senior" would remove a class of false blocks. A config edit.

#### HR-057 — Which rules are severe enough that their mere presence blocks approval — whatever the score, and without being named in any gate?

- **We ship:** `SFU-COMP-DUTIES`, `SFU-COMP-QUALS`, `SFU-COMP-SUMMARY`
- **Configured in:** `rule_catalog.yaml` → `rule_catalog.rules_by_severity.high`
- **Where the default came from:** our invention
- **Why it matters:** THERE ARE TWO ROUTES TO BLOCKING, NOT ONE. A rule blocks if it is named in a gate's rule_ids (pinned by HR-004) — OR if its severity reaches the severity floor (HR-003, currently `high`), because SFU-APPROVE-SEVERITY-FLOOR blocks on *any* finding at or above it. So raising a `low` drafting nudge like SFU-STRUCT-ACTION-VERB to `high` would silently make a non-approved verb block a JD, with no edit to gates.yaml at all. This entry pins the membership of every tier that reaches the floor, so that promotion cannot happen quietly.
- **If it changes:** Anything added to this list starts blocking approval. Note the list adjusts itself: if HR lowers the severity floor (HR-003) to `medium`, the `medium` tier becomes a blocking tier too, appears on the decision surface, and the build fails until it is registered here as well.

### Inherited hris calibration — not an SFU-published number

Carried over from the hris pipeline's calibration (`jd_rules_sfu_v3`). SFU publishes no scoring model at all, so these numbers were somebody else's judgement, not policy.

#### HR-008 — How many points should a HIGH-severity problem cost a job description?

- **We ship:** `20.0`
- **Configured in:** `scoring.yaml` → `scoring.severity_penalty.high`
- **Where the default came from:** hris calibration
- **Why it matters:** Sets what "high" means numerically. Three high-severity findings (missing summary + duties + qualifications) take a JD from 100 to ~59 — just under the approval floor (HR-001). The calibration and the floor were tuned to agree; moving either alone breaks that agreement.
- **If it changes:** Moves every score in the archive and therefore the whole grade distribution.

#### HR-009 — How many points should a MEDIUM-severity problem cost?

- **We ship:** `10.0`
- **Configured in:** `scoring.yaml` → `scoring.severity_penalty.medium`
- **Where the default came from:** hris calibration
- **Why it matters:** The tier most SFU never-approve conditions sit in (duty percentages, banned qualification phrases, leftover placeholders, most coded terms).
- **If it changes:** Six medium findings currently cost ~28 points, not 60, because of the decay factor (HR-012). Raising this without revisiting the decay changes that arithmetic sharply.

#### HR-010 — How many points should a LOW-severity problem cost?

- **We ship:** `5.0`
- **Configured in:** `scoring.yaml` → `scoring.severity_penalty.low`
- **Where the default came from:** hris calibration
- **Why it matters:** The drafting-nudge tier: action verbs, "how and why" detail, proficiency modifiers, a thin summary. These are the findings the archive fires most.
- **If it changes:** Because low-severity findings are common, this is the knob most likely to move the median JD across the approval floor in either direction.

#### HR-011 — Should advisory (INFO) findings cost any score at all?

- **We ship:** `0.0`
- **Configured in:** `scoring.yaml` → `scoring.severity_penalty.info`
- **Where the default came from:** hris calibration
- **Why it matters:** Zero, today: `info` findings appear on the reviewer's checklist but are free. That is what makes the two unverifiable restricted-title checks (Registrar, Human Resources — HR-032 / HR-033) harmless.
- **If it changes:** Giving `info` a non-zero cost would make every advisory observation drag the grade, including checks we KNOW cannot verify their own context.

#### HR-012 — Should the second, third and fourth problem of the same severity cost less than the first?

- **We ship:** `0.7`
- **Configured in:** `scoring.yaml` → `scoring.severity_decay`
- **Where the default came from:** hris calibration
- **Why it matters:** Diminishing returns: the k-th finding in a tier costs penalty × 0.7^k, so a tier can never cost more than penalty ÷ (1 − 0.7). A wall of minor nudges therefore cannot alone force an F, while genuine high-severity failures still drive a low grade. It is the reason a badly-extracted legacy document does not automatically score zero.
- **If it changes:** At 1.0 (no decay) a JD with ten low findings would score 50 and be blocked. At 0.0 only the worst finding in each tier would count at all.

#### HR-013 — What score earns an A?

- **We ship:** `90.0`
- **Configured in:** `scoring.yaml` → `scoring.grade_bands.A.min_score`
- **Where the default came from:** hris calibration
- **Why it matters:** The grade letters are what HR sees on the dashboard and in reports.
- **If it changes:** Re-labels the archive; does not by itself change what is approvable.

#### HR-014 — What score earns a B?

- **We ship:** `75.0`
- **Configured in:** `scoring.yaml` → `scoring.grade_bands.B.min_score`
- **Where the default came from:** hris calibration
- **Why it matters:** The grade letters are what HR sees on the dashboard and in reports.
- **If it changes:** Re-labels the archive; does not by itself change what is approvable.

#### HR-015 — What score earns a C — and is C really the pass mark?

- **We ship:** `60.0`
- **Configured in:** `scoring.yaml` → `scoring.grade_bands.C.min_score`
- **Where the default came from:** hris calibration
- **Why it matters:** This band is load-bearing: the grade floor (HR-002) is C and the score floor (HR-001) is 60.0, so this number is where the two floors meet. It is the de facto definition of "good enough to review".
- **If it changes:** Changing it without changing HR-001 and HR-002 silently decouples the score floor from the grade floor.

#### HR-016 — What score earns a D (rather than an F)?

- **We ship:** `40.0`
- **Configured in:** `scoring.yaml` → `scoring.grade_bands.D.min_score`
- **Where the default came from:** hris calibration
- **Why it matters:** Both D and F are below the approval floor, so this line only affects how a failing JD is *reported* — "needs work" vs "start over".
- **If it changes:** Cosmetic for approval; matters for how the archive triage reads.

#### HR-017 — Should a flawless job description score 100?

- **We ship:** `100.0`
- **Configured in:** `scoring.yaml` → `scoring.max_score`
- **Where the default came from:** hris calibration
- **Why it matters:** The perfect-JD baseline every penalty is subtracted from, and therefore the scale the approval floor (HR-001) and the grade bands are measured on. hris hardcoded it as a literal in Python; it is data here precisely so it is visible.
- **If it changes:** Changing the top of the scale silently rescales HR-001, HR-002 and every grade band at once. In practice: don't — tune the penalties and floors.

#### HR-018 — Should the score bottom out at 0, or can it go negative?

- **We ship:** `0.0`
- **Configured in:** `scoring.yaml` → `scoring.min_score`
- **Where the default came from:** hris calibration
- **Why it matters:** The floor a saturating pile of findings stops at. Keeps a badly-extracted legacy `.doc` from producing a meaningless −40.
- **If it changes:** Presentation of the worst documents only; nothing is approvable there anyway.

#### HR-026 — How many offending items should a single finding name before it says "and others"?

- **We ship:** `5`
- **Configured in:** `thresholds.yaml` → `thresholds.max_listed`
- **Where the default came from:** hris calibration
- **Why it matters:** Presentation, but not nothing: a JD with twelve non-approved action verbs shows the reviewer five of them. The reviewer sees a partial list and may not realise it is partial.
- **If it changes:** Purely what the reviewer reads; changes no decision. Judged low-stakes, but registered rather than waved through because it shapes what a human sees before pressing approve.

#### HR-027 — How many rule ids may a blocked-approval reason cite? (A second, independent copy of HR-026.)

- **We ship:** `5`
- **Configured in:** `gates.yaml` → `gates.max_listed`
- **Where the default came from:** hris calibration
- **Why it matters:** FOUND WHILE BUILDING THIS REGISTER: `max_listed` exists TWICE — once in thresholds.yaml (used by the validators, HR-026) and once in gates.yaml (used by the gate runner). They are independent knobs that happen to hold the same number, and NOTHING keeps them in step. Registering both at least makes a divergence visible.
- **If it changes:** Presentation only, but the duplication is a maintenance trap: an editor who changes "the" cap will likely change one of the two.

#### HR-029 — NINE of these 31 "coded terms" are NOT on SFU's published list — we added them. Does SFU HR adopt them, or should they go?

- **We ship:** `actress` → "actor"; `aggressive` → "rapid", "intense", or "large"; `agreement` → "contract" or "partnership"; `ambitious` → "motivated"; `businessman` → "business person" or "executive"; `chairman` → "chair" or "chairperson"; `championing` → "advocating" or "promoting"; `compassionate` → "caring"; `competitive` → "tough" or "intense"; `confidential` → "restricted"; `craftsman` → "artisan" or "craftsperson"; `dominant` → "top"; `fireman` → "firefighter"; `foreman` → "foreperson"; `guru` → "specialist"; `in-kind` → "non-monetary"; `man-hours` → "work hours"; `mankind` → "humankind"; `manmade` → "artificial", "manufactured", or "synthetic"; `manpower` → "workforce" or "staffing"; `middleman` → "intermediary" or "go-between"; `ninja` → "expert"; `persistent` → "tenacious" or "continuing"; `policeman` → "police officer"; `repairman` → "technician" or "repairer"; `rockstar` → "skilled"; `salesman` → "sales representative"; `spokesman` → "spokesperson"; `stewardess` → "flight attendant"; `waitress` → "server"; `workman` → "worker"
- **Configured in:** `coded_terms.yaml` → `coded_terms.medium`
- **Where the default came from:** hris calibration
- **Why it matters:** DO NOT READ THIS LIST AS SFU POLICY. It is NOT a transcription of SFU's Part 6 lexicon, and labelling it as one (which an earlier draft of this register did) would invite HR to rubber-stamp our own guesses as their published standard. The gendered occupational nouns (chairman, foreman, policeman, waitress, manpower, …) ARE SFU's. But NINE terms — aggressive, ambitious, championing, competitive, compassionate, confidential, dominant, agreement, in-kind — plus the three slang entries (rockstar, ninja, guru) do NOT appear in SFU's Part 6 list. hris added them ("plus a few widely-recognised coded terms") and we inherited them unexamined. Several over-fire badly on ordinary JD prose: "handles confidential information" and "negotiates the agreement" are flagged today. WORSE — see HR-058 — "compassionate" appears in SFU's OWN mandatory About-SFU paragraph, so SFU's boilerplate trips our lexicon.
- **If it changes:** Two separate calls. (a) The nine additions: adopt them as SFU policy, or drop them. (b) The one deliberate OMISSION: SFU's list also carries "supporting", which we do not flag (SFU marks it "vague — clarify" rather than a hard replace, and it appears in almost every JD); adding it would fire on most of the archive. Nothing here blocks approval today (HR-004) — it only costs score and fills the reviewer's checklist.

#### HR-030 — Should a job titled "Executive Director" that is NOT in the APEX group be blocked — and should the check even run when the employee group is unknown?

- **We ship:** `low`
- **Configured in:** `titles.yaml` → `titles.executive_director.severity`
- **Where the default came from:** hris calibration
- **Why it matters:** Two problems, one entry. (a) The finding is only `low` and does not block approval (HR-004), so a mis-titled Executive Director can be approved. (b) Worse: THE CHECK SILENTLY PASSES WHEN `employee_group` IS UNPARSED — a legacy JD whose group we could not extract escapes the restriction entirely, and says nothing about having done so. Restricted titles are an SFU governance rule (Part 3.5), so a rule that quietly no-ops is the wrong default.
- **If it changes:** Blocking on it would mean blocking JDs whose employee group we cannot read — a check that cannot know whether it is right should arguably not gate. The real fix may be a third state ("cannot verify") rather than a severity bump.

#### HR-032 — "Registrar" is reserved for AVPSI Student Services. We cannot verify that from a JD — should we still say anything?

- **We ship:** `info`
- **Configured in:** `titles.yaml` → `titles.registrar.severity`
- **Where the default came from:** hris calibration
- **Why it matters:** `info` means: shown on the reviewer's checklist, costs zero score (HR-011), blocks nothing. We chose to surface it as a prompt to a human rather than pretend to adjudicate it.
- **If it changes:** Any severity above `info` starts penalising JDs for a restriction the validator cannot actually check.

#### HR-033 — "Human Resources" is reserved for roles inside SFU HR (elsewhere: "personnel"). Same unverifiable-context problem — should we still say anything?

- **We ship:** `info`
- **Configured in:** `titles.yaml` → `titles.human_resources.severity`
- **Where the default came from:** hris calibration
- **Why it matters:** As HR-032. Note this rule fires on the SUBSTRING "human resources" in a title, so "Human Resources Advisor" inside SFU HR — a correct title — is flagged too. Harmless at `info`; not harmless at anything higher.
- **If it changes:** Raising the severity would penalise SFU HR's own correctly-titled roles.

#### HR-034 — A JD with no "Impact of Decision Making" section is incomplete. Should it be blocked from approval?

- **We ship:** `medium`
- **Configured in:** `rule_catalog.yaml` → `rule_catalog.SFU-COMP-DECISION.default_severity`
- **Where the default came from:** hris calibration
- **Why it matters:** It is NOT blocked today (absent from HR-004): `medium` costs 10 points and appears on the checklist, but the JD is still approvable. The section is a Hay evaluation input — a JD missing it cannot be properly evaluated for classification, which is arguably a stronger reason to block than several things we DO block on.
- **If it changes:** Promoting to `high` would make it trip the severity floor (HR-003) automatically; adding it to SFU-APPROVE-MANDATORY-SECTIONS would make it un-waivable (HR-006). Either is a one-line YAML edit.

#### HR-035 — Same question for "Problem Solving & Level of Supervision" — should a missing section block approval?

- **We ship:** `medium`
- **Configured in:** `rule_catalog.yaml` → `rule_catalog.SFU-COMP-PROBLEM.default_severity`
- **Where the default came from:** hris calibration
- **Why it matters:** As HR-034: the other Hay input, also `medium`, also non-blocking today. Decide the pair together.
- **If it changes:** See HR-034.

#### HR-036 — SFU says a JD has 3–5 major duties. Should MORE THAN FIVE block approval?

- **We ship:** `medium`
- **Configured in:** `rule_catalog.yaml` → `rule_catalog.SFU-STRUCT-DUTIES-TOO-MANY.default_severity`
- **Where the default came from:** hris calibration
- **Why it matters:** This is the side of the duty-count rule that SFU actually names as the defect ("more than 3-5 main responsibilities"), and we do NOT gate it (HR-004). We defaulted to leniency because duty granularity is an authoring judgement and gating it would block a large slice of the archive on a formatting call. That is a reasonable position — but it is OUR position, not SFU's.
- **If it changes:** Gating it costs one line in gates.yaml (add SFU-STRUCT-DUTIES-TOO-MANY to a gate's rule_ids). Measure against the Phase-2.5 archive baseline first.

#### HR-037 — Should FEWER than three duties be a defect at all?

- **We ship:** `medium`
- **Configured in:** `rule_catalog.yaml` → `rule_catalog.SFU-STRUCT-DUTIES-TOO-FEW.default_severity`
- **Where the default came from:** hris calibration
- **Why it matters:** SFU names the over-run, not the under-run (HR-021). Firing at `medium` — the same cost as a genuine SFU never-approve condition — on a JD that consolidated its work into two well-written duties is our invention, and is arguably too harsh relative to HR-036, which does not block at all.
- **If it changes:** Demoting to `low` (5 points) would put it in line with the other drafting nudges. Note the inconsistency: today a JD with 2 duties and a JD with 9 duties are penalised identically.

#### HR-038 — Should a Position Summary shorter than 100 words be a defect at all?

- **We ship:** `low`
- **Configured in:** `rule_catalog.yaml` → `rule_catalog.SFU-STRUCT-SUMMARY-TOO-SHORT.default_severity`
- **Where the default came from:** hris calibration
- **Why it matters:** The summary-length rule is split in two precisely so this question can be answered separately (HR-019/HR-020): the over-run blocks approval, the under-run is a `low` nudge that only costs score. Firing on the under-run at all is our choice — SFU states a maximum.
- **If it changes:** Low stakes on its own, but it is one of the most frequently-fired rules in the archive, so it moves the median score.

#### HR-039 — Is the territorial acknowledgement's WORDING correct — and is a missing territorial acknowledgement really only a `low` finding?

- **We ship:** `low`
- **Configured in:** `rule_catalog.yaml` → `rule_catalog.SFU-COMP-TERRITORIAL.default_severity`
- **Where the default came from:** hris calibration
- **Why it matters:** CLAUDE.md's standing open flag, and the one entry here that blocks PUBLICATION rather than development. TWO distinct gaps. (a) SEVERITY: a missing acknowledgement is `low` (5 points) — yet it DOES block approval via the EDI-footer gate, so a `low` finding is doing a `high` finding's job. (b) WORDING: THE SYSTEM ONLY CHECKS PRESENCE, NEVER TEXT. There is no configured canonical wording anywhere in the rulebook data — nothing verifies the JD carries SFU's current official acknowledgement rather than an outdated or paraphrased one. Deciding the wording implies ADDING a config key to hold it.
- **If it changes:** Must be signed off against SFU's current official text before any external distribution (Phase 6). Until then every "approved" JD carries an unverified acknowledgement.

#### HR-040 — SFU's knowledge tiers are EXCELLENT / WORKING / [NO MODIFIER]. We encode the third as the literal word "none". Is that the right representation?

- **We ship:** `excellent`, `none`, `working`
- **Configured in:** `qualifications.yaml` → `qualifications.knowledge_modifiers`
- **Where the default came from:** hris calibration
- **Why it matters:** "[NO MODIFIER]" in the rulebook means *the absence of a modifier*. We model it as a sentinel value `none`, which means a JD that literally writes "None knowledge of Python" passes the modifier-vocabulary check, while a knowledge item with genuinely no modifier depends on the parser emitting the sentinel. A representation choice, made in hris, that SFU never made.
- **If it changes:** Modelling absence as `null` instead would be a parser + validator change, not a config edit — the one entry here where ratifying a change is NOT free. Flagged so that is known before HR is asked.

#### HR-050 — What counts as "a degree requirement" in a JD?

- **We ship:** `\b(bachelor|master|phd|doctorate|degree)\b`
- **Configured in:** `patterns.yaml` → `patterns.degree_mention`
- **Where the default came from:** hris calibration
- **Why it matters:** Triggers the check that a stated degree names a discipline and allows related fields (SFU-QUAL-DEGREE-DISCIPLINE, `low`, non-blocking). Matching the bare word "degree" anywhere means "a degree of independent judgement" in a duty trips it.
- **If it changes:** Only score and the checklist; not the approval bar.

#### HR-051 — What wordings count as "allows a related or relevant discipline"?

- **We ship:** `(related|relevant)\s+(discipline|field)|or\s+other\s+relevant`
- **Configured in:** `patterns.yaml` → `patterns.related_discipline`
- **Where the default came from:** hris calibration
- **Why it matters:** The other half of HR-050. A JD that says "…or a closely allied field" or "…in a comparable area" satisfies the rulebook in substance but not this pattern. Same shape of problem as the literal "equivalent combination" match (HR-042) — but this one is advisory, not blocking.
- **If it changes:** Only score and the checklist.

#### HR-054 — Must an ability literally start with "Ability to" / "Able to" to count as observable behaviour?

- **We ship:** `ability to`, `able to`
- **Configured in:** `qualifications.yaml` → `qualifications.ability_prefixes`
- **Where the default came from:** hris calibration
- **Why it matters:** SFU Part 5.3 gives the FORMAT 'Ability to [observable behavior]'. Our check is a literal prefix test, so "Demonstrated ability to lead teams" — which is the same thing, better written — is flagged (SFU-AUTH-ABILITIES-OBSERVABLE, `low`, non-blocking).
- **If it changes:** Score and checklist only; not the approval bar.

#### HR-058 — SFU's mandatory, "do not edit" About SFU paragraph contains the word "compassionate" — which our lexicon flags as a coded term. Every compliant JD is penalised. What should give?

- **We ship:** `"caring"`
- **Configured in:** `coded_terms.yaml` → `coded_terms.medium.compassionate`
- **Where the default came from:** hris calibration
- **Why it matters:** SFU's pre-populated About-SFU block reads "We are unconventional, fearless, COMPASSIONATE, approachable and ready." The template says do not edit it. Our lexicon files "compassionate" at `medium` — one of the nine terms that are NOT on SFU's own published list (HR-029). Measured on a clean JD: WITHOUT the About-SFU paragraph, score 91.5 / grade A, no coded-term finding. WITH it — i.e. exactly as SFU mandates — score 81.5 / grade B, one `medium` coded-term finding. A JD is penalised 10 points for obeying SFU, and penalised again (SFU-COMP-ABOUT) if it leaves the paragraph out. It cannot win. This is almost certainly the highest-frequency false positive in the system, and because it fires on nearly every compliant JD it systematically DEPRESSES THE WHOLE ARCHIVE BASELINE — the very baseline the score floor (HR-001) is supposed to be ratified against. Ratify HR-001 with this fixed, or the floor is calibrated against a 10-point artefact.
- **If it changes:** Three ways out, all config: drop "compassionate" from the lexicon (it is not SFU's term anyway); demote it to `low`; or exclude the About-SFU boilerplate from the lexicon's scan (a validator scope change — NOT free, see HR-041 for the same shape of problem). Left as-is deliberately: this register documents the behaviour, it does not change it.

#### HR-059 — What are SFU's job-title seniority levels — the ladder every title is classified onto (and, later, compared and de-duplicated by)?

- **We ship:** `vp`, `chief`, `director`, `manager`, `lead`, `associate`, `assistant`
- **Configured in:** `titles.yaml` → `titles.families`
- **Where the default came from:** hris calibration
- **Why it matters:** hris shipped this ladder claiming it as "SFU's official title ladder (Toolkit p18-19)". IT IS NOT IN THE RULEBOOK. docs/rulebook/sfu-jd-standards.txt has no title-family ladder at all: `chief` does not appear anywhere in it, and the only occurrence of "VP" (Part 3.5) lists VP as a RESTRICTED title — a title you may not use — not as a seniority family. So the seven rungs below are an inherited guess, and the guess is load-bearing: the ladder is the seniority dimension of title classification, it will normalize titles for dedup Tier-3 (deciding whether "Manager, Research" and "Research Lead" are the same role), and it drives the composer's facets. A missing rung is not a cosmetic gap — a ladder with no `supervisor` or `coordinator` rung cannot classify those titles at all, and they fall to `unmapped`. This is HR-029's problem (nine coded terms SFU never published, shipped as if it had) in the title dimension.
- **If it changes:** Config only — add, remove or reorder rungs in titles.yaml. Nothing here blocks approval; no gate reads it. But HR should either point us at the real SFU ladder (the Job Titling Guide / Toolkit p18-19, which this repo does not hold), confirm these seven, or replace them. NOTE the SEPARATE functional dimension (assistant / coordinator / analyst / officer / specialist / consultant / manager / associate director / director / executive) IS rulebook-sourced — Part 3.3's Application Table — and is not in question here.

#### HR-060 — When a job title carries TWO seniority words — "Associate Director" is both an associate and a director — which one decides the family?

- **We ship:** `vp`, `chief`, `manager`, `director`, `lead`, `assistant`, `associate`
- **Configured in:** `titles.yaml` → `titles.family_match_order`
- **Where the default came from:** hris calibration
- **Why it matters:** The classifier tries the families in THIS order and the first keyword that matches wins. That makes the order a policy statement, not an implementation detail, and it is deliberately NOT the seniority ladder of HR-059: `manager` is tried before `director`, which is the *entire* reason "Associate Director, Advancement" classifies as a manager rather than a director. Likewise `assistant` before `associate`. Shuffle two rungs and real titles change family with no other edit anywhere. hris buried this ordering in a Python tuple with a one-line comment; SFU has never been asked whether an Associate Director is a manager.
- **If it changes:** Config only. Reordering changes which family a *multi-keyword* title lands in — it cannot change a title that carries only one family keyword. Nothing blocks approval on it (no gate reads the family); it feeds titling advice, and will feed title normalization for dedup Tier-3 and the composer's facets.

#### HR-061 — Which title words signal each seniority family?

- **We ship:** `vp` → ['vice president', 'associate vice', ' avp ', ' vp ']; `chief` → ['chief', ' cio ', ' cfo ', ' cto ', ' ceo ', ' coo ']; `manager` → ['associate director', 'manager', 'supervisor']; `director` → ['director']; `lead` → ['team lead', ' lead ']; `assistant` → ['assistant']; `associate` → ['associate', 'representative']
- **Configured in:** `titles.yaml` → `titles.family_keywords`
- **Where the default came from:** hris calibration
- **Why it matters:** This is the ladder of HR-059 made operational: a rung with no keyword can never be matched, and a word missing from a rung sends every title carrying it to `unmapped`. The list is small and inherited — `supervisor` is a manager, `representative` is an associate, and nothing here recognises `coordinator`, `officer`, `analyst` or `specialist` as a seniority at all (they are the FUNCTIONAL dimension, HR-063). The space-padded entries (" vp ", " cio ") match a whole word only; the unpadded ones are substrings, so "manager" also matches "Managerial Accountant".
- **If it changes:** Config only. Adding a word makes titles carrying it classify into that family; removing one sends them to `unmapped` (visible, not silent). Advisory — no gate reads it.

#### HR-062 — SFU writes a supervisory title as "Manager, Laboratory Operations" and a non-supervisory one as "Laboratory Operations Manager" (Part 3.4). WHICH families, written first and followed by a comma, actually signal supervision?

- **We ship:** `chief`, `director`, `lead`, `manager`, `vp`
- **Configured in:** `titles.yaml` → `titles.comma_supervisory_families`
- **Where the default came from:** hris calibration
- **Why it matters:** The comma FORMAT rule is SFU's (Part 3.4). The set of families it applies to is not: hris chose these five. It is the guard that stops "Software Developer, Platform" reading as a supervisory title, so it must exclude non-role prefixes — but it also decides that a `lead` supervises and an `associate` does not, which is a real HR judgement nobody made. Note `lead` is in the set even though SFU's own ladder does not exist (HR-059), so this compounds an unratified default with another one.
- **If it changes:** Config only; advisory. It sets `TitleClassification.comma_supervisory`, which is surfaced to reviewers and (later) used to sanity-check a JD's Relationships section against its title. No gate reads it.

#### HR-064 — "Executive Director" and "Associate Director" both contain "Director". Which functional type wins?

- **We ship:** `executive`, `associate_director`, `director`, `manager`, `consultant`, `specialist`, `officer`, `analyst`, `coordinator`, `assistant`
- **Configured in:** `titles.yaml` → `titles.function_match_order`
- **Where the default came from:** hris calibration
- **Why it matters:** The Application Table (HR-063) is SFU's; the ORDER its rows are tried in is not — hris chose it, and it is what resolves the overlaps. `executive` is tried first, so "Executive Director" is an executive (consistent with SFU reserving that title for APEX roles, Part 3.5 / SFU-AUTH-TITLE-EXEC-DIR); then `associate_director`, so "Associate Director" is not a director. Both readings are defensible and neither is written down by SFU. Reorder and titles change function.
- **If it changes:** Config only, and only for titles carrying two function words. Advisory.

#### HR-066 — Which words in a JD's education requirement mean "graduate-level"?

- **We ship:** `phd`, `doctora`, `master`
- **Configured in:** `hay_signals.yaml` → `hay_signals.edu_high`
- **Where the default came from:** hris calibration
- **Why it matters:** The single biggest contributor to the Know-How signal (HR-073 gives it 3.0 points, more than any other). Matched as substrings of the `education` qualifications only: "doctora" catches doctoral/doctorate, "master" catches master's — and also "Masters of the craft" or a "Mastercard" reconciliation duty, if either ever appeared in an education line.
- **If it changes:** Config only. Advisory: it moves a Hay SIGNAL, never a grade and never a gate.

#### HR-067 — Which words in a JD's education requirement mean "undergraduate"?

- **We ship:** `bachelor`, `undergraduate`, `degree`
- **Configured in:** `hay_signals.yaml` → `hay_signals.edu_mid`
- **Where the default came from:** hris calibration
- **Why it matters:** The fallback when no graduate cue is found (2.0 points, HR-073). Note `degree` is deliberately broad and will also match "Master's degree" — harmless only because the graduate cue is tested first. A JD saying "Diploma or equivalent" scores nothing here.
- **If it changes:** Config only; advisory.

#### HR-068 — Which language in the Problem Solving section signals independent, non-routine thinking?

- **We ship:** `independent`, `judgment`, `judgement`, `novel`, `complex`, `ambiguous`, `unprecedented`, `analyze`, `analyse`, `evaluate`, `interpret`, `strategic`, `non-routine`, `creative`
- **Configured in:** `hay_signals.yaml` → `hay_signals.ps_challenge`
- **Where the default came from:** hris calibration
- **Why it matters:** Each distinct phrase found adds a full point (HR-076) — more than the entire section is worth for existing — so a JD's Problem-Solving signal is close to a count of how many of these 14 words its author happened to use. It rewards a vocabulary, not a role: "Resolves novel, ambiguous, complex problems requiring independent judgment" scores 5 for one sentence. Both spellings of judgment/judgement and analyze/analyse are listed, so a JD using both would double-count.
- **If it changes:** Config only; advisory. Adding words makes the signal easier to raise.

#### HR-069 — Which language in the Problem Solving section signals routine, closely supervised work — and should it really SUBTRACT?

- **We ship:** `routine`, `defined procedure`, `established procedure`, `under supervision`, `close supervision`, `step-by-step`, `prescribed`, `clearly defined`
- **Configured in:** `hay_signals.yaml` → `hay_signals.ps_routine`
- **Where the default came from:** hris calibration
- **Why it matters:** These are the only NEGATIVE cues in the whole estimator (HR-076 weights each hit -1.0). A JD that accurately describes a junior role — "handles routine issues using established procedure, under close supervision" — is pushed to a low Problem-Solving signal, which is the intent; but the same words in a senior JD ("establishes the procedures others follow") are penalised just as hard, because the match is a bare substring with no sense of who is doing what. Note "under supervision" does NOT match "under close supervision" (the words are not adjacent) — "close supervision" is what catches it.
- **If it changes:** Config only; advisory. Setting the weight to 0 (HR-076) neutralises the list without deleting it.

#### HR-070 — Which language in the Impact of Decision Making section signals freedom to act and magnitude of impact?

- **We ship:** `without approval`, `without prior approval`, `autonomous`, `independently`, `authority`, `approve`, `sign`, `budget`, `strategic`, `organization-wide`, `institution`, `significant impact`, `accountable`, `final decision`, `discretion`
- **Configured in:** `hay_signals.yaml` → `hay_signals.acc_autonomy`
- **Where the default came from:** hris calibration
- **Why it matters:** The whole Accountability signal, one point per distinct phrase (HR-079). Known quirks HR should see rather than have hidden: `sign` is a substring, so it also fires on "design" and "significant"; `approve` fires on "requires approval from the Director", which is the OPPOSITE of autonomy; and `without approval` / `without prior approval` overlap, so "without prior approval" scores one, not two ("without approval" is not a substring of it). `institution` fires on the boilerplate word "institution" wherever it appears.
- **If it changes:** Config only; advisory — this can never produce a grade.

#### HR-071 — Which Toolkit skill modifiers count as "advanced" depth for the Know-How signal?

- **We ship:** `advanced`, `expert`
- **Configured in:** `hay_signals.yaml` → `hay_signals.advanced_skill_modifiers`
- **Where the default came from:** hris calibration
- **Why it matters:** SFU's Toolkit defines the skill modifier scale (basic / intermediate / advanced / expert). Which END of it counts as depth is hris's call: `intermediate` scores nothing today, so a JD requiring six intermediate skills reads as no more skilled than one requiring none.
- **If it changes:** Config only; advisory.

#### HR-072 — Which Toolkit knowledge modifiers count as top-level knowledge?

- **We ship:** `excellent`
- **Configured in:** `hay_signals.yaml` → `hay_signals.excellent_knowledge_modifiers`
- **Where the default came from:** hris calibration
- **Why it matters:** The knowledge scale is excellent / working / none. Only `excellent` scores (1.0, HR-073) — `working` knowledge contributes nothing at all.
- **If it changes:** Config only; advisory.

#### HR-073 — How much is each Know-How signal worth?

- **We ship:** `education_graduate` → 3.0; `education_undergraduate` → 2.0; `many_advanced_skills` → 2.0; `some_advanced_skills` → 1.0; `excellent_knowledge` → 1.0; `supervisory_scope` → 1.0; `broad_qualifications` → 1.0
- **Configured in:** `hay_signals.yaml` → `hay_signals.know_how_points`
- **Where the default came from:** hris calibration
- **Why it matters:** The weights that turn a JD into a Know-How score, which HR-075 then turns into low/moderate/high. Education dominates: a graduate degree alone (3.0) is worth as much as supervising staff PLUS excellent knowledge PLUS a broad qualification set (1.0 each), and it alone reaches the `moderate` cutoff. SFU has published no weighting at all — these seven numbers are somebody else's judgement about what makes a job senior.
- **If it changes:** Config only; advisory. Changing a weight re-levels every JD's Know-How signal. Nothing blocks approval on it and no grade is ever derived from it.

#### HR-074 — How many advanced skills is "many", and how many qualification kinds is "broad"?

- **We ship:** `advanced_skills_for_many` → 3; `qualification_kinds_for_broad` → 4
- **Configured in:** `hay_signals.yaml` → `hay_signals.know_how_counts`
- **Where the default came from:** hris calibration
- **Why it matters:** The two counting cliffs inside Know-How. 3 advanced/expert skills scores 2.0; 2 scores 1.0 — a one-skill difference halves the contribution. 4 distinct qualification kinds (of the six the template has: education, experience, knowledge, skill, ability, security) scores 1.0 for "breadth", which rewards a JD for filling in more sections as much as for the role being broader.
- **If it changes:** Config only; advisory.

#### HR-075 — At what Know-How score does a role read as moderate, and at what score high?

- **We ship:** `moderate` → 3.0; `high` → 5.0
- **Configured in:** `hay_signals.yaml` → `hay_signals.know_how_levels`
- **Where the default came from:** hris calibration
- **Why it matters:** The cutoffs that turn the score into the only thing a human sees. With HR-073's weights, `moderate` (3.0) is reached by a graduate degree ALONE, and `high` (5.0) needs roughly a graduate degree plus three advanced skills. Below 3.0 the role reads `low`. hris hardcoded these as `_level(score, mod=3, hi=5)` in a Python default argument.
- **If it changes:** Config only; advisory — a Hay SIGNAL, never a Hay grade. Two levels may not share a cutoff, and every level except `low` (the floor) must have one, or the rulebook does not load.

#### HR-076 — How much is each Problem-Solving signal worth — and how much does routine language cost?

- **We ship:** `section_item` → 0.5; `challenge_hit` → 1.0; `routine_hit` → -1.0
- **Configured in:** `hay_signals.yaml` → `hay_signals.problem_solving_points`
- **Where the default came from:** hris calibration
- **Why it matters:** A single challenge word (HR-068) is worth twice as much as an entire written Problem Solving entry, and a single routine word (HR-069) cancels a challenge word outright. That makes the Problem-Solving signal mostly a word count. The NEGATIVE weight is the only one in the estimator and is the strongest claim it makes: that describing supervision honestly is evidence of a less demanding role.
- **If it changes:** Config only; advisory. Set `routine_hit` to 0.0 to keep the routine lexicon as evidence while removing its penalty.

#### HR-077 — How many Problem Solving entries are worth scoring before length stops counting?

- **We ship:** `section_items_scored` → 3
- **Configured in:** `hay_signals.yaml` → `hay_signals.problem_solving_counts`
- **Where the default came from:** hris calibration
- **Why it matters:** Credit for merely HAVING a section, capped at 3 entries (1.5 points) so a JD cannot inflate its signal by padding the list. Length is not depth — but the cap also means the 4th genuinely distinct problem a role solves counts for nothing.
- **If it changes:** Config only; advisory.

#### HR-078 — At what Problem-Solving score does a role read as moderate, and at what score high?

- **We ship:** `moderate` → 1.5; `high` → 3.0
- **Configured in:** `hay_signals.yaml` → `hay_signals.problem_solving_levels`
- **Where the default came from:** hris calibration
- **Why it matters:** With HR-076's weights, a JD with three Problem Solving entries and no challenge vocabulary at all scores exactly 1.5 and reads `moderate` — the signal can be earned by writing three sentences. `high` needs three challenge words net of any routine language. hris hardcoded these as `mod=1.5, hi=3`.
- **If it changes:** Config only; advisory.

#### HR-079 — How much is each Accountability signal worth?

- **We ship:** `section_item` → 0.5; `autonomy_hit` → 1.0; `supervisory_scope` → 2.0; `external_breadth` → 1.0
- **Configured in:** `hay_signals.yaml` → `hay_signals.accountability_points`
- **Where the default came from:** hris calibration
- **Why it matters:** Supervising staff is worth 2.0 — twice any single autonomy phrase, and twice what supervision is worth to Know-How (HR-073 gives it 1.0). Whether "freedom to act" should be dominated by headcount at all is a real Hay question, and this answers it by default. External breadth (HR-080) adds a point for having enough external contacts listed.
- **If it changes:** Config only; advisory. The Accountability signal never becomes an Accountability grade.

#### HR-080 — How many Impact-of-Decision-Making entries are scored, and how many external relationships count as "breadth of impact"?

- **We ship:** `section_items_scored` → 3; `external_for_breadth` → 3
- **Configured in:** `hay_signals.yaml` → `hay_signals.accountability_counts`
- **Where the default came from:** hris calibration
- **Why it matters:** `external_for_breadth: 3` says a role dealing with three external parties has institution-scale impact and one dealing with two does not. It counts LIST ENTRIES, so a JD that writes "Vendors, government, and peer institutions" as a single line scores 0 while one that writes three lines scores 1 — the same role, formatted differently.
- **If it changes:** Config only; advisory.

#### HR-081 — At what Accountability score does a role read as moderate, and at what score high?

- **We ship:** `moderate` → 2.0; `high` → 4.0
- **Configured in:** `hay_signals.yaml` → `hay_signals.accountability_levels`
- **Where the default came from:** hris calibration
- **Why it matters:** With HR-079's weights, supervising staff alone (2.0) reaches `moderate` with no decision-making language whatsoever, and `high` (4.0) is two autonomy phrases away. hris hardcoded these as `mod=2, hi=4`.
- **If it changes:** Config only; advisory.

### From SFU's published rulebook — but read the caveats

The value is transcribed from SFU's own rulebook — but *how we act on it* (whether it merely costs score or actually blocks approval, and how widely we search for it) is still ours. Each entry says which part is SFU's.

#### HR-019 — SFU's template says a Position Summary is 100–150 words. Should a SHORT summary (under 100) be flagged at all — and should it ever block approval?

- **We ship:** `100`
- **Configured in:** `thresholds.yaml` → `thresholds.summary_min_words`
- **Where the default came from:** SFU rulebook (Part 2B)
- **Why it matters:** Note the asymmetry, which is the real question here. SFU states a MAXIMUM ("100-150 words MAXIMUM") and its Part 11.6 never-approve list names only the over-run. So the 100-word floor is rulebook text, but CHOOSING TO FIRE on it is ours: SFU-STRUCT-SUMMARY-TOO-SHORT is a `low` advisory that costs score and does NOT block (HR-038). A 60-word summary that says everything necessary is penalised today.
- **If it changes:** Raising it makes more of the archive score lower; setting the rule non-firing would require removing the check, which is a rulebook question, not a code one.

#### HR-020 — Is 150 words the hard maximum for a Position Summary?

- **We ship:** `150`
- **Configured in:** `thresholds.yaml` → `thresholds.summary_max_words`
- **Where the default came from:** SFU rulebook (Part 2B)
- **Why it matters:** This one IS an SFU never-approve condition, and we gate it: a summary over 150 words blocks approval (overridable). It is the only two-sided threshold whose over-run blocks and whose under-run does not.
- **If it changes:** Legacy JDs commonly run long. This threshold is a major driver of how many archive documents are blocked on first pass.

#### HR-021 — SFU says 3–5 major responsibilities. Should FEWER than 3 duties be flagged — and should it block?

- **We ship:** `3`
- **Configured in:** `thresholds.yaml` → `thresholds.duties_min`
- **Where the default came from:** SFU rulebook (Part 2C)
- **Why it matters:** Rulebook text, but the same asymmetry as HR-019: SFU names the over-run as the defect ("more than 3-5 main responsibilities"). Firing on the under-run is our choice, and it is advisory only (HR-037).
- **If it changes:** Duty granularity is an authoring judgement — one author's 2 duties are another's 4. Blocking on this would be blocking on a formatting call.

#### HR-022 — Is 5 the maximum number of major duties?

- **We ship:** `5`
- **Configured in:** `thresholds.yaml` → `thresholds.duties_max`
- **Where the default came from:** SFU rulebook (Part 2C)
- **Why it matters:** Rulebook text. But see HR-036: exceeding it does NOT block approval today, even though this is the side SFU actually names. That is the single biggest "we defaulted to leniency" call in the policy.
- **If it changes:** Gating the over-run (a one-line YAML edit — add SFU-STRUCT-DUTIES-TOO-MANY to a gate's rule_ids) would block a large slice of the archive on a duty-count technicality. HR to ratify.

#### HR-031 — Is "Executive Director" reserved for APEX-classified roles, and only those?

- **We ship:** `apex`
- **Configured in:** `titles.yaml` → `titles.executive_director.reserved_for_employee_group`
- **Where the default came from:** SFU rulebook (Part 3.5)
- **Why it matters:** The only restricted title whose restriction is checkable from the JD alone (the other two need organisational context — HR-032, HR-033). If the APEX claim is wrong or out of date, the one title check that CAN fire is firing on the wrong condition.
- **If it changes:** Confirm against the current Job Titling Guide. Setting it to null would turn this into a third unverifiable advisory.

#### HR-041 — Should the banned-phrase check ("may include", "assets", "preferences") search the WHOLE document, or only the Qualifications section?

- **We ship:** `may include`, `assets`, `preferences`
- **Configured in:** `qualifications.yaml` → `qualifications.banned_phrases`
- **Where the default came from:** SFU rulebook (Part 2H)
- **Why it matters:** The phrases are SFU's (they signal *desired* rather than the *minimum* needed). The SCOPE is ours, and it is wrong in a knowable way: the match runs over the whole raw document, so a DUTY that mentions "capital assets" or "manages physical assets" raises a QUALIFICATIONS gate and BLOCKS APPROVAL. Every facilities, finance and property JD in the archive is a candidate. The gate is overridable for exactly this reason — but a reviewer has to waive it by hand, with a written reason, every time.
- **If it changes:** Narrowing the scope to the Qualifications section removes a large class of false blocks. Removing "assets" from the list would diverge from SFU's text. This is the highest-frequency false block we know of.

#### HR-042 — Must a JD contain the literal phrase "equivalent combination" — or is any equivalency wording acceptable?

- **We ship:** `equivalent combination`
- **Configured in:** `qualifications.yaml` → `qualifications.equivalent_combination`
- **Where the default came from:** SFU rulebook (Part 2H)
- **Why it matters:** SFU requires an equivalency path so the bar does not exclude equivalently-qualified applicants — a genuine equity requirement, and it BLOCKS approval. But the check is a literal case-folded substring: a JD that says "or an equivalent mix of education and experience" is blocked despite satisfying the requirement in substance.
- **If it changes:** Accepting more wordings means either a list of accepted phrases or a regex — both are config, no code change. Leaving it strict means reviewers waive it by hand on correctly-written JDs.

#### HR-043 — SFU's action-verb glossary lists "accountable" — an adjective, not a verb. Should a duty be allowed to start with it?

- **We ship:** `true`
- **Configured in:** `action_verbs.yaml` → `action_verbs.approved.accountable`
- **Where the default came from:** SFU rulebook (Glossary)
- **Why it matters:** It is in SFU's published glossary, so we kept it (fidelity over tidiness). The consequence: "Accountable for the departmental budget" passes the action-verb check, while "Accountable to the Director" — not a duty at all — also passes. The glossary is SFU's to fix, not ours. CAVEAT ON THE PROVENANCE: the glossary lives in the JD Toolkit, which is NOT among the sources shipped in this repo (docs/rulebook/sfu-jd-standards.txt does not contain it), so the citation is inherited from hris and CANNOT BE VERIFIED FROM OUR OWN SOURCES. Confirming it is part of the decision.
- **If it changes:** Removing it tightens the check but diverges from SFU's own glossary. Purely a YAML edit either way.

#### HR-044 — Same for "responsible" — an adjective in SFU's action-verb glossary.

- **We ship:** `true`
- **Configured in:** `action_verbs.yaml` → `action_verbs.approved.responsible`
- **Where the default came from:** SFU rulebook (Glossary)
- **Why it matters:** As HR-043. "Responsible for…" is the single most common opening in the legacy archive, and SFU's glossary blesses it — while the same rulebook asks for action-verb-led duties. Decide the pair with HR-043. The same provenance caveat applies: the glossary is not among the sources shipped in this repo, so the citation cannot be verified from them.
- **If it changes:** Removing it would fire the action-verb rule on a very large share of the archive at once.

#### HR-052 — Qualifications must run Knowledge -> Skills -> Abilities. This mapping IS that order. Is it right?

- **We ship:** `knowledge` → 0; `skill` → 1; `ability` → 2
- **Configured in:** `qualifications.yaml` → `qualifications.ksa_rank`
- **Where the default came from:** SFU rulebook (Part 5.4)
- **Why it matters:** The order is SFU's (Part 5.4) and it BLOCKS approval (SFU-APPROVE-KSA-ORDER). Registered because it is the one place where the *values* of a config mapping are the policy: permuting the ranks would silently invert what a blocking gate enforces. Note it says nothing about education or experience items, which are unranked and therefore never out of order.
- **If it changes:** Changing a rank re-points a blocking gate. Ranking education/experience too would extend the gate to items it ignores today.

#### HR-053 — Are BASIC / INTERMEDIATE / ADVANCED / EXPERT the only accepted skill levels?

- **We ship:** `advanced`, `basic`, `expert`, `intermediate`
- **Configured in:** `qualifications.yaml` → `qualifications.skill_modifiers`
- **Where the default came from:** SFU rulebook (Part 5.2)
- **Why it matters:** SFU's Toolkit vocabulary, transcribed. A skill tagged "proficient" or "strong" — common in the archive — is flagged as non-standard (SFU-QUAL-MODIFIER-VOCAB, `low`, non-blocking).
- **If it changes:** Accepting synonyms reduces noise but diverges from the published vocabulary. Score and checklist only.

#### HR-055 — Is SFU's 116-verb action-verb glossary the right list — and should a duty that starts with a good verb NOT on it be flagged?

- **We ship:** `accomplishes`, `accountable`, `accounts`, `acknowledges`, `acts`, `adapts`, `administers`, `advises`, `allocates`, `analyzes`, `applies`, `approves`, `arranges`, `assemble`, `assembles`, `assesses`, `assigns`, `assists`, `assures`, `attends`, `audits`, `authorizes`, `calculates`, `carries`, `checks`, `collaborates`, `communicates`, `compiles`, `composes`, `computes`, `conducts`, `constructs`, `contributes`, `controls`, `coordinates`, `corrects`, `counsels`, `creates`, `decides`, `delegates`, `demonstrates`, `designs`, `determines`, `develops`, `directs`, `disciplines`, `distributes`, `drafts`, `enforces`, `ensures`, `establishes`, `estimates`, `evaluates`, `examines`, `exercises`, `facilitates`, `forecasts`, `formulates`, `guides`, `handles`, `identifies`, `implements`, `initiates`, `inspects`, `instructs`, `integrates`, `interprets`, `interviews`, `investigates`, `leads`, `maintains`, `manages`, `measures`, `monitors`, `motivates`, `negotiates`, `observes`, `operates`, `organizes`, `outlines`, `oversees`, `participates`, `performs`, `plans`, `prepares`, `processes`, `programs`, `promotes`, `proposes`, `provides`, `purchases`, `receives`, `recommends`, `records`, `repairs`, `reports`, `represents`, `requisitions`, `researches`, `resolves`, `responsible`, `reviews`, `revises`, `schedules`, `screens`, `selects`, `services`, `sorts`, `suggests`, `supervises`, `tests`, `trains`, `transcribes`, `transfers`, `troubleshoots`, `verifies`
- **Configured in:** `action_verbs.yaml` → `action_verbs.approved`
- **Where the default came from:** SFU rulebook (Glossary)
- **Why it matters:** The glossary is a CLOSED list: a duty beginning with any verb outside it is flagged (SFU-STRUCT-ACTION-VERB, `low`, non-blocking). Ordinary, perfectly good verbs are absent — "supports", "delivers", "liaises", "administrates", "writes", "edits", "responds", "escalates" — so well-written duties are penalised for word choice. It also contains two adjectives (HR-043, HR-044) and both "assemble" and "assembles". The whole list is pinned here so it cannot be edited without SFU HR being told. Same provenance caveat as HR-043: the glossary is in the JD Toolkit, which is not shipped in this repo.
- **If it changes:** Adding verbs reduces a very common false positive; removing any tightens it. Score and checklist only today — but if SFU-STRUCT-ACTION-VERB were ever gated (HR-004) or promoted to the severity floor (HR-057), this list would become the approval bar.

#### HR-056 — Must every JD's Relationships section open with SFU's standard sentence, verbatim?

- **We ship:** `establishes and maintains relationships and alliances`
- **Configured in:** `markers.yaml` → `markers.relationships_header`
- **Where the default came from:** SFU rulebook (Part 2F)
- **Why it matters:** A literal case-folded substring test. SFU's boilerplate, transcribed — but a JD that paraphrases it is flagged (SFU-GATE-REL-HEADER, `low`, non-blocking). The composer restores the boilerplate anyway, which is why this is a nudge rather than a bar.
- **If it changes:** Score and checklist only.

#### HR-063 — What are the functional title types — SFU's Job-Title Application Table?

- **We ship:** `assistant`, `coordinator`, `analyst`, `officer`, `specialist`, `consultant`, `manager`, `associate_director`, `director`, `executive`
- **Configured in:** `titles.yaml` → `titles.functions`
- **Where the default came from:** SFU rulebook (Part 3.3)
- **Why it matters:** The SECOND, independent title dimension: what the title *word* means, as against how senior it is. "Data Analyst" has no rung on the seniority ladder (family `unmapped`) but a perfectly clear function (`analyst`). Unlike the ladder of HR-059 this table IS SFU's — it is transcribed from the Total Comp Learning Series' Application Table — so the question for HR is not "is this right" but "is this still current, and is it complete". A missing row means every title using that word falls to `unmapped`.
- **If it changes:** Config plus a one-line type change: `jd_core.models.bank.TitleFunction` is the type mirror of this list and the loader REFUSES TO START if the two disagree, so a row cannot be added to the YAML alone. Advisory — no gate reads it.

#### HR-065 — Which words in a title map it onto each functional type?

- **We ship:** `executive` → ['executive']; `associate_director` → ['associate director']; `director` → ['director']; `manager` → ['manager']; `consultant` → ['consultant']; `specialist` → ['specialist']; `officer` → ['officer']; `analyst` → ['analyst']; `coordinator` → ['coordinator']; `assistant` → ['assistant']
- **Configured in:** `titles.yaml` → `titles.function_keywords`
- **Where the default came from:** SFU rulebook (Part 3.3)
- **Why it matters:** Each function is matched by its own name, so the keywords are a direct transcription of the Application Table's title words — that part is SFU's. What is NOT SFU's is that they are matched as bare substrings anywhere in the title: "Chief Information Officer" therefore reads as function `officer`, and any title containing "Assistant" reads as `assistant` however senior it is. HR should confirm the words; the matching strategy is ours to answer for.
- **If it changes:** Config only; advisory. Every keyword must belong to a function that exists in HR-063 or the rulebook fails to load.

## Trivial — on the decision surface, deliberately not a decision

The build requires every parameter on the decision surface to be either a decision above or an exemption here **with a reason**. Nothing can be silently skipped. `Covered by` means the parameter *is* a decision — just one that is pinned by the entry named, so changing it still breaks the build.

| Configured in | Why it is not a decision | Covered by |
|---|---|---|
| `gates.SFU-APPROVE-DUTY-ALLOCATION.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-DUTY-ALLOCATION.rule_ids` | Which overridable gate a blocking rule is filed under determines only the reason copy shown to the reviewer. | HR-004 |
| `gates.SFU-APPROVE-EDI-FOOTER.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-EDI-FOOTER.rule_ids` | Which overridable gate a blocking rule is filed under determines only the reason copy shown to the reviewer. | HR-004 |
| `gates.SFU-APPROVE-GRADE-FLOOR.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-KSA-ORDER.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-KSA-ORDER.rule_ids` | Which overridable gate a blocking rule is filed under determines only the reason copy shown to the reviewer. | HR-004 |
| `gates.SFU-APPROVE-MANDATORY-SECTIONS.overridable` | A member of the un-waivable gate set, which is pinned as a whole. | HR-005 |
| `gates.SFU-APPROVE-NO-PLACEHOLDERS.overridable` | A member of the un-waivable gate set, which is pinned as a whole. | HR-005 |
| `gates.SFU-APPROVE-QUAL-EQUIVALENT.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-QUAL-EQUIVALENT.rule_ids` | Which overridable gate a blocking rule is filed under determines only the reason copy shown to the reviewer. | HR-004 |
| `gates.SFU-APPROVE-QUAL-MINIMUM.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-QUAL-MINIMUM.rule_ids` | Which overridable gate a blocking rule is filed under determines only the reason copy shown to the reviewer. | HR-004 |
| `gates.SFU-APPROVE-SCORE-FLOOR.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-SENIOR-TITLE.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-SENIOR-TITLE.rule_ids` | Which overridable gate a blocking rule is filed under determines only the reason copy shown to the reviewer. | HR-004 |
| `gates.SFU-APPROVE-SEVERITY-FLOOR.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-SUMMARY-CONDITIONS.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-SUMMARY-CONDITIONS.rule_ids` | Which overridable gate a blocking rule is filed under determines only the reason copy shown to the reviewer. | HR-004 |
| `gates.SFU-APPROVE-SUMMARY-INCUMBENT.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-SUMMARY-INCUMBENT.rule_ids` | Which overridable gate a blocking rule is filed under determines only the reason copy shown to the reviewer. | HR-004 |
| `gates.SFU-APPROVE-SUMMARY-LENGTH.overridable` | Overridable; flipping it would move the un-waivable set pinned by HR-005. | HR-005 |
| `gates.SFU-APPROVE-SUMMARY-LENGTH.rule_ids` | Which overridable gate a blocking rule is filed under determines only the reason copy shown to the reviewer. | HR-004 |
| `gates.grade_order` | The ranking of the grade literals from worst to best. F < D < C < B < A is not a policy choice; where the floor sits on it is HR-002. | — |
| `gates.severity_order` | The ranking of the severity literals from least to most severe. Any other order would be incoherent (it is not a policy choice that `high` outranks `low`); the choice of WHERE the floor sits on this ranking is HR-003. | — |
| `hay_signals.evidence_cap` | How many evidence phrases one Hay factor's signal may CITE. Presentation only: the score is computed from every hit and the level is decided before the evidence list is truncated, so this cannot move a signal from low to high — it only shortens the "why". It is bounded by what `HayFactorSignal.evidence` accepts (the rulebook refuses to load if it exceeds that), and the substantive calls — which phrases count and what they are worth — are HR-066 … HR-081. | — |
| `rule_catalog.SFU-AUTH-ABILITIES-OBSERVABLE.default_severity` | A `low` drafting nudge (an ability should read "Ability to <observable behaviour>"). The prefixes are HR-054; severity-floor promotion is pinned by HR-057. | HR-054 |
| `rule_catalog.SFU-AUTH-SUMMARY-CONDITIONS.default_severity` | `medium`, and blocking by name (HR-004). The substantive question is the working-conditions word list (HR-046); severity-floor promotion is pinned by HR-057. | HR-046 |
| `rule_catalog.SFU-AUTH-SUMMARY-INCUMBENT.default_severity` | `low`, but blocking by name (HR-004). The regex it fires on is HR-048; severity-floor promotion is pinned by HR-057. | HR-048 |
| `rule_catalog.SFU-AUTH-TITLE-EXEC-DIR.default_severity` | DEAD CONFIG — never read. A restricted-title finding always takes its severity from titles.yaml (HR-030). Flagged for removal. | — |
| `rule_catalog.SFU-AUTH-TITLE-HR.default_severity` | DEAD CONFIG — never read. Severity comes from titles.yaml (HR-033). Flagged for removal. | — |
| `rule_catalog.SFU-AUTH-TITLE-REGISTRAR.default_severity` | DEAD CONFIG — never read. Severity comes from titles.yaml (HR-032). Flagged for removal. | — |
| `rule_catalog.SFU-COMP-ABOUT.default_severity` | Missing "About SFU" boilerplate — `low`, and boilerplate the composer restores. Score cost HR-008..HR-011; blocking by name HR-004; by severity floor HR-057. (What that boilerplate then does to the coded-term lexicon IS a decision — HR-058.) | HR-058 |
| `rule_catalog.SFU-COMP-DUTIES.default_severity` | Definitional: a document with no duties is not a job description. `high` tier membership is pinned by HR-057; the un-waivable gate by HR-006. | HR-057 |
| `rule_catalog.SFU-COMP-EDI.default_severity` | Missing Employment Equity statement — `low`, and it DOES block, via the EDI-footer gate (pinned by HR-004). Its sibling, the territorial acknowledgement, is registered as HR-039 because its WORDING is an open publish blocker. Severity-floor promotion pinned by HR-057. | HR-004 |
| `rule_catalog.SFU-COMP-QUALS.default_severity` | Definitional: a document with no qualifications is not a job description. `high` tier membership is pinned by HR-057; the un-waivable gate by HR-006. | HR-057 |
| `rule_catalog.SFU-COMP-RELATIONSHIPS.default_severity` | Its score cost is pinned by HR-008..HR-011, its blocking-by-name by HR-004, and its blocking-by-severity-floor by HR-057. A `low` completeness nudge. | HR-057 |
| `rule_catalog.SFU-COMP-SUMMARY.default_severity` | Definitional: a document with no Position Summary is not a job description. `high` is what makes the severity floor (HR-003) and the un-waivable mandatory-sections gate (HR-006) agree about it. Membership of the `high` tier — the tier that trips the floor — is pinned by HR-057. | HR-057 |
| `rule_catalog.SFU-GATE-DUTY-PCT.default_severity` | `medium`, and blocking by name (HR-004) — an explicit SFU never-approve condition. The substantive questions are the rounding window (HR-023/HR-024), the minimum count (HR-025) and the pattern (HR-045). | HR-004 |
| `rule_catalog.SFU-GATE-KSA-ORDER.default_severity` | `low`, but blocking by name (HR-004). The ordering it enforces is HR-052; severity-floor promotion is pinned by HR-057. | HR-052 |
| `rule_catalog.SFU-GATE-REL-HEADER.default_severity` | A `low` nudge for the standardized Relationships header — boilerplate the composer restores. The header text is HR-056; severity-floor promotion is pinned by HR-057. | HR-056 |
| `rule_catalog.SFU-GATE-SENIOR-TITLE.default_severity` | `low`, but blocking by name (HR-004). The pattern it fires on is HR-049; severity-floor promotion is pinned by HR-057. | HR-049 |
| `rule_catalog.SFU-LANG-CODED.default_severity` | DEAD CONFIG — never read. A coded-term finding always takes its severity from the coded_terms.yaml tier the term sits in (HR-028 / HR-029), so this default cannot affect any outcome. Flagged for removal. | — |
| `rule_catalog.SFU-QUAL-BANNED-PHRASE.default_severity` | `medium`, and blocking by name (HR-004). The substantive question is the whole-document match scope (HR-041); severity-floor promotion is pinned by HR-057. | HR-041 |
| `rule_catalog.SFU-QUAL-DEGREE-DISCIPLINE.default_severity` | A `low` drafting nudge (a degree requirement should name a discipline and allow related fields). The patterns are HR-050 / HR-051; severity-floor promotion is pinned by HR-057. | HR-050 |
| `rule_catalog.SFU-QUAL-EQUIVALENT.default_severity` | `low`, but blocking by name (HR-004). The substantive question is the literal-phrase match (HR-042); severity-floor promotion is pinned by HR-057. | HR-042 |
| `rule_catalog.SFU-QUAL-MODIFIER-VOCAB.default_severity` | A `low` drafting nudge (use the Toolkit's modifier vocabulary). The vocabularies are HR-040 and HR-053; severity-floor promotion is pinned by HR-057. | HR-040 |
| `rule_catalog.SFU-QUAL-SKILL-MODIFIER.default_severity` | A `low` drafting nudge (skills should carry a proficiency modifier). The vocabulary itself is HR-053; severity-floor promotion is pinned by HR-057. | HR-053 |
| `rule_catalog.SFU-STRUCT-ACTION-VERB.default_severity` | A `low` drafting nudge (duties should be action-verb led). THIS is the rule the reviewer used to prove the severity-floor hole: promoting it to `high` used to make a non-approved verb block a JD with no register change. It now moves HR-057 and breaks the build. The glossary itself is HR-055 / HR-043 / HR-044. | HR-057 |
| `rule_catalog.SFU-STRUCT-HOW-WHY.default_severity` | A `low` drafting nudge (duties should carry "how and why" detail). Cost pinned by HR-008..HR-011; blocking by name HR-004; by severity floor HR-057. | HR-057 |
| `rule_catalog.SFU-STRUCT-PLACEHOLDER.default_severity` | `medium`, and un-waivably blocking (HR-007). The substantive question is the marker list (HR-047); severity-floor promotion is pinned by HR-057. | HR-047 |
| `rule_catalog.SFU-STRUCT-SUMMARY-TOO-LONG.default_severity` | `low`, but blocking by name (HR-004, HR-020). All three effects of the severity are pinned: cost HR-008..HR-011, name HR-004, floor HR-057. | HR-004 |
| `scoring.fallback_grade` | The grade awarded below the lowest band. Definitional given the bands (HR-013..HR-016): F is what sits under D. The loader already refuses a fallback_grade that duplicates a band. | — |
| `thresholds.evidence_context_window` | Characters of surrounding text quoted either side of a match in an evidence snippet. Pure presentation: it changes how much context a reviewer reads, and no decision whatsoever. | — |
| `titles.human_resources.reserved_for_employee_group` | Null by design: the Human Resources restriction is not checkable from the JD alone. The decision is HR-033. | HR-033 |
| `titles.registrar.reserved_for_employee_group` | Null by design: it records that the Registrar restriction is NOT checkable from the JD alone (it needs organisational context). The decision — whether to say anything at all, and at what severity — is HR-032. | HR-032 |

