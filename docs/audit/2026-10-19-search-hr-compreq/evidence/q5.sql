BEGIN READ ONLY;
WITH pos AS (
  SELECT m[1] pid, s.id sid, s.filename, substring(s.filename from '^(\d{8})') d
  FROM source_documents s, regexp_matches(s.filename,'(?<![0-9])(0[0-9]{7})(?![0-9])','g') m),
latest AS (SELECT DISTINCT ON (pid) * FROM pos ORDER BY pid, d DESC, filename DESC),
j AS (SELECT l.pid, l.filename, p.parsed->>'position_number' hp FROM latest l JOIN parsed_jds p ON p.source_document_id=l.sid AND p.parser_version='jd_segmenter_v8')
SELECT count(*) FILTER (WHERE hp <> pid AND position(ltrim(pid,'0') in hp)>0) differs_but_contains_unpadded,
       count(*) FILTER (WHERE hp <> pid AND position(ltrim(pid,'0') in hp)=0) truly_different
FROM j WHERE nullif(hp,'') IS NOT NULL;
WITH pos AS (
  SELECT m[1] pid, s.id sid, s.filename, substring(s.filename from '^(\d{8})') d
  FROM source_documents s, regexp_matches(s.filename,'(?<![0-9])(0[0-9]{7})(?![0-9])','g') m),
latest AS (SELECT DISTINCT ON (pid) * FROM pos ORDER BY pid, d DESC, filename DESC)
SELECT l.pid, left(l.filename,60) f, p.parsed->>'position_number' hp FROM latest l JOIN parsed_jds p ON p.source_document_id=l.sid AND p.parser_version='jd_segmenter_v8'
WHERE nullif(p.parsed->>'position_number','') IS NOT NULL AND position(ltrim(l.pid,'0') in p.parsed->>'position_number')=0 LIMIT 8;
SELECT filename FROM source_documents WHERE filename LIKE '20200601_%30785%';
ROLLBACK;
