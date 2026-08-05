// Phase 5.4b — vectors for HARMONIZED ROLES (canonical_jds), so the Builder's
// "start from an existing JD" can find the Bank's own output semantically and not
// only by title.
//
// A SEPARATE label and index from `JDDocument`/`jd_document_embeddings` on purpose.
// The document index describes the ARCHIVE (one node per source file) and is read by
// `composer.search` for neighbours and by dedup/cluster via id lookup; a role is a
// different unit entirely (one node per cluster, distilled from many documents).
// Folding roles into `JDDocument` would work today and quietly corrupt the next
// `MATCH (d:JDDocument)` corpus count — the "one index, two purposes" trap that
// produced both the title-search and advisory-badge defects.
//
// Dimensions/similarity are hardcoded here because Cypher cannot read the rulebook;
// they MUST match `embeddings.yaml` (768, cosine) — the same duplication, and the
// same registered caveat, as migration 002.

CREATE CONSTRAINT jd_role_id IF NOT EXISTS
FOR (r:JDRole) REQUIRE r.id IS UNIQUE;

CREATE VECTOR INDEX jd_role_embeddings IF NOT EXISTS
FOR (r:JDRole) ON (r.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 768,
  `vector.similarity_function`: 'cosine'
}};
