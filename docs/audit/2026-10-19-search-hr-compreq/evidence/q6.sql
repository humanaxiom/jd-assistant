BEGIN READ ONLY;
SELECT s.filename, p.parsed->>'title' t, p.parsed->>'position_number' pn, p.parsed->>'department' d, p.parsed->>'employee_group' g, p.parsed->'classification' c, left(p.parsed->>'position_summary',80) ps
FROM source_documents s JOIN parsed_jds p ON p.source_document_id=s.id AND p.parser_version='jd_segmenter_v8'
WHERE s.filename LIKE '20200601_%30785%' OR s.filename LIKE '%00000337_JDFN%' OR s.filename LIKE '%00000075%' ORDER BY 1 DESC LIMIT 6;
ROLLBACK;
