-- =============================================================================
-- EMIS Data Warehouse: ETL Step — SCD2 Load → dw.schools_dim
-- Called nightly AFTER 01_flatten_schools.sql.
-- Implements full SCD Type 2 with change_hash, changed_fields, change_reason.
--
-- FIX (2026-05): admin_unit_id JOIN changed from source_id to id.
--   Previously:  JOIN dw.admin_units_dim aud ON aud.source_id = stg_s.admin_unit_id
--   Now:         JOIN dw.admin_units_dim aud ON aud.id         = stg_s.admin_unit_id
--
--   This is required because 01_flatten_schools.sql now stores
--   dw.admin_units_dim.id (surrogate key) in stg.schools_flat.admin_unit_id,
--   not source_id. Joining on source_id was ambiguous when multiple
--   admin_units_dim rows shared the same source_id (duplicate nodes),
--   causing arbitrary node selection and massive cross-district school
--   misassignment (BUSHENYI/IBANDA inflation in Top 15 Districts report).
--
-- FIX (prior): Added ON CONFLICT (emis_number) DO UPDATE to handle cases
--   where two source records share the same EMIS number (data quality issue).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------
-- STEP A: Expire rows where tracked attributes have changed
-- -----------------------------------------------------------------------
UPDATE dw.schools_dim AS dw_s
SET
    expiration_date = CURRENT_DATE - 1,
    is_current      = FALSE
FROM stg.schools_flat stg_s
JOIN dw.admin_units_dim aud
    ON aud.id             = stg_s.admin_unit_id   -- FIX: id not source_id
   AND aud.current_status = TRUE
WHERE
    dw_s.source_id   = stg_s.source_id
    AND dw_s.is_current = TRUE
    AND dw_s.change_hash <>
        MD5(CONCAT_WS('|',
            COALESCE(stg_s.name,               ''),
            COALESCE(aud.id::TEXT,             ''),
            COALESCE(stg_s.emis_number,        ''),
            COALESCE(stg_s.school_type,        ''),
            COALESCE(stg_s.operational_status, ''),
            COALESCE(stg_s.ownership_status,   ''),
            COALESCE(stg_s.funding_type,       ''),
            COALESCE(stg_s.sex_composition,    ''),
            COALESCE(stg_s.boarding_status,    ''),
            COALESCE(stg_s.founding_body_type, '')
        ));


-- -----------------------------------------------------------------------
-- STEP B: Insert new rows (first version OR changed version)
-- ON CONFLICT (emis_number) DO UPDATE handles the case where EMIS has
-- two schools with the same emis_number (duplicate source records).
-- In that case we keep the most recent version by updating in place.
-- -----------------------------------------------------------------------
INSERT INTO dw.schools_dim (
    source_id,
    name,
    admin_unit_id,
    emis_number,
    school_type,
    operational_status,
    ownership_status,
    funding_type,
    sex_composition,
    boarding_status,
    founding_body_type,
    effective_date,
    expiration_date,
    is_current,
    change_hash,
    change_reason,
    changed_fields
)
SELECT
    stg_s.source_id,
    stg_s.name,
    aud.id                                              AS admin_unit_id,
    stg_s.emis_number,
    stg_s.school_type,
    stg_s.operational_status,
    stg_s.ownership_status,
    stg_s.funding_type,
    stg_s.sex_composition,
    stg_s.boarding_status,
    stg_s.founding_body_type,
    CURRENT_DATE                                        AS effective_date,
    '9999-12-31'::DATE                                  AS expiration_date,
    TRUE                                                AS is_current,

    MD5(CONCAT_WS('|',
        COALESCE(stg_s.name,               ''),
        COALESCE(aud.id::TEXT,             ''),
        COALESCE(stg_s.emis_number,        ''),
        COALESCE(stg_s.school_type,        ''),
        COALESCE(stg_s.operational_status, ''),
        COALESCE(stg_s.ownership_status,   ''),
        COALESCE(stg_s.funding_type,       ''),
        COALESCE(stg_s.sex_composition,    ''),
        COALESCE(stg_s.boarding_status,    ''),
        COALESCE(stg_s.founding_body_type, '')
    ))                                                  AS change_hash,

    CASE
        WHEN dw_old.id IS NULL               THEN 'INITIAL_LOAD'
        WHEN dw_old.name <> stg_s.name      THEN 'School renamed'
        WHEN dw_old.admin_unit_id <> aud.id THEN 'Admin unit re-assignment or boundary update'
        WHEN dw_old.operational_status <> stg_s.operational_status THEN 'Operational status updated'
        WHEN dw_old.boarding_status    <> stg_s.boarding_status    THEN 'Boarding status changed'
        WHEN dw_old.sex_composition    <> stg_s.sex_composition    THEN 'Sex composition changed'
        WHEN dw_old.ownership_status   <> stg_s.ownership_status   THEN 'Ownership status changed'
        WHEN dw_old.funding_type       <> stg_s.funding_type       THEN 'Funding type changed'
        WHEN dw_old.founding_body_type <> stg_s.founding_body_type THEN 'Founding body changed'
        ELSE 'Attribute update'
    END                                                 AS change_reason,

    TRIM(BOTH ',' FROM CONCAT_WS(',',
        CASE WHEN dw_old.id IS NULL                                        THEN 'ALL'           ELSE NULL END,
        CASE WHEN dw_old.id IS NOT NULL AND dw_old.name <> stg_s.name     THEN 'name'          ELSE NULL END,
        CASE WHEN dw_old.id IS NOT NULL AND dw_old.admin_unit_id <> aud.id THEN 'admin_unit_id' ELSE NULL END,
        CASE WHEN dw_old.id IS NOT NULL AND dw_old.operational_status <> stg_s.operational_status THEN 'operational_status' ELSE NULL END,
        CASE WHEN dw_old.id IS NOT NULL AND dw_old.boarding_status    <> stg_s.boarding_status    THEN 'boarding_status'    ELSE NULL END,
        CASE WHEN dw_old.id IS NOT NULL AND dw_old.sex_composition    <> stg_s.sex_composition    THEN 'sex_composition'    ELSE NULL END,
        CASE WHEN dw_old.id IS NOT NULL AND dw_old.ownership_status   <> stg_s.ownership_status   THEN 'ownership_status'   ELSE NULL END,
        CASE WHEN dw_old.id IS NOT NULL AND dw_old.funding_type       <> stg_s.funding_type       THEN 'funding_type'       ELSE NULL END,
        CASE WHEN dw_old.id IS NOT NULL AND dw_old.founding_body_type <> stg_s.founding_body_type THEN 'founding_body_type' ELSE NULL END
    ))                                                  AS changed_fields

FROM stg.schools_flat stg_s

JOIN dw.admin_units_dim aud
    ON aud.id             = stg_s.admin_unit_id   -- FIX: id not source_id
   AND aud.current_status = TRUE

LEFT JOIN dw.schools_dim dw_old
    ON  dw_old.source_id  = stg_s.source_id
    AND dw_old.is_current = FALSE
    AND dw_old.expiration_date = CURRENT_DATE - 1

WHERE NOT EXISTS (
    SELECT 1
    FROM   dw.schools_dim existing
    WHERE  existing.source_id  = stg_s.source_id
      AND  existing.is_current = TRUE
)

-- Handle duplicate emis_number in EMIS source data:
-- If another source_id already inserted a row with the same emis_number,
-- update it in place rather than failing.
ON CONFLICT (emis_number) DO UPDATE
    SET
        source_id          = EXCLUDED.source_id,
        name               = EXCLUDED.name,
        admin_unit_id      = EXCLUDED.admin_unit_id,
        school_type        = EXCLUDED.school_type,
        operational_status = EXCLUDED.operational_status,
        ownership_status   = EXCLUDED.ownership_status,
        funding_type       = EXCLUDED.funding_type,
        sex_composition    = EXCLUDED.sex_composition,
        boarding_status    = EXCLUDED.boarding_status,
        founding_body_type = EXCLUDED.founding_body_type,
        effective_date     = EXCLUDED.effective_date,
        expiration_date    = EXCLUDED.expiration_date,
        is_current         = EXCLUDED.is_current,
        change_hash        = EXCLUDED.change_hash,
        change_reason      = EXCLUDED.change_reason,
        changed_fields     = EXCLUDED.changed_fields;

COMMIT;
