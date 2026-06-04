"""
EMIS Data Warehouse — Superset Dashboard Builder
Indicators Dashboard (GER, NER, PTR, GPI etc.)
"""

import requests, urllib3, getpass, json, uuid, sys
urllib3.disable_warnings()

SUPERSET_URL = "https://dw.emis4africa.com"
DB_NAME      = "demis_live"
session      = requests.Session()
session.verify = False

def login(username, password):
    r = session.post(f"{SUPERSET_URL}/api/v1/security/login", json={
        "username": username, "password": password, "provider": "db", "refresh": True})
    r.raise_for_status()
    session.headers.update({"Authorization": f"Bearer {r.json()['access_token']}", "Content-Type": "application/json"})
    csrf = session.get(f"{SUPERSET_URL}/api/v1/security/csrf_token/")
    csrf.raise_for_status()
    session.headers["X-CSRFToken"] = csrf.json()["result"]
    print("✅ Logged in successfully")

def get_database_id():
    r = session.get(f"{SUPERSET_URL}/api/v1/database/")
    r.raise_for_status()
    for db in r.json()["result"]:
        if DB_NAME.lower() in db["database_name"].lower():
            print(f"✅ Found database: {db['database_name']} (id={db['id']})")
            return db["id"]
    raise ValueError(f"Database '{DB_NAME}' not found")

def create_dataset(db_id, name, sql):
    r = session.get(f"{SUPERSET_URL}/api/v1/dataset/?q=(page_size:1000)")
    for ds in r.json().get("result", []):
        if ds.get("table_name") == name:
            ds_id = ds["id"]
            session.put(f"{SUPERSET_URL}/api/v1/dataset/{ds_id}", json={"sql": sql})
            print(f"  ♻️  Updated '{name}' (id={ds_id})")
            return ds_id
    r = session.post(f"{SUPERSET_URL}/api/v1/dataset/", json={"database": db_id, "schema": "dw", "table_name": name, "sql": sql})
    r.raise_for_status()
    ds_id = r.json()["id"]
    print(f"  ✅ Created '{name}' (id={ds_id})")
    return ds_id

def m(col):
    return {"expressionType": "SIMPLE", "column": {"column_name": col}, "aggregate": "MAX", "label": col}

def m_avg(col):
    return {"expressionType": "SIMPLE", "column": {"column_name": col}, "aggregate": "AVG", "label": col}

def m_sum(col):
    return {"expressionType": "SIMPLE", "column": {"column_name": col}, "aggregate": "SUM", "label": col}

def create_chart(name, viz_type, ds_id, params):
    r = session.post(f"{SUPERSET_URL}/api/v1/chart/", json={
        "slice_name": name, "viz_type": viz_type,
        "datasource_id": ds_id, "datasource_type": "table",
        "params": json.dumps(params), "query_context": json.dumps({})})
    if r.status_code in (200, 201):
        cid = r.json().get("id")
        print(f"  ✅ Created chart '{name}' (id={cid})")
        return cid
    print(f"  ⚠️  Chart '{name}' — {r.status_code}: {r.text[:150]}")
    return None

def create_dashboard(title, chart_ids, markdown_text):
    r = session.post(f"{SUPERSET_URL}/api/v1/dashboard/", json={
        "dashboard_title": title, "published": False, "position_json": "{}"})
    if r.status_code not in (200, 201):
        print(f"  ⚠️  Dashboard — {r.status_code}: {r.text[:300]}")
        return None
    dash_id = r.json().get("id") or r.json().get("result", {}).get("id")
    print(f"\n✅ Dashboard '{title}' created (id={dash_id})")

    valid_ids = [cid for cid in chart_ids if cid is not None]
    md_row_id = f"ROW-{str(uuid.uuid4())[:8]}"
    md_col_id = f"COLUMN-{str(uuid.uuid4())[:8]}"
    md_id     = f"MARKDOWN-{str(uuid.uuid4())[:8]}"
    position  = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
        md_row_id: {"type": "ROW", "id": md_row_id, "children": [md_col_id], "parents": ["GRID_ID", "ROOT_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}},
        md_col_id: {"type": "COLUMN", "id": md_col_id, "children": [md_id], "parents": [md_row_id, "GRID_ID", "ROOT_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT", "width": 12}},
        md_id:     {"type": "MARKDOWN", "id": md_id, "children": [], "parents": [md_col_id, md_row_id, "GRID_ID", "ROOT_ID"], "meta": {"width": 12, "height": 14, "code": markdown_text}},
    }
    rows = [md_row_id]
    for i in range(0, len(valid_ids), 3):
        row_charts = valid_ids[i:i+3]
        row_id = f"ROW-{str(uuid.uuid4())[:8]}"
        cols = []
        for j, cid in enumerate(row_charts):
            col_id    = f"COLUMN-{str(uuid.uuid4())[:8]}"
            chart_key = f"CHART-{str(uuid.uuid4())[:8]}"
            position[col_id]    = {"type": "COLUMN", "id": col_id, "children": [chart_key], "parents": [row_id, "GRID_ID", "ROOT_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT", "width": 4}}
            position[chart_key] = {"type": "CHART", "id": chart_key, "children": [], "parents": [col_id, row_id, "GRID_ID", "ROOT_ID"], "meta": {"chartId": cid, "width": 4, "height": 50, "sliceName": f"Chart {cid}"}}
            cols.append(col_id)
        position[row_id] = {"type": "ROW", "id": row_id, "children": cols, "parents": ["GRID_ID", "ROOT_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        rows.append(row_id)
    position["GRID_ID"]["children"] = rows

    r2 = session.put(f"{SUPERSET_URL}/api/v1/dashboard/{dash_id}", json={"position_json": json.dumps(position)})
    if r2.status_code in (200, 201):
        print(f"✅ Charts and Markdown attached successfully")
    else:
        print(f"  ⚠️  Attachment — {r2.status_code}: {r2.text[:300]}")
    return dash_id

# ── SQL Queries ────────────────────────────────────────────────
DATASETS = {

    "indicators_kpi_avg_ptr": """
SELECT ROUND(AVG(ptr), 1) AS national_avg_ptr
FROM dw.school_indicator_fact
WHERE ptr > 0 AND ptr < 200""",

    "indicators_kpi_avg_qualified_ratio": """
SELECT ROUND(AVG(qualified_teacher_ratio), 1) AS avg_qualified_ratio
FROM dw.school_indicator_fact
WHERE qualified_teacher_ratio > 0""",

    "indicators_kpi_avg_pct_female_teachers": """
SELECT ROUND(AVG(pct_female_teachers), 1) AS avg_pct_female_teachers
FROM dw.school_indicator_fact
WHERE pct_female_teachers >= 0""",

    "indicators_kpi_schools_with_data": """
SELECT COUNT(DISTINCT school_id) AS schools_with_indicators
FROM dw.school_indicator_fact""",

    "indicators_kpi_total_enrolment": """
SELECT SUM(total_enrolment) AS total_enrolment
FROM dw.enrolment_indicator_fact
WHERE gender = 'TOTAL'
  AND academic_year = (SELECT MAX(academic_year) FROM dw.enrolment_indicator_fact)""",

    "indicators_kpi_districts_with_data": """
SELECT COUNT(DISTINCT district_id) AS districts_with_indicators
FROM dw.enrolment_indicator_fact""",

    "indicators_ptr_by_district": """
SELECT
    m.district_name                     AS "District",
    ROUND(AVG(sif.ptr), 1)             AS "Avg PTR",
    ROUND(AVG(sif.qualified_teacher_ratio), 1) AS "% Qualified Teachers",
    ROUND(AVG(sif.pct_female_teachers), 1)     AS "% Female Teachers",
    COUNT(DISTINCT sif.school_id)      AS "Schools"
FROM dw.school_indicator_fact sif
JOIN dw.school_district_map m ON m.school_dim_id = sif.school_id
WHERE sif.ptr > 0 AND sif.ptr < 200
GROUP BY m.district_name
ORDER BY "Avg PTR" DESC
LIMIT 20""",

    "indicators_ptr_distribution": """
SELECT
    CASE
        WHEN ptr <= 20  THEN '0-20 (Very Low)'
        WHEN ptr <= 40  THEN '21-40 (Low)'
        WHEN ptr <= 53  THEN '41-53 (Acceptable)'
        WHEN ptr <= 70  THEN '54-70 (High)'
        WHEN ptr <= 100 THEN '71-100 (Very High)'
        ELSE '100+ (Critical)'
    END AS ptr_range,
    COUNT(*) AS schools
FROM dw.school_indicator_fact
WHERE ptr > 0 AND ptr < 500
GROUP BY 1
ORDER BY MIN(ptr)""",

    "indicators_enrolment_by_level_gender": """
SELECT
    UPPER(TRIM(school_level))           AS school_level,
    gender,
    SUM(total_enrolment)                AS total_enrolment,
    academic_year
FROM dw.enrolment_indicator_fact
WHERE gender IN ('M', 'F')
  AND school_level IS NOT NULL
  AND academic_year = (SELECT MAX(academic_year) FROM dw.enrolment_indicator_fact)
GROUP BY school_level, gender, academic_year
ORDER BY school_level, gender""",

    "indicators_gpi_by_district": """
SELECT
    au.name                             AS "District",
    eif.school_level                    AS "School Level",
    ROUND(AVG(eif.gpi_ger), 2)         AS "GPI (GER)",
    ROUND(AVG(eif.gpi_ner), 2)         AS "GPI (NER)",
    SUM(eif.total_enrolment)           AS "Total Enrolment"
FROM dw.enrolment_indicator_fact eif
JOIN dw.admin_units_dim au ON au.id = eif.district_id
WHERE eif.gender = 'TOTAL'
  AND eif.school_level IS NOT NULL
  AND au.admin_unit_type = 'District'
GROUP BY au.name, eif.school_level
ORDER BY "GPI (GER)" ASC NULLS LAST
LIMIT 30""",

    "indicators_qualified_teacher_by_district": """
SELECT
    m.district_name                              AS district_name,
    ROUND(AVG(sif.qualified_teacher_ratio), 1)  AS avg_qualified_ratio
FROM dw.school_indicator_fact sif
JOIN dw.school_district_map m ON m.school_dim_id = sif.school_id
WHERE sif.qualified_teacher_ratio >= 0
GROUP BY m.district_name
ORDER BY avg_qualified_ratio ASC
LIMIT 20""",

    "indicators_female_teachers_by_district": """
SELECT
    m.district_name                              AS district_name,
    ROUND(AVG(sif.pct_female_teachers), 1)      AS avg_pct_female_teachers
FROM dw.school_indicator_fact sif
JOIN dw.school_district_map m ON m.school_dim_id = sif.school_id
WHERE sif.pct_female_teachers >= 0
GROUP BY m.district_name
ORDER BY avg_pct_female_teachers ASC
LIMIT 20""",

    "indicators_enrolment_trend": """
SELECT
    academic_year,
    UPPER(TRIM(school_level))       AS school_level,
    SUM(total_enrolment)            AS total_enrolment
FROM dw.enrolment_indicator_fact
WHERE gender = 'TOTAL'
  AND school_level IS NOT NULL
GROUP BY academic_year, school_level
ORDER BY academic_year, school_level""",

    "indicators_sne_by_district": """
SELECT
    au.name                             AS "District",
    SUM(eif.learners_with_disability)  AS "SNE Learners",
    SUM(eif.total_enrolment)           AS "Total Enrolment",
    ROUND(
        SUM(eif.learners_with_disability)::DECIMAL /
        NULLIF(SUM(eif.total_enrolment), 0) * 100
    , 2)                                AS "SNE Inclusion Rate %"
FROM dw.enrolment_indicator_fact eif
JOIN dw.admin_units_dim au ON au.id = eif.district_id
WHERE eif.gender = 'TOTAL'
  AND au.admin_unit_type = 'District'
GROUP BY au.name
ORDER BY "SNE Learners" DESC
LIMIT 15""",

    "indicators_ptr_over_time": """
SELECT
    academic_year,
    term,
    CONCAT('FY', academic_year, ' ', term) AS period,
    ROUND(AVG(ptr), 1)                     AS avg_ptr,
    ROUND(AVG(qualified_teacher_ratio), 1) AS avg_qualified_ratio,
    ROUND(AVG(pct_female_teachers), 1)     AS avg_pct_female
FROM dw.school_indicator_fact
WHERE ptr > 0 AND ptr < 200
GROUP BY academic_year, term
ORDER BY academic_year, term""",
}

# ── Chart definitions ──────────────────────────────────────────
def get_chart_defs(ds_ids):
    return [
        # KPIs
        ("National Average PTR",            "big_number_total", ds_ids["indicators_kpi_avg_ptr"],                {"metric": m("national_avg_ptr"),           "subheader": "National Avg Pupil-Teacher Ratio"}),
        ("% Qualified Teachers",            "big_number_total", ds_ids["indicators_kpi_avg_qualified_ratio"],    {"metric": m("avg_qualified_ratio"),         "subheader": "Avg % Qualified Teachers"}),
        ("% Female Teachers",               "big_number_total", ds_ids["indicators_kpi_avg_pct_female_teachers"],{"metric": m("avg_pct_female_teachers"),     "subheader": "Avg % Female Teachers"}),
        ("Schools with Indicator Data",     "big_number_total", ds_ids["indicators_kpi_schools_with_data"],      {"metric": m("schools_with_indicators"),     "subheader": "Schools with Indicator Data"}),
        ("Total Enrolment (Latest Year)",   "big_number_total", ds_ids["indicators_kpi_total_enrolment"],        {"metric": m_sum("total_enrolment"),         "subheader": "Total Enrolment Latest Year"}),
        ("Districts with Indicator Data",   "big_number_total", ds_ids["indicators_kpi_districts_with_data"],    {"metric": m("districts_with_indicators"),   "subheader": "Districts with Data"}),
        # PTR distribution pie
        ("PTR Distribution by Range",       "pie",  ds_ids["indicators_ptr_distribution"],          {"groupby": ["ptr_range"], "metric": m_sum("schools"), "show_labels": True, "show_legend": True, "label_type": "key_percent", "row_limit": 10}),
        # Enrolment by level and gender bar
        ("Enrolment by School Level and Gender", "bar", ds_ids["indicators_enrolment_by_level_gender"], {"metrics": [m_sum("total_enrolment")], "columns": ["gender"], "groupby": ["school_level"], "row_limit": 50, "show_legend": True}),
        # PTR over time bar
        ("PTR Trend Over Time",             "bar",  ds_ids["indicators_ptr_over_time"],              {"metrics": [m_avg("avg_ptr")], "columns": [], "groupby": ["period"], "row_limit": 50, "show_legend": True}),
        # Enrolment trend bar
        ("Enrolment Trend by School Level", "bar",  ds_ids["indicators_enrolment_trend"],            {"metrics": [m_sum("total_enrolment")], "columns": ["school_level"], "groupby": ["academic_year"], "row_limit": 50, "show_legend": True}),
        # Bottom districts by qualified teacher ratio
        ("Bottom 20 Districts by Qualified Teacher Ratio", "bar", ds_ids["indicators_qualified_teacher_by_district"], {"metrics": [m_avg("avg_qualified_ratio")], "columns": [], "groupby": ["district_name"], "row_limit": 20, "show_legend": True}),
        # Bottom districts by female teachers
        ("Bottom 20 Districts by % Female Teachers", "bar", ds_ids["indicators_female_teachers_by_district"], {"metrics": [m_avg("avg_pct_female_teachers")], "columns": [], "groupby": ["district_name"], "row_limit": 20, "show_legend": True}),
        # Tables
        ("PTR by District",                 "table", ds_ids["indicators_ptr_by_district"],           {"groupby": ["District", "Avg PTR", "% Qualified Teachers", "% Female Teachers", "Schools"], "show_cell_bars": True, "page_length": 20}),
        ("Gender Parity Index by District", "table", ds_ids["indicators_gpi_by_district"],           {"groupby": ["District", "School Level", "GPI (GER)", "GPI (NER)", "Total Enrolment"], "show_cell_bars": True, "page_length": 20}),
        ("SNE Inclusion by District",       "table", ds_ids["indicators_sne_by_district"],           {"groupby": ["District", "SNE Learners", "Total Enrolment", "SNE Inclusion Rate %"], "show_cell_bars": True, "page_length": 20}),
    ]

# ── Markdown ───────────────────────────────────────────────────
MARKDOWN = (
    "# EMIS Education Indicators Overview\n\n"
    "**Key education quality and equity indicators including PTR, GER, NER, GPI, and SNE inclusion rates.**\n\n"
    "---\n\n"
    "### Primary Audience\n"
    "- Commissioner Planning / Statistics\n"
    "- MoES Senior Management\n"
    "- District Education Officers (DEOs)\n"
    "- Gender and Equity Officers\n"
    "- Development Partners and Researchers\n\n"
    "### Primary Questions Answered\n"
    "- What is the national Pupil-Teacher Ratio and how does it vary by district?\n"
    "- What proportion of teachers are qualified?\n"
    "- How is gender parity in enrolment measured across school levels?\n"
    "- Which districts have the lowest female teacher percentages?\n"
    "- How many learners with disabilities are included in mainstream education?\n"
    "- How are key indicators changing over time?\n\n"
    "### Note on Data Coverage\n"
    "GER and NER indicators are computed only for districts where UBOS population data has been loaded. "
    "PTR indicators are computed for all schools reporting both teacher and enrolment data in EMIS."
)

# ── Main ───────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("EMIS DW — Indicators Dashboard Builder")
    print("=" * 60)

    username = input("Superset username: ")
    password = getpass.getpass("Superset password: ")

    try:
        login(username, password)
        db_id = get_database_id()

        print("\nCreating datasets...")
        ds_ids = {}
        for name, sql in DATASETS.items():
            ds_ids[name] = create_dataset(db_id, name, sql)

        print("\nCreating charts...")
        chart_ids = []
        for name, viz_type, ds_id, params in get_chart_defs(ds_ids):
            chart_ids.append(create_chart(name, viz_type, ds_id, params))

        print("\nCreating dashboard...")
        create_dashboard("EMIS Education Indicators Overview", chart_ids, MARKDOWN)

        print("\n" + "=" * 60)
        created = sum(1 for c in chart_ids if c is not None)
        print(f"✅ Done! {created}/{len(chart_ids)} charts created")
        print(f"   Visit: {SUPERSET_URL}/dashboard/list/")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
