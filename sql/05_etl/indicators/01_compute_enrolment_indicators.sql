-- =============================================================================
-- EMIS Indicators Mart ETL: Step 1 — Compute Enrolment Indicators
--
-- HIERARCHY CONFIRMED (from diagnostics):
--   child_id = parent's SOURCE_ID (not parent's id/surrogate)
--   So: Parish.child_id = Sub County.source_id
--       Sub County.child_id = County.source_id
--       County.child_id = District.source_id
--
--   Schools link at many levels (DIAG D):
--     Parish: 43,615 | Sub County: 20,107 | Ward: 12,904
--     County: 8,741  | Town Council: 3,264 | District: 862
--     Municipality: 834 | City: 76
--
-- Strategy: build a lookup mapping every unit's id → its district's id,
-- covering all levels schools actually link to.
-- =============================================================================

BEGIN;

TRUNCATE TABLE stg.enrolment_indicator_raw;

-- ── Step 1a: Build unit → district lookup ─────────────────────────────────────
-- child_id = parent's source_id. Walk up to District level for every unit type.

CREATE TEMP TABLE tmp_unit_to_district AS

-- Parish → Sub County → County → District (standard rural path)
SELECT parish.id AS unit_dim_id, district.id AS district_dim_id, district.name AS district_name
FROM dw.admin_units_dim parish
JOIN dw.admin_units_dim sub_county ON sub_county.source_id = parish.child_id   AND sub_county.current_status = TRUE
JOIN dw.admin_units_dim county     ON county.source_id     = sub_county.child_id AND county.current_status   = TRUE
JOIN dw.admin_units_dim district   ON district.source_id   = county.child_id   AND district.admin_unit_type = 'District' AND district.current_status = TRUE
WHERE parish.current_status = TRUE AND parish.admin_unit_type = 'Parish'

UNION ALL

-- Ward → Sub County → County → District
SELECT ward.id, district.id, district.name
FROM dw.admin_units_dim ward
JOIN dw.admin_units_dim sub_county ON sub_county.source_id = ward.child_id     AND sub_county.current_status = TRUE
JOIN dw.admin_units_dim county     ON county.source_id     = sub_county.child_id AND county.current_status   = TRUE
JOIN dw.admin_units_dim district   ON district.source_id   = county.child_id   AND district.admin_unit_type = 'District' AND district.current_status = TRUE
WHERE ward.current_status = TRUE AND ward.admin_unit_type = 'Ward'

UNION ALL

-- Sub County → County → District
SELECT sc.id, district.id, district.name
FROM dw.admin_units_dim sc
JOIN dw.admin_units_dim county   ON county.source_id   = sc.child_id       AND county.current_status   = TRUE
JOIN dw.admin_units_dim district ON district.source_id = county.child_id   AND district.admin_unit_type = 'District' AND district.current_status = TRUE
WHERE sc.current_status = TRUE AND sc.admin_unit_type = 'Sub County'

UNION ALL

-- Town Council → County → District
SELECT tc.id, district.id, district.name
FROM dw.admin_units_dim tc
JOIN dw.admin_units_dim county   ON county.source_id   = tc.child_id       AND county.current_status   = TRUE
JOIN dw.admin_units_dim district ON district.source_id = county.child_id   AND district.admin_unit_type = 'District' AND district.current_status = TRUE
WHERE tc.current_status = TRUE AND tc.admin_unit_type = 'Town Council'

UNION ALL

-- County → District
SELECT county.id, district.id, district.name
FROM dw.admin_units_dim county
JOIN dw.admin_units_dim district ON district.source_id = county.child_id   AND district.admin_unit_type = 'District' AND district.current_status = TRUE
WHERE county.current_status = TRUE AND county.admin_unit_type = 'County'

UNION ALL

-- Municipality → District
SELECT muni.id, district.id, district.name
FROM dw.admin_units_dim muni
JOIN dw.admin_units_dim district ON district.source_id = muni.child_id     AND district.admin_unit_type = 'District' AND district.current_status = TRUE
WHERE muni.current_status = TRUE AND muni.admin_unit_type = 'Municipality'

UNION ALL

-- City → District
SELECT city.id, district.id, district.name
FROM dw.admin_units_dim city
JOIN dw.admin_units_dim district ON district.source_id = city.child_id     AND district.admin_unit_type = 'District' AND district.current_status = TRUE
WHERE city.current_status = TRUE AND city.admin_unit_type = 'City'

UNION ALL

-- District itself
SELECT id, id, name
FROM dw.admin_units_dim
WHERE admin_unit_type = 'District' AND current_status = TRUE;

CREATE INDEX ON tmp_unit_to_district (unit_dim_id);

DO $$ DECLARE v BIGINT;
BEGIN
    SELECT COUNT(*) INTO v FROM tmp_unit_to_district;
    RAISE NOTICE 'tmp_unit_to_district: % rows built', v;
END; $$;


-- ── Step 1b: Aggregate enrolment counts ──────────────────────────────────────
INSERT INTO stg.enrolment_indicator_raw (
    district_id, district_name, school_level, academic_year, gender,
    total_enrolment, official_age_enrolment,
    new_entrants_p1, new_entrants_p1_official_age,
    repeaters, learners_with_disability
)
SELECT
    pd.district_dim_id                              AS district_id,
    pd.district_name,
    sd.school_type                                  AS school_level,
    ef.academic_year,
    ld.gender,
    COUNT(ef.id)                                    AS total_enrolment,
    0                                               AS official_age_enrolment,
    COUNT(CASE
        WHEN (UPPER(gd.grade_name) LIKE '%P1%'
              OR UPPER(gd.grade_name) LIKE '%BABY%'
              OR UPPER(gd.grade_code) = 'P1')
             AND UPPER(etd.enrolment_type) IN ('BASELINE','NEW')
        THEN 1 ELSE NULL END)                       AS new_entrants_p1,
    0                                               AS new_entrants_p1_official_age,
    -- CONTINUING enrolment type is not the same as a repeater.
    -- True repeaters require is_repeating_yn from learner_enrolments source.
    -- That flag is not currently stored on enrolment_fact.
    -- Set to 0 to avoid inflated repetition rates until source is added.
    0                                               AS repeaters,
    COUNT(CASE
        WHEN ld.is_visual_yn = TRUE OR ld.is_hearing_yn = TRUE
          OR ld.is_walking_yn = TRUE OR ld.is_self_care_yn = TRUE
          OR ld.is_remembering_yn = TRUE OR ld.is_communication_yn = TRUE
        THEN 1 ELSE NULL END)                       AS learners_with_disability

FROM dw.enrolment_fact ef
JOIN dw.learner_dim ld
    ON ld.id = ef.learner_id AND ld.is_current = TRUE
JOIN dw.schools_dim sd
    ON sd.id = ef.school_id AND sd.is_current = TRUE
LEFT JOIN dw.grade_dim gd
    ON gd.id = ef.grade_id
LEFT JOIN dw.enrolment_type_dim etd
    ON etd.id = ef.enrolment_type_id
JOIN tmp_unit_to_district pd
    ON pd.unit_dim_id = sd.admin_unit_id
WHERE ef.academic_year >= 2022
  AND ld.gender IS NOT NULL
GROUP BY
    pd.district_dim_id, pd.district_name,
    sd.school_type, ef.academic_year, ld.gender;


-- ── Step 1c: Add TOTAL gender rows ───────────────────────────────────────────
INSERT INTO stg.enrolment_indicator_raw (
    district_id, district_name, school_level, academic_year, gender,
    total_enrolment, official_age_enrolment,
    new_entrants_p1, new_entrants_p1_official_age,
    repeaters, learners_with_disability
)
SELECT
    district_id, district_name, school_level, academic_year, 'TOTAL',
    SUM(total_enrolment), SUM(official_age_enrolment),
    SUM(new_entrants_p1), SUM(new_entrants_p1_official_age),
    SUM(repeaters), SUM(learners_with_disability)
FROM stg.enrolment_indicator_raw
WHERE UPPER(gender) IN ('M','F','MALE','FEMALE')
GROUP BY district_id, district_name, school_level, academic_year
ON CONFLICT (district_id, school_level, academic_year, gender) DO NOTHING;


-- ── Step 1d: Join population denominators ──────────────────────────────────
UPDATE stg.enrolment_indicator_raw eir
SET
    school_age_population = CASE
        WHEN eir.school_level ILIKE '%PRE%PRIMARY%'             THEN pf.pop_age_3_5
        WHEN eir.school_level ILIKE '%PRIMARY%'
             AND NOT eir.school_level ILIKE '%PRE%'             THEN pf.pop_age_6_12
        WHEN eir.school_level ILIKE '%SECONDARY%'               THEN pf.pop_age_13_16 + pf.pop_age_17_18
        ELSE NULL
    END,
    population_age_6 = pf.pop_age_6
FROM dw.population_fact pf,
     dw.admin_units_dim au
WHERE au.id          = eir.district_id
  AND pf.district_id = au.id
  AND pf.year        = eir.academic_year
  AND UPPER(pf.sex) = CASE
        WHEN UPPER(eir.gender) IN ('M','MALE')   THEN 'M'
        WHEN UPPER(eir.gender) IN ('F','FEMALE') THEN 'F'
        ELSE 'TOTAL'
    END;


-- ── Step 1e: Compute indicators ───────────────────────────────────────────────
UPDATE stg.enrolment_indicator_raw
SET
    ger = CASE
        WHEN school_age_population > 0
        THEN ROUND((total_enrolment::DECIMAL / school_age_population) * 100, 2)
        ELSE NULL END,
    ner = NULL,
    gir = CASE
        WHEN school_level ILIKE '%PRIMARY%'
             AND NOT school_level ILIKE '%PRE%'
             AND population_age_6 > 0
        THEN ROUND((new_entrants_p1::DECIMAL / population_age_6) * 100, 2)
        ELSE NULL END,
    repetition_rate = CASE
        WHEN total_enrolment > 0
        THEN ROUND((repeaters::DECIMAL / total_enrolment) * 100, 2)
        ELSE NULL END,
    sne_inclusion_rate = CASE
        WHEN total_enrolment > 0
        THEN ROUND((learners_with_disability::DECIMAL / total_enrolment) * 100, 2)
        ELSE NULL END;

DROP TABLE IF EXISTS tmp_unit_to_district;

DO $$ DECLARE v BIGINT;
BEGIN
    SELECT COUNT(*) INTO v FROM stg.enrolment_indicator_raw;
    RAISE NOTICE 'stg.enrolment_indicator_raw: % rows computed', v;
END; $$;

COMMIT;
