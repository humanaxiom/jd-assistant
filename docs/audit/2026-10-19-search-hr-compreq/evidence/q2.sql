BEGIN READ ONLY;
WITH cur AS (SELECT DISTINCT ON (cluster_id) * FROM canonical_jds ORDER BY cluster_id, version DESC)
SELECT count(*) roles,
 count(*) FILTER (WHERE nullif(content->>'position_number','') IS NOT NULL) pos_no,
 count(*) FILTER (WHERE nullif(content->>'department','') IS NOT NULL) dept,
 count(*) FILTER (WHERE nullif(content->>'employee_group','') IS NOT NULL) grp,
 count(*) FILTER (WHERE jsonb_typeof(content->'classification')='object') classif,
 count(*) FILTER (WHERE content->'classification'->>'source'='hris') classif_hris,
 count(*) FILTER (WHERE content->'classification'->>'source'='entered') classif_entered,
 count(*) FILTER (WHERE nullif(content->>'grade','') IS NOT NULL) grade_str
FROM cur;
WITH cur AS (SELECT DISTINCT ON (cluster_id) * FROM canonical_jds ORDER BY cluster_id, version DESC)
SELECT content->'classification'->>'scheme', content->'classification'->>'source', count(*) FROM cur WHERE jsonb_typeof(content->'classification')='object' GROUP BY 1,2 ORDER BY 3 DESC;
SELECT source_document_ids->0 sample FROM canonical_jds LIMIT 1;
SELECT parsed->>'department' d, count(*) FROM parsed_jds WHERE parser_version='jd_segmenter_v8' GROUP BY 1 ORDER BY 2 DESC LIMIT 15;
SELECT parsed->>'position_number' p, count(*) FROM parsed_jds WHERE parser_version='jd_segmenter_v8' GROUP BY 1 ORDER BY 2 DESC LIMIT 8;
SELECT count(*) FILTER (WHERE parsed->>'department' ~ '\m\d{4}\M') dept_has_4digit_code FROM parsed_jds WHERE parser_version='jd_segmenter_v8';
SELECT count(*) FILTER (WHERE parsed->>'position_number' ~ '^0\d{7}$') padded8, count(*) FILTER (WHERE parsed->>'position_number' ~ '^\d+$') digits_only FROM parsed_jds WHERE parser_version='jd_segmenter_v8';
ROLLBACK;
