# Search NLP spike: Library + Builder search (2026-10-19)

This was a read-only spike. Nothing in the repo was edited and nothing was written to Postgres or Neo4j (every script session ran `SET TRANSACTION READ ONLY` and rolled back).
- **Where it ran:** inside `jd-bank-api-1`, which bind-mounts `./core`, so it ran the live code against the live stack (Postgres `harness`, Neo4j, Ollama on `aria-gb10-2`).
- **What it measured:** the service functions were called directly. **HTTP routes were not exercised**, because CAS auth sits in front of the UI routes.
- **Inputs:** `PARSER_VERSION=jd_segmenter_v8`; live embed stamp `jd_rules_sfu_v4+b760ce00210a`. Neo4j holds `(:JDRole)` 2,493 nodes and `(:JDDocument)` 14,407 nodes, each on a single stamp. The Bank holds 2,503 current roles (2,499 DRAFT, 5 PUBLISHED rows) and 14,565 source documents.
- **Scripts and raw JSON:** both are in [`evidence/`](evidence/). The scripts are `spike.py`, `summ.py`, `trgm.py` and `gpudown.py`. The raw JSON files are `baseline.json`, `rerank_120b.json`, `spike_nlp_gpt-oss_20b.json`, `spike_guarded_gpt-oss_{120b,20b}.json` and `summary.txt`.

---

## 1. Code map (file:line, at HEAD 2e3e6dc)

### Library (HR's browse/search)
| Piece | Location | Behaviour |
|---|---|---|
| Route `GET /jd-bank/library` | `core/src/api/routes/library.py:75-99` | params `q, limit, offset, sort, dir`. **No filter params.** |
| `list_roles` | `core/src/jd_bank/library/service.py:254-317` | Takes the current version per cluster (`DISTINCT ON`). The search is `content->>'title' ILIKE '%q%'` (`:291`). **Results are sorted by TITLE A–Z by default, not by relevance** (`_ROLE_SORTS`, `:49-55`). `cluster_ids` is used only by collection pages. |
| Route `GET /jd-bank/archive` | `library.py:144-163` | `q, limit, offset` |
| `list_source_jds` | `service.py:323-368` | `source_documents.filename ILIKE '%q%'` (`:338`). It searches **filenames only**; the parsed title, group and grade are displayed but cannot be searched. |
| Smoke dependency | `core/tests/live/test_smoke_live_bank.py:140` | Exact-filename findability depends on `list_source_jds`. Any change must keep it. |

### Builder ("start from an existing JD")
| Piece | Location | Behaviour |
|---|---|---|
| JSON route `GET /jd-bank/compose/search` | `core/src/api/routes/compose.py:164-182` | `q, limit`. Default form is JDFN. No timeout and no try/except. |
| UI route `GET /jd-bank/ui/compose/search` | `core/src/api/routes/compose_ui.py:876-937` | `q, form`. Runs `asyncio.wait_for(..., embeddings.interactive_timeout_seconds=10.0)` (HR-198). **It catches only `TimeoutError`.** |
| `search_similar_jds` | `core/src/jd_bank/composer/search.py:449-597` | Four passes in order: (1) role-title ILIKE `:330-371`; (2) doc-title ILIKE over `parsed_jds` `:374-401`; (3) role vectors `jd_role_embeddings` `:555-572`; (4) doc vectors `jd_document_embeddings` `:576-597`. The query is embedded at `:551`. Every pass returns early once `limit` hits are reached. |
| Scope filter | `_out_of_scope` `search.py:404-423` | Driven by the form. WJQ form means `cupe` only. JDFN means "not cupe", so blank groups are kept. |
| Stale-vector filter | `_comparable` `search.py:97-131` | Drops vectors whose `embed_stamp` differs from the live stamp. |
| Department label | `_with_departments` / `_role_departments` `:243-326` | The department is **display only**. It is never filtered on. |

### Metadata available to filter on (measured on the live Bank)
- **`canonical_jds.content.employee_group`** over the current role set: apsa 994, **blank 764**, cupe 627, apex 83, poly 19, excluded 16. Blank means an include filter on a group silently drops about 30% of roles.
- **`content.department`** is set on 1,746 of 2,503 roles (70%). It is free text with many spellings: "Beedie School of Business", "Faculty of Business Administration" and "Career Management Centre (CMC), Beedie…" are all the same school. `org_units.yaml` has 6 units (vpfa, facilities_services, finance, its, safety_risk, campus_services), and **no faculty units at all**.
- **`content.relationships.supervisory`** is free text ("Reports to…" or a list of supervised staff). It is not a usable boolean.
- **Grade/level is unreliable everywhere** (memory note `grade-level-data-state`). There is no level facet.
- **`clusters.employee_group` / `level_band`** exist on the cluster row and were not checked further.

### Side findings (measured)
1. **Builder search hard-depends on the GPU today.** I injected an `EmbedClient` pointing at a dead port and then ran the queries:
   - `"Financial Assistant"`: **raised `APIConnectionError` after 4.3 s, discarding the title hits that had already been found.**
   - `"Financial"`: returned 10 `role_title` hits in 0.08 s. The embed is never reached when the title passes fill the page.
   - `"someone who processes invoices"`: raised after 4.0 s.

   The UI route catches only `TimeoutError`, so this becomes an unhandled exception (500). That last step is inferred from the code: the 500 was not exercised over HTTP.
2. **The doc-title pass is the latency bottleneck.** `parsed_jds` holds **116,176 rows: all 8 parser versions × 14,522 docs**, 452 MB. The only indexes are pkey, source_id and (source, parser_version). A single `parsed->>'title' ILIKE` is a **2.7 s seq scan**. That is why Builder p50 is about 2.9 s while the embedding plus both vector queries cost about 0.03 s.
3. **The doc-title pass matches on superseded parses.** 10,369 of 14,522 docs have differing title text across their 8 parses. Docs that match *only* through an old parse:
   - `%Coordinator%`: 47 of 2,011 docs.
   - `%Assistant%`: 75 of 1,691 docs.

   In those cases the result shows a stale title.
4. **`pg_trgm` is available in the postgres image but not installed** (`pg_available_extensions`). Only plpgsql and pgcrypto are installed.
5. **The query embedding uses no `search_query:` prefix**, and the documents use no `search_document:` prefix (nomic-embed-text convention). This is consistent on both sides, so it is not a bug. It is noted as an untested lever; changing it means a full re-embed.

---

## 2. Evaluation set (22 queries, relevance judged from the live Bank)

**How relevance was judged.** Each query has a relevance predicate over (title, department, group) that I wrote after reading the live role table. The roles were exported to `roles.tsv` and grepped per query, so every query has known relevant roles in the Bank. A hit counts as relevant if its role (or, for an unclustered document, the document's own title, department and group) satisfies the predicate.

**Which form each query ran under.** Each Builder query ran under the form a manager would plausibly pick: `wjq` for CUPE-type jobs, `jdfn` otherwise. The judge is a single reviewer (me), and the predicates are somewhat lenient. **Treat hit@k as coarse; P@10 is the more discriminating number.**

| id | kind | query | Builder form | relevant if title matches… |
|---|---|---|---|---|
| E1 | exact | Financial Assistant | wjq | financial / admin-and-financial assistant |
| E2 | exact | Co-op Education Coordinator | jdfn | co-op / co-operative education coordinator, co-op career advisor |
| E3 | exact | Research Grants Facilitator | jdfn | research grants / research facilitator |
| E4 | exact | Laboratory Technician | wjq | lab technician / technologist / research technician |
| P1 | paraphrase | someone who processes invoices and reconciles accounts | wjq | accounts payable/receivable, accounting, financial assistant/clerk |
| P2 | paraphrase | person who helps students plan their courses and meet degree requirements | jdfn | academic / undergraduate / graduate / program advisor |
| P3 | paraphrase | fundraiser who builds relationships with major donors | jdfn | advancement, development officer, major gifts, donor |
| P4 | paraphrase | entry-level library job shelving books and helping patrons at the desk | wjq | library assistant, circulation, loans |
| D1 | duty | maintain Linux servers, apply patches, run backups and manage user accounts | jdfn | systems administrator / consultant / infrastructure |
| D2 | duty | plan and run conferences, convocation ceremonies and university events | jdfn | event / ceremonies / convocation / conference |
| D3 | duty | manage research grant applications and post-award budgets for faculty members | jdfn | research grants / facilitator / research finance |
| D4 | duty | write news stories, manage social media and the department newsletter | jdfn | communications / marketing / writer / content |
| C1 | constraint | supervisory admin role in Faculty of Science, APSA | jdfn | manager / director / administrator **AND** a Science-faculty department **AND** apsa or blank (about 15 such roles exist) |
| C2 | constraint | CUPE administrative assistant | wjq | admin / office / program assistant **AND** cupe |
| C3 | constraint | APSA communications officer | jdfn | communications officer / associate… **AND** apsa or blank |
| C4 | constraint | academic advisor in the Beedie business school | jdfn | advis* **AND** department beedie/business (16 such roles exist) |
| A1 | abbrev | coop coord | jdfn | same as E2 |
| A2 | abbrev | IT sysadmin | jdfn | same as D1 |
| A3 | abbrev | AP clerk | wjq | same as P1 |
| A4 | typo | adminstrative cordinator | jdfn | administrative coordinator |
| A5 | abbrev | HR advisor labour relations | jdfn | labour / employee relations / human resources |
| A6 | abbrev | web dev | jdfn | web* |

---

## 3. Results (all MEASURED on the live stack)

### Aggregates (n = 22)
| Variant | hit@5 | hit@10 | mean P@10 | empty results |
|---|---|---|---|---|
| **Library today** (`list_roles` ILIKE, title-sorted) | **5** | 5 | 0.200 | **17** |
| Library, no-LLM hybrid (raw-q title ILIKE + raw-q role vectors) | 20 | 20 | 0.673 | 0 |
| Library, LLM plan unguarded (120b) | 20 | 20 | 0.777 | 0 |
| Library, LLM plan unguarded + LLM rerank of top-20 (120b) | 21 | 21 | 0.773 | 1 |
| **Library, LLM plan guarded (120b)** | **21** | 21 | **0.827** | 0 |
| Library, LLM plan unguarded (20b) | 18 | 19 | 0.745 | 0 |
| **Library, LLM plan guarded (20b)** | **21** | 21 | **0.836** | 0 |
| **Builder today** (`search_similar_jds`) | **20** | 20 | **0.723** | 0 |
| Builder, LLM plan unguarded (120b) | 18 | 18 | 0.782 | 2 |
| Builder, LLM plan unguarded (20b) | 17 | 17 | 0.741 | 3 |
| **Builder, LLM plan guarded (120b)** | **20** | 20 | **0.859** | 0 |
| **Builder, LLM plan guarded (20b)** | **20** | 20 | **0.868** | 0 |

**What "guarded" means.** It is a deterministic post-processing of the *same* LLM plans: the guarded runs replayed the stored plans and made no new LLM calls. The guard does three things:
- It keeps `employee_group` only if that token literally appears in the user's query.
- It keeps a department keyword only if one of its words appears in the query, and then uses it as a **soft boost**, not a filter.
- It always prepends the raw query as the first title keyword.

### Per query (P@10; H5 means a relevant hit in the top 5)
```
id  query (truncated)                              | LIB today | LIB hybrid | LIB guarded120 | BLD today | BLD guarded120 | BLD guarded20
E1  Financial Assistant                            | H5 .6     | H5 .6      | H5 .6          | H5 1.0    | H5 1.0         | H5 1.0
E2  Co-op Education Coordinator                    | H5 1.0    | H5 1.0     | H5 1.0         | H5 1.0    | H5 1.0         | H5 1.0
E3  Research Grants Facilitator                    | H5 1.0    | H5 1.0     | H5 1.0         | H5 1.0    | H5 1.0         | H5 1.0
E4  Laboratory Technician                          | H5 1.0    | H5 1.0     | H5 1.0         | H5 1.0    | H5 1.0         | H5 1.0
P1  processes invoices and reconciles accounts     | empty     | H5 .6      | H5 .5          | H5 .6     | H5 .8          | H5 .8
P2  helps students plan courses / degree reqs      | empty     | H5 .8      | H5 1.0         | H5 .8     | H5 1.0         | H5 1.0
P3  fundraiser ... major donors                    | empty     | H5 1.0     | H5 1.0         | H5 1.0    | H5 1.0         | H5 .9
P4  entry-level library job shelving books         | empty     | H5 .9      | H5 1.0         | H5 .9     | H5 1.0         | H5 1.0
D1  maintain Linux servers, patches, backups       | empty     | H5 .5      | H5 1.0         | H5 .8     | H5 1.0         | H5 1.0
D2  conferences, convocation, events               | empty     | H5 1.0     | H5 .9          | H5 1.0    | H5 .6          | H5 .9
D3  research grant applications, post-award        | empty     | H5 .9      | H5 .9          | H5 .9     | H5 .9          | H5 .8
D4  news stories, social media, newsletter         | empty     | H5 .8      | H5 1.0         | H5 .8     | H5 1.0         | H5 1.0
C1  supervisory admin, Faculty of Science, APSA    | empty     | -- 0       | -- 0           | -- 0      | -- 0           | -- 0
C2  CUPE administrative assistant                  | empty     | H5 .5      | H5 1.0         | H5 .8     | H5 1.0         | H5 1.0
C3  APSA communications officer                    | empty     | H5 .7      | H5 1.0         | H5 .7     | H5 1.0         | H5 1.0
C4  academic advisor in Beedie business school     | empty     | H5 .1      | H5 .1          | H5 .1     | -- 0           | -- 0
A1  coop coord                                     | empty     | H5 .6      | H5 1.0         | H5 .7     | H5 1.0         | H5 1.0
A2  IT sysadmin                                    | empty     | H5 .6      | H5 1.0         | H5 .5     | H5 1.0         | H5 1.0
A3  AP clerk                                       | empty     | H5 .4      | H5 .5          | H5 .4     | H5 .8          | H5 .8
A4  adminstrative cordinator (typo)                | empty     | -- 0       | H5 1.0         | -- 0      | H5 1.0         | H5 1.0
A5  HR advisor labour relations                    | empty     | H5 .9      | H5 .8          | H5 .9     | H5 .8          | H5 .9
A6  web dev                                        | H5 .8     | H5 .9      | H5 .9          | H5 1.0    | H5 1.0         | H5 1.0
```
The full top-10 lists for every variant are in the JSON files in this folder (key `top`; a leading `*` marks a relevant hit).

### What the numbers say
1. **The Library's problem is not "no LLM"; it is "no semantic pass at all".** Today 17 of 22 queries return an empty page. Reusing the *existing* role-vector search, with no LLM, takes it from 5/22 to 20/22 hit@5.
2. **The Builder is already decent** at 20/22 hit@5. Its vector passes handle paraphrase, duty text and most abbreviations. Its real misses are:
   - typos (A4);
   - faculty constraints (C1, C4);
   - looser precision on abbreviations (A2 .5, A3 .4).
3. **The LLM plan's measurable gain is in precision.** P@10 rises from 0.72 to 0.86 (Builder) and from 0.67 to 0.83 (Library, against the no-LLM hybrid), and the plan fixes the typo (A4) and abbreviations (A1/A2/A3). **It only helps once guarded. Unguarded it is worse than today**, losing hit@5 from 20 to 18 (120b) and 17 (20b).
4. 🔴 **The LLM invents filters, and a prompt instruction does not stop it.** The prompt said "Never invent constraints the query does not state". Even so, **gpt-oss:120b assigned an employee group on 17 of the 20 queries that named none**, and gpt-oss:20b did so on 15 of 20 (for example "IT sysadmin" became `apex`, "processes invoices" became `apsa`). Under the WJQ form, an invented `apsa` produced **empty Builder pages** (P1 and A3).

   Department lists were invented as well. "Faculty of Science" was expanded with "Computer Science", which at SFU is Computing Science and is in Applied Sciences, and 20b added "Psychology", which sits in Arts and Social Sciences (FASS). **Any filter that comes from the LLM must be validated deterministically, and a hard filter must come from what the user typed or from a closed list.**
5. **Faculty constraints (C1) are unsolved by every variant.** C4 is barely solved. This is a **data** gap, not a model gap: no faculty-to-department mapping exists (`org_units.yaml` has no faculties), and department strings are free text with aliases. In the unguarded runs the LLM's own department list used as a hard filter did reach C1 0.4/0.5 and C4 0.3/0.6, but only through an invented list. That is not shippable.
6. **LLM rerank is not worth it.** On the 120b unguarded pool it gave hit@5 20→21 and P@10 0.777→0.773, at a cost of **+6.0 s p50 and +10.5 s p95**. It also *drops* candidates: 6 of 22 queries came back with fewer than 10 results, and C1 came back with 0.
7. **Typos are cheaper to fix with trigrams than with an LLM.** This was emulated in Python, because pg_trgm is not installed and I could not create the extension read-only:
   - "adminstrative cordinator" → Administrative Coordinator, at word_similarity 0.73.
   - "labratory techician" → Laboratory Technician, at 0.62.

   Trigrams do **not** expand abbreviations: "coop coord", "IT sysadmin" and "AP clerk" come out as noise. Abbreviation expansion is the one thing the LLM uniquely adds, and the vectors already half-cover it.

### Latency (MEASURED, wall clock, from inside the api container)
| Step | p50 | p95 | max | notes |
|---|---|---|---|---|
| Builder today (`search_similar_jds`) | 2.91 s | 4.42 s | 4.52 s | Dominated by the 2.7 s `parsed_jds` ILIKE seq scan; 0.06 s when the role-title pass alone fills the page |
| Library hybrid (title ILIKE + embed + role vectors) | 0.03 s | — | — | Embedding the query plus the role-vector query is fast once nomic is warm |
| LLM plan, gpt-oss:120b, effort low, schema-constrained | 4.66 s | 7.42 s | **24.98 s** | The max was the **cold load** on the first call (no model resident: `/api/ps` was empty) |
| LLM plan, gpt-oss:20b | 3.29 s | 6.06 s | 10.01 s | First call 10.0 s cold |
| LLM rerank top-20, 120b | 5.98 s | 10.52 s | 10.98 s | |
| Builder driven by a multi-keyword plan | 6.9 s | 16.1 s | 16.2 s | One doc-title seq scan **per keyword**. This is undeliverable until the doc-title pass is indexed |
| Builder with the inference host down | raises after about 4.0–4.3 s | | | Measured with a dead-port client: the title hits are lost |

Ollama unloads idle models (default keep_alive is 5 min). With sparse search traffic, **most real queries would pay the cold start: about 10 s on 20b and about 25 s on 120b.** This is inference from the defaults; the deployed keep_alive was not checked.

---

## 4. Recommended design

### Stage 1: ship first, no LLM, no GPU dependency for correctness
1. **Library roles search becomes hybrid.**
   - Keep the title ILIKE pass, but rank it exact > prefix > contains (reuse `search._title_rank`) instead of A–Z when `q` is set.
   - Then append the role-vector neighbours (reuse `search._nearest_role_ids` plus `_comparable`).
   - Each row gets a match label: "title contains …" or "similar duties". **Rank only, no % and no cosine shown** (memory note: no threshold exists).
   - Sort headers still work. Sorting by anything other than relevance re-sorts the matched set.
   - Measured result: 5/22 → 20/22 hit@5, and P@10 0.20 → 0.67.
2. **Add filters as explicit UI facets**: employee group (with "not recorded" as its own option, since 764 roles are blank) and department/unit. Hard filters come from the user's clicks, never from inference.
3. **Make Builder search degrade instead of 500.**
   - Wrap only the embed and vector part in its own try/`wait_for`.
   - On any failure (refused, timeout or 5xx), return the title-pass hits with a banner: "Similar-duty matches are unavailable right now; showing title matches only."
   - Library hybrid does the same.
   - This also satisfies "search must not hard-depend on the GPU", which **today it does** (§1, side finding 1).
4. **Fix the doc-title pass** (needs a `core/` migration, so branch + PR):
   - Restrict it to the current parse (`parser_version = PARSER_VERSION`, or latest per document).
   - Add `CREATE EXTENSION pg_trgm` plus a GIN trigram index on the title expression, or a materialized current-title column.
   - This removes the 2.7 s scan, fixes the stale-parse matches, and lets a `similarity()` / `word_similarity` fallback handle typos when ILIKE finds nothing. Rank by that similarity, but never display it.
5. **Archive (source) search** should also search the current parsed title, not just the filename. Keep exact-filename findability, because smoke depends on it.

### Stage 2: optional LLM query understanding (only after Stage 1 lands)
- **Step:** `plan_search_query(q) -> QueryPlan {semantic_query, title_keywords[≤N], employee_group, unit_key, supervisory}` via `ChatClient.chat_json(..., constrain_to_schema=True)`. This is a small flat schema; constrained decoding worked on all 44 calls, with no plan errors.
- **Deterministic guard (non-negotiable, and measured as necessary):**
  - `employee_group` is honoured only if the user typed the token (apsa/cupe/apex/poly).
  - `unit_key` must be an **enum drawn from rulebook units**. The LLM never emits free-text departments.
  - The raw query is always the first title keyword, so exact-title behaviour is never worse than today.
  - Inferred constraints are shown as **suggested chips** the user can click, not applied silently.
- **Run it concurrently, not in series:** render the Stage-1 results immediately. If the plan returns within budget, swap in the merged results via htmx (the UI already uses it). If it misses the budget, keep the Stage-1 page. Show the interpretation ("Searching for: Accounts Payable Clerk · Accounts Payable"), so the user can see and undo what the model did.
- **Model:** gpt-oss:20b gave the same guarded quality as 120b (P@10 0.868 vs 0.859 Builder, 0.836 vs 0.827 Library), is about 1.4 s faster warm, and cold-loads 2.5× faster. That makes it the better candidate. **The model choice is a register decision for HR/ITS, not mine.**
- **No rerank** (measured as neutral and slow, and it drops results).
- **Faculty and unit constraints need data, not a model.** Extend `org_units.yaml`, using the same human-assigned exact-list discipline, with faculties such as Science and Beedie (including the "Faculty of Business Administration" alias) before any "in Faculty of X" query can work. Until then, C1-type queries should say plainly that unit filtering covers only the listed units.

### Knobs: YAML plus `decision_register.yaml` entries (all `open`, tier technical, provenance our_invention)
- Stage 1, `embeddings.yaml` or a new `search.yaml` (if new, follow the six-wiring-point checklist in the memory note):
  - `library_vector_k` (role-vector over-fetch, e.g. 50)
  - `library_semantic_enabled`
  - `title_trgm_min_word_similarity`: a ranking floor for the typo fallback only. Measure it first. It is **not** a displayed score.
  - reuse `interactive_timeout_seconds` (HR-198) for the vector part.
- Stage 2, new `query_understanding` section:
  - `enabled` (default false until HR/ITS rule)
  - `model`, `temperature` (0), `reasoning_effort` (low), `max_tokens`, `max_retries` (0 or 1: interactive)
  - `timeout_seconds` (suggest 6 s; measured warm p95 is 6.1 s on 20b and 7.4 s on 120b)
  - `prompt_id: jd_search_plan_v1`, with the template in `core/src/jd_bank/llm/templates/`, like `jd_compose_summary_v1`
  - `max_title_keywords` (bounds the per-keyword title scans)
- Also update `docs/LLM-CALLS.md`, which would gain a 4th chat use and a 2nd query-embed use, and AI-USAGE.md (HR-facing).

### Honest display
- Rank only. Never show a %, cosine or similarity score. Pin this the same way `test_related_role_never_carries_a_similarity_number` does.
- Every hit carries *why it matched*: title, similar duties, or the interpreted keyword "Accounts Payable" (from "AP").
- The model's interpretation is visible and reversible. Inferred filters are suggestions until clicked. When the vector or LLM path is down, say so on the page and never present title-only results as complete.

### Extending `make smoke` (core/tests/live/test_smoke_live_bank.py)
Smoke today is DB-only plus vector-coverage checks. It does not touch search ranking or any HTTP route. Add the following:
1. **Title findability for roles:** a random sample of current roles, each found by its exact title in the top-10 of the Library hybrid search and of `search_similar_jds` (the Builder runs in the role's own form). This needs no GPU.
2. **Semantic recall floor:** run this spike's 22-query set (predicates as a fixture) through the Library hybrid and the Builder. Assert hit@5 ≥ 18/22 on both, by rank and never by score. It needs the embed host, so it shares the smoke's existing dependency on Neo4j and Ollama vectors.
3. **Degradation:** with a dead-port `EmbedClient` (exactly `gpudown.py`), both searches must **return the title hits and not raise**. This pins the fix for the 500 measured today.
4. **Doc-title pass reads only current parses:** no hit's title may come only from a superseded `parser_version`.
5. **When `query_understanding.enabled` is true:** a live plan call on 3 fixed queries returns a valid `QueryPlan` within `timeout_seconds`, and the guard strips an un-typed `employee_group`. This is not optional, because the measured invention rate is 75–85%.
   - ⚠ Enabling the LLM step therefore ties **shipping** to the GPU being free (Directive #0). That is a reason to keep it optional and off by default.
6. **HTTP coverage:** drive `/jd-bank/library?q=` and `/jd-bank/ui/compose/search?q=` through the ASGI app with the auth dependency overridden, so the routes, not just the services, are smoke-covered.

---

## 5. What was NOT measured / caveats
- HTTP routes and CAS were not exercised. The services were called directly with the live code.
- There was a single relevance judge (me) with lenient regex predicates, and only 22 queries. Hit@5 saturates; read P@10.
- pg_trgm was emulated in Python, not run in Postgres.
- Cold-start under the deployed `keep_alive` was not checked. The latencies are from one run each, while the GPU was otherwise idle (`/api/ps` was empty at the start).
- The "500 when the GPU is down" result is inferred from the route code. The exception itself was measured.
- `search_query:` / `search_document:` nomic prefixes were not tested (testing them requires a re-embed).
- The Stage-2 Builder prototype did not early-cut inside passes (prod does), so its pass mix differs slightly from what a production implementation would produce.

## 6. Raw aggregates (`summ.py` output)
See `summary.txt` in this folder; it is reproduced below.
```
===== /tmp/spike_baseline_gpt-oss_120b.json baseline gpt-oss:120b
builder {'n': 22, 'hit5': 20, 'hit10': 20, 'p10': 0.723, 'empty': 0}
library {'n': 22, 'hit5': 5, 'hit10': 5, 'p10': 0.2, 'empty': 17}
library_rawvec {'n': 22, 'hit5': 20, 'hit10': 20, 'p10': 0.673, 'empty': 0}
builder_s p50 2.91 p95 4.421 max 4.516 min 0.064
per-query: id | builder | library | library_rawvec
E1 Financial Assistant                           H5 p1.0 n10 | H5 p0.6 n6 | H5 p0.6 n10 
E2 Co-op Education Coordinator                   H5 p1.0 n10 | H5 p1.0 n10 | H5 p1.0 n10 
E3 Research Grants Facilitator                   H5 p1.0 n10 | H5 p1.0 n10 | H5 p1.0 n10 
E4 Laboratory Technician                         H5 p1.0 n10 | H5 p1.0 n10 | H5 p1.0 n10 
P1 someone who processes invoices and reconciles H5 p0.6 n10 | -- p0.0 n0 | H5 p0.6 n10 
P2 person who helps students plan their courses  H5 p0.8 n10 | -- p0.0 n0 | H5 p0.8 n10 
P3 fundraiser who builds relationships with majo H5 p1.0 n10 | -- p0.0 n0 | H5 p1.0 n10 
P4 entry-level library job shelving books and he H5 p0.9 n10 | -- p0.0 n0 | H5 p0.9 n10 
D1 maintain Linux servers, apply patches, run ba H5 p0.8 n10 | -- p0.0 n0 | H5 p0.5 n10 
D2 plan and run conferences, convocation ceremon H5 p1.0 n10 | -- p0.0 n0 | H5 p1.0 n10 
D3 manage research grant applications and post-a H5 p0.9 n10 | -- p0.0 n0 | H5 p0.9 n10 
D4 write news stories, manage social media and t H5 p0.8 n10 | -- p0.0 n0 | H5 p0.8 n10 
C1 supervisory admin role in Faculty of Science, -- p0.0 n10 | -- p0.0 n0 | -- p0.0 n10 
C2 CUPE administrative assistant                 H5 p0.8 n10 | -- p0.0 n0 | H5 p0.5 n10 
C3 APSA communications officer                   H5 p0.7 n10 | -- p0.0 n0 | H5 p0.7 n10 
C4 academic advisor in the Beedie business schoo H5 p0.1 n10 | -- p0.0 n0 | H5 p0.1 n10 
A1 coop coord                                    H5 p0.7 n10 | -- p0.0 n0 | H5 p0.6 n10 
A2 IT sysadmin                                   H5 p0.5 n10 | -- p0.0 n0 | H5 p0.6 n10 
A3 AP clerk                                      H5 p0.4 n10 | -- p0.0 n0 | H5 p0.4 n10 
A4 adminstrative cordinator                      -- p0.0 n10 | -- p0.0 n0 | -- p0.0 n10 
A5 HR advisor labour relations                   H5 p0.9 n10 | -- p0.0 n0 | H5 p0.9 n10 
A6 web dev                                       H5 p1.0 n10 | H5 p0.8 n8 | H5 p0.9 n10 
===== /tmp/spike_rerank_gpt-oss_120b.json rerank gpt-oss:120b
builder_nlp {'n': 22, 'hit5': 18, 'hit10': 18, 'p10': 0.782, 'empty': 2}
library_nlp {'n': 22, 'hit5': 20, 'hit10': 20, 'p10': 0.777, 'empty': 0}
library_nlp_dept {'n': 2, 'hit5': 2, 'hit10': 2, 'p10': 0.35, 'empty': 0}
library_nlp_rerank {'n': 22, 'hit5': 21, 'hit10': 21, 'p10': 0.773, 'empty': 1}
plan_s p50 4.66 p95 7.417 max 24.977 min 3.757
builder_nlp_s p50 3.43 p95 13.749 max 13.782 min 0.296
rerank_s p50 5.98 p95 10.517 max 10.984 min 3.018
per-query: id | builder_nlp | library_nlp | library_nlp_dept | library_nlp_rerank
E1 Financial Assistant                           H5 p1.0 n10 | H5 p0.6 n10 | - | H5 p0.6 n6 
E2 Co-op Education Coordinator                   H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p1.0 n10 
E3 Research Grants Facilitator                   H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p1.0 n10 
E4 Laboratory Technician                         H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p1.0 n10 
P1 someone who processes invoices and reconciles -- p0.0 n0 | H5 p0.3 n10 | - | H5 p0.3 n10 
P2 person who helps students plan their courses  H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p1.0 n10 
P3 fundraiser who builds relationships with majo H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p1.0 n10 
P4 entry-level library job shelving books and he H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p0.9 n10 
D1 maintain Linux servers, apply patches, run ba H5 p1.0 n10 | H5 p0.9 n10 | - | H5 p0.9 n10 
D2 plan and run conferences, convocation ceremon H5 p0.6 n10 | H5 p0.6 n10 | - | H5 p0.7 n10 
D3 manage research grant applications and post-a H5 p0.9 n10 | H5 p0.9 n10 | - | H5 p1.0 n10 
D4 write news stories, manage social media and t H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p1.0 n10 
C1 supervisory admin role in Faculty of Science, -- p0.0 n10 | -- p0.0 n10 | H5 p0.4 n4 | -- p0.0 n0 
C2 CUPE administrative assistant                 H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p1.0 n10 
C3 APSA communications officer                   H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p1.0 n10 
C4 academic advisor in the Beedie business schoo -- p0.0 n10 | -- p0.0 n10 | H5 p0.3 n6 | H5 p0.1 n1 
A1 coop coord                                    H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p1.0 n10 
A2 IT sysadmin                                   H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p0.9 n9 
A3 AP clerk                                      -- p0.0 n0 | H5 p0.1 n10 | - | H5 p0.1 n3 
A4 adminstrative cordinator                      H5 p1.0 n10 | H5 p1.0 n10 | - | H5 p1.0 n10 
A5 HR advisor labour relations                   H5 p0.8 n10 | H5 p0.8 n10 | - | H5 p0.6 n8 
A6 web dev                                       H5 p0.9 n10 | H5 p0.9 n10 | - | H5 p0.9 n10 
===== /tmp/spike_guarded_gpt-oss_120b.json guarded gpt-oss:120b
builder_guarded {'n': 22, 'hit5': 20, 'hit10': 20, 'p10': 0.859, 'empty': 0}
library_guarded {'n': 22, 'hit5': 21, 'hit10': 21, 'p10': 0.827, 'empty': 0}
builder_nlp_s p50 6.87 p95 16.08 max 16.163 min 1.102
per-query: id | builder_guarded | library_guarded
E1 Financial Assistant                           H5 p1.0 n10 | H5 p0.6 n10 
E2 Co-op Education Coordinator                   H5 p1.0 n10 | H5 p1.0 n10 
E3 Research Grants Facilitator                   H5 p1.0 n10 | H5 p1.0 n10 
E4 Laboratory Technician                         H5 p1.0 n10 | H5 p1.0 n10 
P1 someone who processes invoices and reconciles H5 p0.8 n10 | H5 p0.5 n10 
P2 person who helps students plan their courses  H5 p1.0 n10 | H5 p1.0 n10 
P3 fundraiser who builds relationships with majo H5 p1.0 n10 | H5 p1.0 n10 
P4 entry-level library job shelving books and he H5 p1.0 n10 | H5 p1.0 n10 
D1 maintain Linux servers, apply patches, run ba H5 p1.0 n10 | H5 p1.0 n10 
D2 plan and run conferences, convocation ceremon H5 p0.6 n10 | H5 p0.9 n10 
D3 manage research grant applications and post-a H5 p0.9 n10 | H5 p0.9 n10 
D4 write news stories, manage social media and t H5 p1.0 n10 | H5 p1.0 n10 
C1 supervisory admin role in Faculty of Science, -- p0.0 n10 | -- p0.0 n10 
C2 CUPE administrative assistant                 H5 p1.0 n10 | H5 p1.0 n10 
C3 APSA communications officer                   H5 p1.0 n10 | H5 p1.0 n10 
C4 academic advisor in the Beedie business schoo -- p0.0 n10 | H5 p0.1 n10 
A1 coop coord                                    H5 p1.0 n10 | H5 p1.0 n10 
A2 IT sysadmin                                   H5 p1.0 n10 | H5 p1.0 n10 
A3 AP clerk                                      H5 p0.8 n10 | H5 p0.5 n10 
A4 adminstrative cordinator                      H5 p1.0 n10 | H5 p1.0 n10 
A5 HR advisor labour relations                   H5 p0.8 n10 | H5 p0.8 n10 
A6 web dev                                       H5 p1.0 n10 | H5 p0.9 n10 
===== /tmp/spike_nlp_gpt-oss_20b.json nlp gpt-oss:20b
builder_nlp {'n': 22, 'hit5': 17, 'hit10': 17, 'p10': 0.741, 'empty': 3}
library_nlp {'n': 22, 'hit5': 18, 'hit10': 19, 'p10': 0.745, 'empty': 0}
library_nlp_dept {'n': 3, 'hit5': 3, 'hit10': 3, 'p10': 0.667, 'empty': 0}
plan_s p50 3.29 p95 6.056 max 10.012 min 2.291
builder_nlp_s p50 3.61 p95 10.246 max 11.132 min 0.296
per-query: id | builder_nlp | library_nlp | library_nlp_dept
E1 Financial Assistant                           -- p0.0 n0 | -- p0.0 n10 | - 
E2 Co-op Education Coordinator                   H5 p1.0 n10 | H5 p1.0 n10 | - 
E3 Research Grants Facilitator                   H5 p1.0 n10 | H5 p1.0 n10 | - 
E4 Laboratory Technician                         H5 p1.0 n10 | H5 p1.0 n10 | - 
P1 someone who processes invoices and reconciles -- p0.0 n0 | h10 p0.1 n10 | - 
P2 person who helps students plan their courses  H5 p1.0 n10 | H5 p1.0 n10 | - 
P3 fundraiser who builds relationships with majo H5 p0.9 n10 | H5 p0.9 n10 | - 
P4 entry-level library job shelving books and he H5 p1.0 n10 | H5 p1.0 n10 | H5 p0.9 n10 
D1 maintain Linux servers, apply patches, run ba H5 p1.0 n10 | H5 p0.9 n10 | - 
D2 plan and run conferences, convocation ceremon H5 p0.9 n10 | H5 p0.9 n10 | - 
D3 manage research grant applications and post-a H5 p0.8 n10 | H5 p0.8 n10 | - 
D4 write news stories, manage social media and t H5 p1.0 n10 | H5 p1.0 n10 | - 
C1 supervisory admin role in Faculty of Science, -- p0.0 n10 | -- p0.0 n10 | H5 p0.5 n6 
C2 CUPE administrative assistant                 H5 p1.0 n10 | H5 p1.0 n10 | - 
C3 APSA communications officer                   H5 p1.0 n10 | H5 p1.0 n10 | - 
C4 academic advisor in the Beedie business schoo -- p0.0 n10 | -- p0.0 n10 | H5 p0.6 n8 
A1 coop coord                                    H5 p1.0 n10 | H5 p1.0 n10 | - 
A2 IT sysadmin                                   H5 p1.0 n10 | H5 p0.9 n10 | - 
A3 AP clerk                                      -- p0.0 n0 | H5 p0.2 n10 | - 
A4 adminstrative cordinator                      H5 p1.0 n10 | H5 p1.0 n10 | - 
A5 HR advisor labour relations                   H5 p0.7 n10 | H5 p0.8 n10 | - 
A6 web dev                                       H5 p1.0 n10 | H5 p0.9 n10 | - 
===== /tmp/spike_guarded_gpt-oss_20b.json guarded gpt-oss:20b
builder_guarded {'n': 22, 'hit5': 20, 'hit10': 20, 'p10': 0.868, 'empty': 0}
library_guarded {'n': 22, 'hit5': 21, 'hit10': 21, 'p10': 0.836, 'empty': 0}
builder_nlp_s p50 7.44 p95 11.606 max 11.627 min 1.16
per-query: id | builder_guarded | library_guarded
E1 Financial Assistant                           H5 p1.0 n10 | H5 p0.6 n10 
E2 Co-op Education Coordinator                   H5 p1.0 n10 | H5 p1.0 n10 
E3 Research Grants Facilitator                   H5 p1.0 n10 | H5 p1.0 n10 
E4 Laboratory Technician                         H5 p1.0 n10 | H5 p1.0 n10 
P1 someone who processes invoices and reconciles H5 p0.8 n10 | H5 p0.4 n10 
P2 person who helps students plan their courses  H5 p1.0 n10 | H5 p1.0 n10 
P3 fundraiser who builds relationships with majo H5 p0.9 n10 | H5 p0.9 n10 
P4 entry-level library job shelving books and he H5 p1.0 n10 | H5 p0.9 n10 
D1 maintain Linux servers, apply patches, run ba H5 p1.0 n10 | H5 p1.0 n10 
D2 plan and run conferences, convocation ceremon H5 p0.9 n10 | H5 p1.0 n10 
D3 manage research grant applications and post-a H5 p0.8 n10 | H5 p0.8 n10 
D4 write news stories, manage social media and t H5 p1.0 n10 | H5 p1.0 n10 
C1 supervisory admin role in Faculty of Science, -- p0.0 n10 | -- p0.0 n10 
C2 CUPE administrative assistant                 H5 p1.0 n10 | H5 p1.0 n10 
C3 APSA communications officer                   H5 p1.0 n10 | H5 p1.0 n10 
C4 academic advisor in the Beedie business schoo -- p0.0 n10 | H5 p0.2 n10 
A1 coop coord                                    H5 p1.0 n10 | H5 p1.0 n10 
A2 IT sysadmin                                   H5 p1.0 n10 | H5 p1.0 n10 
A3 AP clerk                                      H5 p0.8 n10 | H5 p0.8 n10 
A4 adminstrative cordinator                      H5 p1.0 n10 | H5 p1.0 n10 
A5 HR advisor labour relations                   H5 p0.9 n10 | H5 p0.9 n10 
A6 web dev                                       H5 p1.0 n10 | H5 p0.9 n10 
```
