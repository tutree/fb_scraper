-- PostgreSQL: reset leads that were incorrectly marked analyzed after an AI transport/parse failure.
-- Preview matches first; then run the UPDATE in a transaction.

-- --- Preview: see what would be cleared ---
SELECT id,
       name,
       LEFT(analysis_message, 200) AS analysis_message_preview,
       analyzed_at,
       user_type
FROM search_results
WHERE archived = false
  AND analysis_message IS NOT NULL
  AND (
        analysis_message ILIKE '%Failed to parse AI response%'
     OR analysis_message ILIKE '%Groq request failed%'
     OR analysis_message ILIKE '%Classification error:%'
     OR analysis_message ILIKE '%Comment classification error:%'
     OR analysis_message ILIKE '%Geo classification error:%'
  )
ORDER BY analyzed_at DESC NULLS LAST;

-- --- Apply reset (run in a transaction; COMMIT or ROLLBACK) ---
BEGIN;

UPDATE search_results
SET analyzed_at = NULL,
    user_type = NULL,
    confidence_score = NULL,
    analysis_message = NULL
WHERE archived = false
  AND analysis_message IS NOT NULL
  AND (
        analysis_message ILIKE '%Failed to parse AI response%'
     OR analysis_message ILIKE '%Groq request failed%'
     OR analysis_message ILIKE '%Classification error:%'
     OR analysis_message ILIKE '%Comment classification error:%'
     OR analysis_message ILIKE '%Geo classification error:%'
  );

-- Check row count matches expectation, then:
-- COMMIT;
-- ROLLBACK;
