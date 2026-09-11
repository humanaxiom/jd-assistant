# VPFA / Facilities rollup — the curation worksheet

**Generated 2026-09-09 against the live Bank.** This is the input Track E (MVP-2) is
blocked on, turned into a tick-box exercise. It is **not** a proposal: the plan forbids
seeding the tree by inference, and every row below needs a human to assign it.

## How to use this

Put a unit in the **assign** column of each row that belongs to one:

* `VPFA` — Finance & Administration (the portfolio)
* `FACILITIES` — Facilities Services (rolls up INTO VPFA)
* `FINANCE` · `ITS` · `SAFETY-RISK` · `CAMPUS-SERVICES` — the named sub-units
* leave blank for anything outside these two portfolios

Then the rollup is configuration, and the page is a small build on the existing scope seam.

## What the archive says before anyone assigns anything

| | |
|---|---|
| DRAFT roles | 2,496 |
| carrying a `department` | 1,819 (72.9%) |
| **carrying none** | 🔴 **677 (27.1%)** — no rollup can see these, and the page must say so |
| distinct department strings | 742 (113 plausible for these two portfolios, below) |

⚠ **`Campus Services` was named as a VPFA sub-unit and does not exist as a department
string anywhere in the archive.** The closest candidates are Ancillary Services (6),
Bookstore (12+3+1+1), Residence & Housing (16+9+6+1), Meeting/Event/Conference Services
(7 spellings) and Parking Services (1) — but which of those constitute Campus Services is
an org question, not a parse question.

⚠ **`Science – IT Services` (1)** is the shape of the false positive to watch for: a
faculty's own IT, or ITS? Matching `IT Services` as a phrase would claim it either way.

🔴 **A KNOWN PARSE DEFECT IS VISIBLE IN THIS LIST.** 33 parsed rows across 16 distinct
strings have the department field swallow the NEXT form label and its value, e.g.
`Windows Applications, Applications Services Position Reports To (Title): Information
Technology Professional IV`. It reaches 6 drafts. Assign those rows to the unit the
*leading* text names; the strings themselves need a parser fix (Track P shape).

## The candidates

| assign | department (as written) | roles |
|---|---|---:|
|  | `Facilities Services` | 24 |
|  | `Finance` | 20 |
|  | `Residence & Housing` | 16 |
|  | `Bookstore` | 12 |
|  | `Campus Security` | 11 |
|  | `Information Technology Services` | 11 |
|  | `IT Services` | 10 |
|  | `Information Technology` | 10 |
|  | `Residence and Housing` | 9 |
|  | `Financial Services` | 8 |
|  | `Procurement Services` | 7 |
|  | `Ancillary Services` | 6 |
|  | `Environmental Health & Research Safety` | 6 |
|  | `Residence Life` | 6 |
|  | `Financial Aid & Awards` | 5 |
|  | `Safety & Risk Services` | 5 |
|  | `Budget Office` | 4 |
|  | `Environmental Health and Safety` | 4 |
|  | `Facilities Management` | 4 |
|  | `Bookstore/Spirit Shop` | 3 |
|  | `Campus Safety & Security Services` | 3 |
|  | `Financial Aid and Awards` | 3 |
|  | `IT Services, Application Services` | 3 |
|  | `Safety and Risk Services` | 3 |
|  | `Student Accounts` | 3 |
|  | `Campus Planning & Development` | 2 |
|  | `Campus Public Safety` | 2 |
|  | `Enterprise Risk and Resilience` | 2 |
|  | `Environmental Health & Safety` | 2 |
|  | `Financial Reporting` | 2 |
|  | `IT Services, Client Services` | 2 |
|  | `IT Services, Strategic Services` | 2 |
|  | `Meeting, Event &` | 2 |
|  | `Office of the Vice-President, Finance and Administration` | 2 |
|  | `Research Accounting` | 2 |
|  | `(Office of the Registrar) Financial Assistant` | 1 |
|  | `/ Meetings, Events & Conferences Services, SFU Vancouver (MECS)` | 1 |
|  | `AVP Finance Administration` | 1 |
|  | `AVP Students and International, Residence Life` | 1 |
|  | `AVP, Financial Planning Office` | 1 |
|  | `Academic Planning & Budgeting` | 1 |
|  | `Accounting Services` | 1 |
|  | `Ancillary Services, Meetings, Event, Conferences Services` | 1 |
|  | `Application Services, IT Services` | 1 |
|  | `Application Services, Information Technology Services` | 1 |
|  | `Bookstore and Spirit Shop` | 1 |
|  | `Building & Grounds` | 1 |
|  | `Business Solutions, IT Services` | 1 |
|  | `Campus Planning and Development` | 1 |
|  | `Career Management Centre SFU Beedie School of Business, Burnaby Campus` | 1 |
|  | `Client Services, Facilities Services` | 1 |
|  | `Client Services, IT Desktop Support Position Reports To (Title): Information Technology Professional III` | 1 |
|  | `Client Services, IT Services` | 1 |
|  | `Conference & Guest Accommodations` | 1 |
|  | `Enterprise Risk & Resilience` | 1 |
|  | `Enterprise Risk and Resilience, Safety & Risk Services` | 1 |
|  | `Enterprise Systems – Application Services Position Reports To (Title): Information Technology Professional IV` | 1 |
|  | `Events and Conference Services` | 1 |
|  | `FACILITIES SERVICES` | 1 |
|  | `Facilities` | 1 |
|  | `Facilities Capital Projects` | 1 |
|  | `Facilities Customer Services` | 1 |
|  | `Facilities Management – SFU Surrey` | 1 |
|  | `Facilities Operations` | 1 |
|  | `Facilities Services Surrey` | 1 |
|  | `Facilities Services – Major Projects Division` | 1 |
|  | `Facilities Services, Vancouver Campus` | 1 |
|  | `Facilities Strategic Support` | 1 |
|  | `Facilities and Capital Planning` | 1 |
|  | `Finance - Payroll` | 1 |
|  | `Finance and Administration` | 1 |
|  | `Financial Services - Purchasing` | 1 |
|  | `Financial Services, Accounts Payable & Expenses,` | 1 |
|  | `Health and Safety` | 1 |
|  | `IT Services (ITS) – SFU Surrey Campus` | 1 |
|  | `IT Services - Infrastructure` | 1 |
|  | `IT Services Infrastructure Services` | 1 |
|  | `IT Services – Application Services` | 1 |
|  | `IT Services – Audio Visual` | 1 |
|  | `IT Services – CaRS Client Services Innovations` | 1 |
|  | `IT Services – High Performance Computing` | 1 |
|  | `IT Services, AV Services` | 1 |
|  | `IT Services, Learning and Community Systems` | 1 |
|  | `Information Technology Services, SFU Vancouver Campus` | 1 |
|  | `Learning and Community Systems, IT Services` | 1 |
|  | `Major Projects, Campus Planning & Development` | 1 |
|  | `Meeting, Event & Conference Services (MECS)` | 1 |
|  | `Meeting, Event & Conference Services, MECS` | 1 |
|  | `Meeting, Event and Conference Services` | 1 |
|  | `Meeting, Event and Conferences Services` | 1 |
|  | `Occupational Health & Trades Safety` | 1 |
|  | `Operations and Maintenance` | 1 |
|  | `Parking Services` | 1 |
|  | `Payroll` | 1 |
|  | `Program & Policy Development, Safety & Risk Services` | 1 |
|  | `Research & Laboratory Safety` | 1 |
|  | `Research Accounting-Financial Services` | 1 |
|  | `Research Computing, IT Services` | 1 |
|  | `Residences` | 1 |
|  | `SFU Bookstore/Spirit Shop` | 1 |
|  | `SFU Surrey Campus` | 1 |
|  | `SFU Surrey Facilities Services` | 1 |
|  | `SFU Vancouver - Meeting, Event and Conference Services` | 1 |
|  | `Science – IT Services` | 1 |
|  | `Student Services – Student Accounts` | 1 |
|  | `Surrey Campus Director’s Office` | 1 |
|  | `Surrey Campus – Community Engagement Centre` | 1 |
|  | `VP Finance &` | 1 |
|  | `Vancouver Campus Office of the Executive Director` | 1 |
|  | `Vice President Finance` | 1 |
|  | `Vice President Finance & Administration` | 1 |
|  | `Vice-President Finance and Administration` | 1 |
|  | `Windows Applications, Applications Services Position Reports To (Title): Information Technology Professional IV` | 1 |

## Everything else

The remaining ~629 department strings did not match any Finance / Facilities / IT /
Safety / Campus pattern and are presumed outside both portfolios — faculties, student
services, advancement, libraries. If a VPFA unit is missing from the list above, it is
because **no role in the Bank names it**, which is itself worth knowing.

## Regenerate

```sql
SELECT trim(content->>'department'), count(*)
FROM canonical_jds WHERE status='DRAFT' AND coalesce(content->>'department','')<>''
  AND (content->>'department') ~* '(facilit|campus|financ|budget|procure|purchas|payroll|treasur|account|it services|information technolog|safety|risk|ancillary|bookstore|residence|housing|parking|maintenance|custodial|grounds|trades|meeting, event|conference|vice.?president finance|vp finance|avp financ)'
GROUP BY 1 ORDER BY 2 DESC, 1;
```
