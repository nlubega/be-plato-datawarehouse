-- =============================================================================
-- EMIS Teachers Mart ETL: Step 2 — SCD2 Load into dw.teacher_dim
--
-- SCD2 tracked fields:
--   gender, qualification, qualification_category, teacher_type,
--   designation, highest_education_level, is_on_government_payroll,
--   discipline
--
-- Pattern: same as enrolment mart learner_dim SCD2
--   1. Deduplicate to one row per teacher from stg.teachers_flat
--   2. Expire changed rows in dw.teacher_dim
--   3. Insert new rows (new teachers + changed teachers)
-- =============================================================================

BEGIN;

-- ── Step 2a: Deduplicate to one row per teacher ───────────────────────────────
CREATE TEMP TABLE tmp_teachers_current AS
SELECT DISTINCT ON (person_id)
    person_id,
    employee_id,
    surname,
    given_name,
    gender,
    age                     AS age_at_load,
    nationality,
    nin,
    passport_no,
    teacher_type,
    qualification,
    qualification_category,
    designation,
    discipline,
    highest_education_level,
    is_on_government_payroll,
    ipps_number,
    tmis_number,
    moes_license_number,
    hrin,
    hcm_employee_number,
    first_appointment_date,
    posting_date,
    -- Change hash over all SCD2-tracked fields
    MD5(
        COALESCE(gender,                    '') ||'|'||
        COALESCE(qualification,             '') ||'|'||
        COALESCE(qualification_category,    '') ||'|'||
        COALESCE(teacher_type,              '') ||'|'||
        COALESCE(designation,               '') ||'|'||
        COALESCE(highest_education_level,   '') ||'|'||
        COALESCE(is_on_government_payroll::TEXT, 'false') ||'|'||
        COALESCE(discipline,                '')
    ) AS change_hash
FROM stg.teachers_flat
ORDER BY person_id, term_start_date DESC NULLS LAST;

CREATE INDEX ON tmp_teachers_current (person_id);

DO $$ DECLARE v BIGINT;
BEGIN
    SELECT COUNT(*) INTO v FROM tmp_teachers_current;
    RAISE NOTICE 'tmp_teachers_current: % distinct teachers', v;
END; $$;


-- ── Step 2b: Expire changed rows ──────────────────────────────────────────────
UPDATE dw.teacher_dim AS dim
SET
    expiration_date = CURRENT_DATE - 1,
    is_current      = FALSE
FROM tmp_teachers_current stg
WHERE dim.source_id   = stg.person_id
  AND dim.is_current  = TRUE
  AND dim.change_hash <> stg.change_hash;


DO $$ DECLARE v BIGINT;
BEGIN
    SELECT COUNT(*) INTO v FROM dw.teacher_dim WHERE is_current = FALSE;
    RAISE NOTICE 'dw.teacher_dim: % historical (expired) rows', v;
END; $$;


-- ── Step 2c: Insert new and changed rows ──────────────────────────────────────
INSERT INTO dw.teacher_dim (
    source_id,
    employee_id,
    surname,
    given_name,
    gender,
    date_of_birth,
    nationality,
    nin,
    passport_no,
    teacher_type,
    qualification,
    qualification_category,
    designation,
    discipline,
    highest_education_level,
    is_on_government_payroll,
    ipps_number,
    tmis_number,
    moes_license_number,
    hrin,
    hcm_employee_number,
    first_appointment_date,
    posting_date,
    effective_date,
    expiration_date,
    is_current,
    change_hash,
    change_reason,
    changed_fields
)
SELECT
    stg.person_id,
    stg.employee_id,
    stg.surname,
    stg.given_name,
    stg.gender,
    NULL                    AS date_of_birth,   -- not in teachers_flat; set from teachers_raw if needed
    stg.nationality,
    stg.nin,
    stg.passport_no,
    stg.teacher_type,
    stg.qualification,
    stg.qualification_category,
    stg.designation,
    stg.discipline,
    stg.highest_education_level,
    stg.is_on_government_payroll,
    stg.ipps_number,
    stg.tmis_number,
    stg.moes_license_number,
    stg.hrin,
    stg.hcm_employee_number,
    stg.first_appointment_date,
    stg.posting_date,
    CURRENT_DATE            AS effective_date,
    '9999-12-31'::DATE      AS expiration_date,
    TRUE                    AS is_current,
    stg.change_hash,

    CASE WHEN dim.id IS NULL THEN 'INITIAL_LOAD'
         ELSE 'ATTRIBUTE_CHANGE'
    END                     AS change_reason,

    CASE WHEN dim.id IS NULL THEN 'INITIAL_LOAD'
         ELSE TRIM(BOTH ',' FROM
            CASE WHEN COALESCE(dim.gender,'')                  <> COALESCE(stg.gender,'')                  THEN 'gender,'                  ELSE '' END ||
            CASE WHEN COALESCE(dim.qualification,'')           <> COALESCE(stg.qualification,'')           THEN 'qualification,'           ELSE '' END ||
            CASE WHEN COALESCE(dim.qualification_category,'')  <> COALESCE(stg.qualification_category,'')  THEN 'qualification_category,'  ELSE '' END ||
            CASE WHEN COALESCE(dim.teacher_type,'')            <> COALESCE(stg.teacher_type,'')            THEN 'teacher_type,'            ELSE '' END ||
            CASE WHEN COALESCE(dim.designation,'')             <> COALESCE(stg.designation,'')             THEN 'designation,'             ELSE '' END ||
            CASE WHEN COALESCE(dim.highest_education_level,'') <> COALESCE(stg.highest_education_level,'') THEN 'highest_education_level,'  ELSE '' END ||
            CASE WHEN COALESCE(dim.is_on_government_payroll::TEXT,'false') <> COALESCE(stg.is_on_government_payroll::TEXT,'false') THEN 'is_on_government_payroll,' ELSE '' END ||
            CASE WHEN COALESCE(dim.discipline,'')              <> COALESCE(stg.discipline,'')              THEN 'discipline,'              ELSE '' END
         )
    END                     AS changed_fields

FROM tmp_teachers_current stg
LEFT JOIN dw.teacher_dim dim
    ON  dim.source_id  = stg.person_id
    AND dim.is_current = TRUE
WHERE dim.id IS NULL;  -- new teachers OR just-expired rows have no current match


-- ── Step 2d: Verify ───────────────────────────────────────────────────────────
DO $$
DECLARE
    v_total     BIGINT;
    v_current   BIGINT;
    v_historical BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_total     FROM dw.teacher_dim;
    SELECT COUNT(*) INTO v_current   FROM dw.teacher_dim WHERE is_current = TRUE;
    SELECT COUNT(*) INTO v_historical FROM dw.teacher_dim WHERE is_current = FALSE;
    RAISE NOTICE 'dw.teacher_dim  total=% | current=% | historical=%',
        v_total, v_current, v_historical;
END;
$$;

DROP TABLE IF EXISTS tmp_teachers_current;

COMMIT;
