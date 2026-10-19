BEGIN READ ONLY;
WITH f AS (SELECT s.id, (SELECT count(*) FROM regexp_matches(s.filename,'(?<![0-9])(0[0-9]{7})(?![0-9])','g')) n,
  s.filename ~ '^\d{8}_\d{1,7}[,_]' AS unpadded_lead FROM source_documents s)
SELECT count(*) FILTER (WHERE n>=2) multi_position_files, count(*) FILTER (WHERE n=0) no_padded_id, count(*) FILTER (WHERE n=0 AND unpadded_lead) no_padded_but_unpadded_lead FROM f;
ROLLBACK;
