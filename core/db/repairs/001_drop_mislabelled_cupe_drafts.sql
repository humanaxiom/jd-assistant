-- Repair 001 — drop the DRAFT canonical JDs that claim the CUPE template while their
-- source documents are not CUPE.
--
-- WHY
-- The v6 parser fix (HR-226) established that a job description was being called CUPE
-- because it MENTIONED the word — "Directly supervises CUPE employees". ~140 documents
-- were mislabelled, and 61 of them had already been harmonized into 24 drafts. Every one
-- of those drafts is built ENTIRELY from mislabelled documents, so each is a "CUPE role"
-- made of APSA managers: Director, Advancement · Undergraduate Records Manager ·
-- Assistant Director, Conference and Guest Accommodations · Network Systems Analyst.
-- They were scored on the WJQ profile and counted as CUPE everywhere.
--
-- WHY DELETE RATHER THAN RE-COMPOSE
-- Ruled by the project owner 2026-08-29. A cluster with no draft reads as *un-drafted*,
-- which is an honest state the funnel already accounts for; a cluster with a WRONG draft
-- reads as a finished role. The next producer run regenerates them on the template their
-- documents actually are. `src.jd_bank.canonical` has `--only-template` but no
-- per-cluster filter, so re-composing exactly these is not currently expressible.
--
-- WHAT IT DOES NOT TOUCH
--   * `clusters` — the grouping is unaffected; only the composed draft was wrong.
--   * `audit_log` — it is HASH-CHAINED (`audit_chain_tail`). Hand-writing a row would
--     corrupt the chain, so this repair is recorded in git and in docs/FINDINGS.md §7d,
--     not by forging an entry the application did not make.
--   * anything PUBLISHED. The guard below refuses to run if that ever changes.
--
-- SAFETY
-- Selects by the DERIVED condition, never by hardcoded ids, so it is self-documenting
-- and idempotent: run it twice and the second run deletes nothing. It is wrapped in a
-- transaction with an assertion that nothing published or reviewed is in scope.
--
-- RUN
--   docker exec -i jd-bank-postgres-1 psql -U app -d harness \
--     -f - < core/db/repairs/001_drop_mislabelled_cupe_drafts.sql
--
-- VERIFY
--   make smoke   -- test_no_draft_claims_a_template_its_documents_do_not goes green

BEGIN;

CREATE TEMP TABLE _cur ON COMMIT DROP AS
  SELECT DISTINCT ON (cluster_id) * FROM canonical_jds ORDER BY cluster_id, version DESC;

CREATE TEMP TABLE _latest ON COMMIT DROP AS
  SELECT DISTINCT ON (source_document_id)
         source_document_id AS sid, parsed->>'employee_group' AS grp
  FROM parsed_jds ORDER BY source_document_id, created_at DESC;

-- A draft is in scope only when it CLAIMS cupe and NOT ONE of its documents is cupe.
-- The `NOT EXISTS` is load-bearing: a mixed cluster (some members genuinely CUPE) is a
-- different problem and must not be deleted by a repair aimed at wholly-wrong drafts.
CREATE TEMP TABLE _doomed ON COMMIT DROP AS
  SELECT c.id, c.cluster_id
  FROM _cur c
  WHERE c.content->>'employee_group' = 'cupe'
    AND EXISTS (
      SELECT 1 FROM jsonb_array_elements(c.source_document_ids) s
      JOIN _latest l ON l.sid = (s.value->>'source_id')::uuid
      WHERE coalesce(l.grp, '') <> 'cupe')
    AND NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements(c.source_document_ids) s
      JOIN _latest l ON l.sid = (s.value->>'source_id')::uuid
      WHERE l.grp = 'cupe');

DO $$
DECLARE
    n_published int;
    n_reviewed  int;
BEGIN
    SELECT count(*) INTO n_published
      FROM canonical_jds c JOIN _doomed d ON d.cluster_id = c.cluster_id
     WHERE c.status <> 'DRAFT';
    IF n_published > 0 THEN
        RAISE EXCEPTION
          'REFUSING: % non-DRAFT canonical rows are in scope. A published or archived '
          'version must never be deleted by a repair (non-negotiable #1).', n_published;
    END IF;

    SELECT count(*) INTO n_reviewed
      FROM review_actions ra
      JOIN canonical_jds c ON c.id = ra.canonical_jd_id
      JOIN _doomed d ON d.cluster_id = c.cluster_id;
    IF n_reviewed > 0 THEN
        RAISE EXCEPTION
          'REFUSING: % reviewer actions are attached. A human has already ruled on these '
          'drafts; deleting them would erase that record.', n_reviewed;
    END IF;

    RAISE NOTICE 'repair 001: deleting % mislabelled CUPE drafts',
                 (SELECT count(*) FROM _doomed);
END $$;

DELETE FROM canonical_jds WHERE id IN (SELECT id FROM _doomed);

COMMIT;
