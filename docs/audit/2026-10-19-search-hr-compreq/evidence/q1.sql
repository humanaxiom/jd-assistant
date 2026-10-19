BEGIN READ ONLY;
SELECT count(*) AS source_docs FROM source_documents;
SELECT parser_version, count(*) FROM parsed_jds GROUP BY 1 ORDER BY 1;
WITH cur AS (SELECT p.* FROM parsed_jds p WHERE parser_version='jd_segmenter_v8')
SELECT count(*) n,
 count(*) FILTER (WHERE nullif(parsed->>'position_number','') IS NOT NULL) pos_no,
 count(*) FILTER (WHERE nullif(parsed->>'department','') IS NOT NULL) dept,
 count(*) FILTER (WHERE parsed->'employee_group' IS NOT NULL AND parsed->>'employee_group' IS NOT NULL) grp,
 count(*) FILTER (WHERE parsed->'classification' IS NOT NULL AND jsonb_typeof(parsed->'classification')='object') classif,
 count(*) FILTER (WHERE nullif(parsed->>'title','') IS NOT NULL AND parsed->>'title'<>'Untitled Position') title,
 count(*) FILTER (WHERE nullif(parsed->>'position_summary','') IS NOT NULL) summary,
 count(*) FILTER (WHERE jsonb_array_length(coalesce(parsed->'qualifications','[]'))>0) quals
FROM cur;
SELECT parsed->'classification'->>'scheme' scheme, parsed->'classification'->>'source' src, count(*) FROM parsed_jds WHERE parser_version='jd_segmenter_v8' AND jsonb_typeof(parsed->'classification')='object' GROUP BY 1,2 ORDER BY 3 DESC;
SELECT parsed->>'employee_group' g, count(*) FROM parsed_jds WHERE parser_version='jd_segmenter_v8' GROUP BY 1 ORDER BY 2 DESC;
SELECT status, count(*) FROM canonical_jds GROUP BY 1;
SELECT jsonb_object_keys(content) k, count(*) FROM canonical_jds GROUP BY 1 ORDER BY 2 DESC;
ROLLBACK;
