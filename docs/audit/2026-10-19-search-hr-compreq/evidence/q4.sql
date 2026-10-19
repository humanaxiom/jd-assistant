BEGIN READ ONLY;
WITH pos AS (
  SELECT m[1] pid, s.id sid, s.filename, substring(s.filename from '^(\d{8})') d
  FROM source_documents s, regexp_matches(s.filename,'(?<![0-9])(0[0-9]{7})(?![0-9])','g') m),
latest AS (SELECT DISTINCT ON (pid) * FROM pos ORDER BY pid, d DESC, filename DESC),
j AS (SELECT l.pid, l.filename, p.parsed FROM latest l LEFT JOIN parsed_jds p ON p.source_document_id=l.sid AND p.parser_version='jd_segmenter_v8')
SELECT count(*) positions,
 count(*) FILTER (WHERE parsed IS NOT NULL) parsed,
 count(*) FILTER (WHERE filename ~ 'JDFN') latest_is_jdfn,
 count(*) FILTER (WHERE substring(filename from '^(\d{4})')::int >= 2019) latest_2019plus,
 count(*) FILTER (WHERE nullif(parsed->>'title','') IS NOT NULL AND parsed->>'title'<>'Untitled Position') title,
 count(*) FILTER (WHERE nullif(parsed->>'department','') IS NOT NULL) dept_name,
 count(*) FILTER (WHERE parsed->>'employee_group' IS NOT NULL) grp,
 count(*) FILTER (WHERE jsonb_typeof(parsed->'classification')='object') grade,
 count(*) FILTER (WHERE parsed->>'position_number' = pid) header_pos_agrees,
 count(*) FILTER (WHERE nullif(parsed->>'position_number','') IS NOT NULL AND parsed->>'position_number' <> pid) header_pos_differs,
 count(*) FILTER (WHERE nullif(parsed->>'position_summary','') IS NOT NULL) summary
FROM j;
ROLLBACK;
