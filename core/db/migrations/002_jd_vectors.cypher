// 002_jd_vectors.cypher — JD Bank vector indexes (doc + section embeddings)
// Run via: make migrate (applied after 001_init.cypher)
//
// Per-document and per-section embeddings (768-dim cosine, nomic-embed-text)
// live here, each carrying a `model` tag for reindex safety and a back-reference
// (`source_document_id` / `parsed_jd_id`) to its Postgres row. Postgres holds no
// vectors (plan §1).

CREATE CONSTRAINT jd_document_id IF NOT EXISTS
FOR (d:JDDocument) REQUIRE d.id IS UNIQUE;

CREATE CONSTRAINT jd_section_id IF NOT EXISTS
FOR (s:JDSection) REQUIRE s.id IS UNIQUE;

// 768-dim cosine vector index for whole-document JD embeddings.
CREATE VECTOR INDEX jd_document_embeddings IF NOT EXISTS
FOR (d:JDDocument) ON (d.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 768,
  `vector.similarity_function`: 'cosine'
}};

// 768-dim cosine vector index for per-section JD embeddings.
CREATE VECTOR INDEX jd_section_embeddings IF NOT EXISTS
FOR (s:JDSection) ON (s.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 768,
  `vector.similarity_function`: 'cosine'
}};
