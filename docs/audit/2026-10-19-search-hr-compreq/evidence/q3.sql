BEGIN READ ONLY;
-- filename position ids (rulebook segmentation.position_id_pattern) over all source docs
SELECT count(*) docs,
 count(*) FILTER (WHERE filename ~ '(?<![0-9])0[0-9]{7}(?![0-9])') with_padded_id,
 count(*) FILTER (WHERE filename ~ 'JDFN') jdfn,
 count(*) FILTER (WHERE filename ~ '^(19|20)\d{6}_') date_prefix
FROM source_documents;
SELECT count(DISTINCT m[1]) distinct_positions FROM source_documents, regexp_matches(filename,'(?<![0-9])(0[0-9]{7})(?![0-9])','g') m;
-- roles -> member source docs -> filename position ids
WITH cur AS (SELECT DISTINCT ON (cluster_id) * FROM canonical_jds ORDER BY cluster_id, version DESC),
mem AS (SELECT c.id rid, c.status, (e->>'source_id')::uuid sid FROM cur c, jsonb_array_elements(c.source_document_ids) e),
ids AS (SELECT m.rid, x[1] pid FROM mem m JOIN source_documents s ON s.id=m.sid, regexp_matches(s.filename,'(?<![0-9])(0[0-9]{7})(?![0-9])','g') x)
SELECT (SELECT count(*) FROM cur) roles,
 (SELECT count(DISTINCT rid) FROM mem) roles_with_sources,
 (SELECT count(DISTINCT rid) FROM ids) roles_with_filename_posid,
 (SELECT count(*) FROM (SELECT rid FROM ids GROUP BY rid HAVING count(DISTINCT pid)=1) z) roles_exactly_one_pos,
 (SELECT round(avg(n),1) FROM (SELECT rid, count(DISTINCT pid) n FROM ids GROUP BY rid) z) avg_pos_per_role,
 (SELECT max(n) FROM (SELECT rid, count(DISTINCT pid) n FROM ids GROUP BY rid) z) max_pos_per_role;
WITH cur AS (SELECT DISTINCT ON (cluster_id) * FROM canonical_jds ORDER BY cluster_id, version DESC)
SELECT content->>'grade' g, count(*) FROM cur WHERE nullif(content->>'grade','') IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
WITH cur AS (SELECT DISTINCT ON (cluster_id) * FROM canonical_jds ORDER BY cluster_id, version DESC)
SELECT content->>'employee_group' g, count(*) FROM cur GROUP BY 1 ORDER BY 2 DESC;
ROLLBACK;
