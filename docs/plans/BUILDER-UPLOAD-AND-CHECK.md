# Track G — Upload a JD into the Builder

**Design only. Nothing here is built.** Written 2026-08-29 against the live code, so the
reuse/new split below is fact rather than recollection — every "already exists" was read
in the tree, and every "genuinely new" was checked for.

---

## What it is

> A manager has a job description in a Word file or a PDF. Today the Builder can only
> start from an archive JD or from a blank form, so that manager cannot ask the one
> question they actually have: **"is this any good?"**

Upload the file → it is parsed → the compliance panel scores it → and, if the author
wants, it seeds a draft. The Builder stops being an authoring form for people who already
work inside the Bank and becomes a **JD assistant** anyone with a document can use.

⚠ **Honest placement, per this plan's own rule.** *Does this change the number of
PUBLISHED JDs?* **Not directly.** It changes **who can use the Bank at all** — which is a
different kind of value, and it should not jump the HR asks (B3/B4) that do move the
count. It is a backlog item, sequenced below.

---

## Most of this already exists

The upload is a **new front door onto the clone chain that already runs in production**.
`GET /jd-bank/ui/compose/clone/{source_document_id}` does every step below except the
first, and has since Phase 5.4:

```
  upload  →  extract_text  →  parse_jd  →  jd_to_answers  →  _render_clone  →  assess_draft  →  submit
   NEW        REUSE (docx)     REUSE         REUSE            REUSE            REUSE          REUSE
              NEW (pdf)
```

| verified as reusable, unchanged | where |
|---|---|
| `.docx` / `.doc` / `.rtf` / `.txt` extraction, with a size cap and NUL stripping | `jd_bank.ingest.extract.extract_text` |
| the v6 segmenter, incl. the JDFN/WJQ router — deterministic and **never raises** | `jd_core.parser.parse_jd` |
| parsed JD → Builder answers, for both instruments | `jd_bank.composer.jd_to_answers` |
| land the author on a scored, pre-filled Builder; form derived from the SOURCE | `compose_ui._render_clone` |
| the compliance panel, gates, inclusive-language meter | `assess_draft` |
| the near-duplicate authoring guard ("SFU already has these roles") | `composer.duplicates.find_related_roles` |
| persisting a composed draft with no archive lineage (`source_document_ids=[]`) | `composer/persist.py` |

**That last row matters:** the Bank already mints roles from nothing but an author's
input — one of the four currently PUBLISHED JDs is such a role. So "a draft with no
archive document behind it" is an existing, exercised state, not a new concept to invent.

---

## What is genuinely new

### 1. 🔴 Multipart intake — and the constraint nobody will expect

**`python-multipart` is deliberately not installed.** `src/api/routes/_forms.py` is the
single reader of every POST body in this app and uses `urllib.parse.parse_qsl` on the raw
bytes, precisely to avoid that dependency: on the installed Starlette, `Request.form()`
asserts `python-multipart` is importable *regardless of content type*.

A file upload is multipart by nature, so this is a real decision, not a detail.

⚠ **And there is a trap underneath it.** The CSRF check is a **dependency that reads the
request body before the handler does**, relying on Starlette caching `Request._body` so
the handler's read is a dict lookup rather than a second drain. That design is sound for a
2 KB form and **buffers the entire file in memory for an upload**. Whatever is chosen —
adding the dependency, a separate streaming endpoint, or a two-step
upload-then-reference — the CSRF/body interaction has to be settled deliberately.
It is the kind of thing that works fine on a 40 KB test file and falls over on a real one.

### 2. PDF extraction

`DocumentFormat` today is `docx | doc | rtf | txt | other`, and **PDF routes to `other`,
which raises `UnsupportedFormatError`**. A backend is new code and a new dependency, and
it must be vendored into the image — the deploy target has **no internet** (Directive #1).

Two failure modes to decide before promising anything:

- **A scanned PDF has no text layer at all.** Extraction returns empty, `parse_jd` returns
  an `Untitled Position` shell with near-zero confidence, and the user is shown a
  confident-looking empty result. **Refuse it explicitly, or add OCR** — OCR is a heavy
  dependency and a much larger change than it looks.
- **Layout.** The archive is `.doc`/`.docx`; PDF column and table ordering is a genuinely
  hard extraction problem, and this parser is tuned to SFU's templates.

### 3. Provenance for a document that is not from the archive

Non-negotiable #6: *every canonical JD traces to sources.* An uploaded file has no
`source_documents` row and no archive lineage. Either it gains one with an explicit
non-archive origin, or the draft records the upload some other way — but **it must not
silently borrow the archive's provenance vocabulary**, and it must never inflate the
archive counts on the funnel.

### 4. Retention

The first user-supplied file this system has ever accepted. Whether the bytes are kept at
all, and for how long, is a decision — not a default that emerges from whichever
implementation is easiest.

---

## 🔴 The risk that matters most: a confident wrong parse

This project's recurring defect is **a surface that presents an assumption as a
measurement**, and an upload UI is the most exposed place yet for it.

Everything we already know says so. `Untitled Position` is a *placeholder*, not an empty
string — a null check reports 100% title coverage over 2,050 documents that have no title
(FINDINGS §2b). Parse quality across the archive varies enormously, and that is on
documents the parser was **tuned for**. An arbitrary uploaded PDF is strictly harder.

**So the panel must report three things, never two:** what it read, what it could not
find, and what it could not evaluate. A parse that silently yields an empty shell and then
scores it is worse than a refusal, because the score looks like an answer. The same rule
that fixed the IT collection applies here: *matched / not-matched / could-not-evaluate.*

**Required before U2 ships:** run the parser over a sample of real non-archive JDs and
measure section recall. We have never parsed a document this pipeline was not built for,
and no one should promise the feature works on PDFs until that number exists.

---

## Decisions to register (all `open`, none ours to settle)

Per CLAUDE.md, each of these is a rulebook value registered in the same PR that builds it:

| # | question |
|---|---|
| G-a | Which formats may be uploaded? (`docx`/`doc`/`rtf`/`txt` reuse the existing backends; PDF is new) |
| G-b | Maximum upload size? **Not** `MAX_DOCUMENT_BYTES` (50 MiB) — that governs a trusted archive file read from disk, not an untrusted body buffered in memory |
| G-c | Is the uploaded file persisted at all, and for how long? |
| G-d | May a draft created from an upload be **approved and published**, given it has no archive lineage? |
| G-e | A scanned PDF with no text layer: refuse, or OCR? |
| G-f | Do incumbent names in an uploaded file get the same normalization as at ingest? (a JD is not a resume — but this is user-supplied content, which is new) |

---

## Sequencing — three slices, smallest risk first

| # | slice | why this order |
|---|---|---|
| **U1** | **`.docx`/`.doc`/`.rtf`/`.txt`, in memory, no persistence.** Upload → parse → compliance panel. Nothing is stored; the result is a scored Builder the author can edit. | **Zero new extraction code** — it reuses the archive's own backends. Delivers the whole user story for the format most JDs are actually in, and settles the multipart/CSRF question once. |
| **U2** | **PDF, text-layer only**, scanned files refused with a clear message. | New dependency and new failure modes. **Gated on the recall measurement above.** |
| **U3** | **Persistence + draft creation** with explicit non-archive provenance. | Only worth building once U1 shows people use it, and it is where the provenance and retention decisions bite. |

**U1 is the honest MVP**, and it is much smaller than the feature sounds: the chain
already exists and the archive's own extractors already handle the formats.

---

## What this deliberately does not do

- **No LLM parsing.** The segmenter is deterministic and never raises. Adding a model here
  would put a generative step between a user's document and a compliance verdict, and the
  validator — not a model — is the oracle (non-negotiable #3).
- **No bulk upload.** One document, one author, one answer. A bulk path is an ingest
  pipeline wearing a Builder costume, and `make ingest` already exists.
- **No auto-publish.** Non-negotiable #1 is unchanged: an uploaded JD becomes a DRAFT at
  most, and a human reviewer approves it or nothing happens.

---

## Prerequisite

Directive #1 applies: whatever ships must be **testable, deployable through
`build.ps1`/`launch.ps1`/`teardown.ps1` and the offline bundle, and discoverable in the
UI**. An upload button nothing links to has not been delivered — and a PDF dependency that
cannot be installed on a box with no internet has not been delivered either.
