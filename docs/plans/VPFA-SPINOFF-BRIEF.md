# A job description bank for the VPFA portfolio: briefing

**For:** the VPFA Senior Policy Advisor and the Chief Risk & Safety Officer. **Date:**
prepared 2026-11-24, revised 2026-11-25 (the VPFA version is a full copy, not a smaller
application).
**What we are asking for:** agreement on scope, named reviewers and unit contacts, and a
view on privacy review. Details are in §5.

---

## 1. What exists today

SFU HR holds roughly 14,500 job descriptions written over two decades, many of them copies
or near-copies of each other. Over the past five months we have built a working prototype
that:

- reads every one of them and groups the copies into about 2,500 distinct roles;
- writes one clean, standards-checked **draft** description per role;
- lets a manager **write a new description** that meets SFU's JD Toolkit as they type,
  starting from an existing role or a blank page;
- fills in SFU's **Compensation Requisition Form** from a role;
- keeps every draft a draft until a named HR reviewer approves it.

HR colleagues are testing it now, signed in with their SFU credentials.

## 2. The proposal

A **focused version for the VPFA portfolio**: the VPFA office, IT Services, Safety & Risk
Services, Facilities Services and Campus Services (and Finance, which sits under VPFA in
SFU's structure). It would have four parts:

| part | what it does for a VPFA manager |
|---|---|
| **The Bank** | read the current description of any VPFA role, see the original files it came from and their position numbers |
| **The Builder** | write or update a description with live feedback against SFU's standards, export it to HR's Word template |
| **The funnel** | see, honestly, how much of the archive could be turned into roles, and what could not, for VPFA units |
| **The Compensation Requisition Form** | download the form pre-filled from a role or a new draft |

It would be a **full copy of the working prototype**, set up for VPFA: the same engine
that reads the archive, groups the copies and drafts each role comes across unchanged, and
only the internal statistics dashboards are left out. It starts with today's complete
bank, opens on the VPFA units, and can still show all of SFU when a manager wants to
compare. Estimated **3–5 weeks** to a pilot, then a **2-week pilot** with a few named
users per unit.

## 3. What it would show today

Counted on 2026-11-24:
- about **130 roles** sit in the VPFA units by the department written on their files;
- **about 750 of all 2,500 roles have no department written on them at all**, so no one
  can say from the files alone whether they belong to VPFA.

The application will always show three numbers for each unit: in the unit, elsewhere, and
**not recorded**. It will not guess. Which departments belong to Campus Services has not yet
been decided, so that unit currently shows none.

## 4. How the risks are handled

| concern | how it is handled |
|---|---|
| **Who can publish a job description?** | Nobody, automatically. Every draft stays a draft until a named VPFA reviewer approves it. Approval re-checks SFU's standards at that moment, and the action is recorded permanently |
| **Where does the content go?** | Nowhere outside SFU-controlled systems. The AI models run on SFU hardware; no cloud AI service and no outside vendor sees any job description. If that ever had to change, it would be a new privacy decision, not a quiet change |
| **Is personal information involved?** | Job descriptions describe roles, not people. Where an old description names the person in the job, that name is removed as a quality step |
| **Who can get in?** | SFU sign-in (CAS) only, with three roles: author, reviewer, administrator. The new version will **refuse to start** without sign-in switched on, a lesson from the prototype, where a configuration slip once left it open on the local network for eleven days |
| **Does the AI make things up?** | It is not allowed to. In the prototype, testing caught the model inventing duties; since then, the rule is that it may reword, never invent, and every result is re-checked by fixed rules. The VPFA version carries those same checks. Every AI-drafted description is still a draft until a named reviewer approves it |
| **What if the AI server is slow or down?** | Reading, the funnel, the form and approvals do not need it. Search falls back to titles. We have learned to check the AI server's settings before relying on it |
| **Who decides the standards?** | HR's standards apply as they stand today. For this application **VPFA acts as HR's proxy**: every threshold and rule is listed in a decision register, VPFA can rule on each one, and each ruling is recorded under the person's name. Anything not yet ruled on is marked open, not quietly decided by us, and anywhere VPFA departs from HR is shown as such |
| **Who approves?** | Named VPFA reviewers: Denise (VPFA office), Galib (Safety & Risk Services, or a designate), and two more to be named. Each approval is recorded under the reviewer's SFU sign-in |
| **What if the person who built it leaves?** | The project is documented for hand-over: a full engineering plan, a history of why each rule exists, and scripts that install it without the original developer |

## 5. What we need

Settled on 2026-11-24:
- **Scope:** every unit under VPFA, Finance included.
- **Campus Services:** includes Residence and Housing, and the Bookstore.
- **Reviewers:** Denise (VPFA office) and Galib (Safety & Risk Services, or a designate),
  plus two more to be named.
- **Standards:** VPFA acts for HR on the standards the application applies.

Still open:
1. **Two more reviewers**, covering IT Services, Facilities, Finance and Campus Services.
2. **Membership:** confirm a few neighbouring departments for Campus Services: Ancillary
   Services; Meeting, Event and Conference Services; Residence Life.
3. **Standards:** confirm that HR is content for VPFA to act as its proxy for this
   application. Any standard VPFA changes would differ from HR's, and the application will
   show where it does.
4. **Privacy:** whether the privacy office wants a privacy impact assessment before a
   pilot.
5. **Who keeps it up to date:** once VPFA reviewers start approving descriptions, the VPFA
   version should maintain its own bank and take improvements from the main project as
   software updates, not as a fresh copy of its data. A fresh copy would overwrite VPFA's
   own approvals.
6. **Hosting:** agreement for IT Services to provide a server, a web address and SFU
   sign-in registration.
7. **Pilot users:** one or two people per unit for a two-week pilot.
