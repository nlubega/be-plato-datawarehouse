"""
EMIS Data Warehouse — Superset Dashboard Builder
Teaching Subjects Dashboard
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

def m_sum(col):
    return {"expressionType": "SIMPLE", "column": {"column_name": col}, "aggregate": "SUM", "label": col}

def m_cntd(col):
    return {"expressionType": "SIMPLE", "column": {"column_name": col}, "aggregate": "COUNT_DISTINCT", "label": col}

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

    "subjects_kpi_total_assignments": """
SELECT COUNT(*) AS total_assignments
FROM dw.teaching_subject_fact""",

    "subjects_kpi_teachers_with_subjects": """
SELECT COUNT(DISTINCT teacher_id) AS teachers_with_subjects
FROM dw.teaching_subject_fact""",

    "subjects_kpi_total_subjects": """
SELECT COUNT(DISTINCT subject_id) AS total_subjects
FROM dw.teaching_subject_fact""",

    "subjects_kpi_science_teachers": """
SELECT COUNT(DISTINCT tsf.teacher_id) AS science_teachers
FROM dw.teaching_subject_fact tsf
JOIN dw.subject_dim sd ON sd.id = tsf.subject_id
WHERE sd.is_science_subject = TRUE""",

    "subjects_kpi_arts_teachers": """
SELECT COUNT(DISTINCT tsf.teacher_id) AS arts_teachers
FROM dw.teaching_subject_fact tsf
JOIN dw.subject_dim sd ON sd.id = tsf.subject_id
WHERE sd.is_science_subject = FALSE""",

    "subjects_kpi_pct_science": """
SELECT ROUND(
    COUNT(DISTINCT CASE WHEN sd.is_science_subject = TRUE THEN tsf.teacher_id END)::DECIMAL /
    NULLIF(COUNT(DISTINCT tsf.teacher_id), 0) * 100
, 1) AS pct_science_teachers
FROM dw.teaching_subject_fact tsf
JOIN dw.subject_dim sd ON sd.id = tsf.subject_id""",

    "subjects_by_category": """
SELECT
    COALESCE(sd.subject_category, 'Unknown') AS subject_category,
    COUNT(DISTINCT tsf.teacher_id)            AS total_teachers,
    COUNT(DISTINCT tsf.subject_id)            AS total_subjects
FROM dw.teaching_subject_fact tsf
JOIN dw.subject_dim sd ON sd.id = tsf.subject_id
GROUP BY sd.subject_category
ORDER BY total_teachers DESC""",

    "subjects_by_level": """
SELECT
    COALESCE(sd.subject_level, 'Unknown') AS subject_level,
    COUNT(DISTINCT tsf.teacher_id)         AS total_teachers,
    COUNT(DISTINCT tsf.subject_id)         AS total_subjects
FROM dw.teaching_subject_fact tsf
JOIN dw.subject_dim sd ON sd.id = tsf.subject_id
GROUP BY sd.subject_level
ORDER BY total_teachers DESC""",

    "subjects_top20_by_teachers": """
SELECT
    sd.subject_name                        AS subject_name,
    sd.subject_category                    AS category,
    sd.subject_level                       AS level,
    COUNT(DISTINCT tsf.teacher_id)         AS total_teachers
FROM dw.teaching_subject_fact tsf
JOIN dw.subject_dim sd ON sd.id = tsf.subject_id
GROUP BY sd.subject_name, sd.subject_category, sd.subject_level
ORDER BY total_teachers DESC
LIMIT 20""",

    "subjects_science_vs_arts_by_district": """
SELECT
    m.district_name                                                             AS district_name,
    COUNT(DISTINCT CASE WHEN sd.is_science_subject = TRUE
          THEN tsf.teacher_id END)                                             AS science_teachers,
    COUNT(DISTINCT CASE WHEN sd.is_science_subject = FALSE
          THEN tsf.teacher_id END)                                             AS arts_teachers,
    COUNT(DISTINCT tsf.teacher_id)                                             AS total_teachers,
    ROUND(COUNT(DISTINCT CASE WHEN sd.is_science_subject = TRUE
          THEN tsf.teacher_id END)::DECIMAL /
        NULLIF(COUNT(DISTINCT tsf.teacher_id), 0) * 100, 1)                   AS pct_science
FROM dw.teaching_subject_fact tsf
JOIN dw.subject_dim sd        ON sd.id = tsf.subject_id
JOIN dw.school_district_map m ON m.school_dim_id = tsf.school_id
GROUP BY m.district_name
ORDER BY pct_science ASC
LIMIT 20""",

    "subjects_olevel_alevel_split": """
SELECT
    CASE
        WHEN sd.is_olevel_subject = TRUE AND sd.is_alevel_subject = TRUE  THEN 'Both O and A Level'
        WHEN sd.is_olevel_subject = TRUE AND sd.is_alevel_subject = FALSE THEN 'O Level Only'
        WHEN sd.is_olevel_subject = FALSE AND sd.is_alevel_subject = TRUE THEN 'A Level Only'
        ELSE 'Primary'
    END                                                AS level_type,
    COUNT(DISTINCT tsf.teacher_id)                    AS total_teachers
FROM dw.teaching_subject_fact tsf
JOIN dw.subject_dim sd ON sd.id = tsf.subject_id
GROUP BY 1
ORDER BY total_teachers DESC""",

    "subjects_lab_subjects": """
SELECT
    sd.subject_name                        AS subject_name,
    sd.subject_category                    AS category,
    COUNT(DISTINCT tsf.teacher_id)         AS total_teachers
FROM dw.teaching_subject_fact tsf
JOIN dw.subject_dim sd ON sd.id = tsf.subject_id
WHERE sd.has_lab_yn = TRUE
GROUP BY sd.subject_name, sd.subject_category
ORDER BY total_teachers DESC""",

    "subjects_full_leaderboard": """
SELECT
    sd.subject_name                        AS "Subject",
    sd.subject_level                       AS "Level",
    sd.subject_category                    AS "Category",
    CASE WHEN sd.is_science_subject THEN 'Yes' ELSE 'No' END AS "Science",
    CASE WHEN sd.has_lab_yn THEN 'Yes' ELSE 'No' END         AS "Lab Required",
    CASE WHEN sd.is_mandatory THEN 'Yes' ELSE 'No' END       AS "Mandatory",
    CASE WHEN sd.is_examinable THEN 'Yes' ELSE 'No' END      AS "Examinable",
    COUNT(DISTINCT tsf.teacher_id)         AS "Teachers"
FROM dw.teaching_subject_fact tsf
JOIN dw.subject_dim sd ON sd.id = tsf.subject_id
GROUP BY sd.subject_name, sd.subject_level, sd.subject_category,
         sd.is_science_subject, sd.has_lab_yn, sd.is_mandatory, sd.is_examinable
ORDER BY "Teachers" DESC""",
}

# ── Chart definitions ──────────────────────────────────────────
def get_chart_defs(ds_ids):
    return [
        # KPIs
        ("Total Subject Assignments",       "big_number_total", ds_ids["subjects_kpi_total_assignments"],        {"metric": m("total_assignments"),       "subheader": "Teacher-Subject Assignments"}),
        ("Teachers with Subjects",          "big_number_total", ds_ids["subjects_kpi_teachers_with_subjects"],   {"metric": m("teachers_with_subjects"),  "subheader": "Teachers with Subject Data"}),
        ("Total Subjects",                  "big_number_total", ds_ids["subjects_kpi_total_subjects"],           {"metric": m("total_subjects"),          "subheader": "Total Subjects"}),
        ("Science Teachers",                "big_number_total", ds_ids["subjects_kpi_science_teachers"],         {"metric": m("science_teachers"),        "subheader": "Science Teachers"}),
        ("Arts Teachers",                   "big_number_total", ds_ids["subjects_kpi_arts_teachers"],            {"metric": m("arts_teachers"),           "subheader": "Arts Teachers"}),
        ("% Science Teachers",              "big_number_total", ds_ids["subjects_kpi_pct_science"],              {"metric": m("pct_science_teachers"),    "subheader": "% Science Teachers", "y_axis_format": ".1f"}),
        # Pies
        ("Teachers by Subject Category",    "pie", ds_ids["subjects_by_category"],         {"groupby": ["subject_category"], "metric": m_sum("total_teachers"), "show_labels": True, "show_legend": True, "label_type": "key_percent", "row_limit": 10}),
        ("Teachers by Subject Level",       "pie", ds_ids["subjects_by_level"],            {"groupby": ["subject_level"],    "metric": m_sum("total_teachers"), "show_labels": True, "show_legend": True, "label_type": "key_percent", "row_limit": 10}),
        ("Teachers by O/A Level Split",     "pie", ds_ids["subjects_olevel_alevel_split"], {"groupby": ["level_type"],       "metric": m_sum("total_teachers"), "show_labels": True, "show_legend": True, "label_type": "key_percent", "row_limit": 10}),
        # Bars
        ("Top 20 Subjects by Teachers",     "bar", ds_ids["subjects_top20_by_teachers"],              {"metrics": [m_sum("total_teachers")], "columns": [], "groupby": ["subject_name"],   "row_limit": 20, "show_legend": True}),
        ("Bottom 20 Districts - % Science", "bar", ds_ids["subjects_science_vs_arts_by_district"],    {"metrics": [m_sum("science_teachers"), m_sum("arts_teachers")], "columns": [], "groupby": ["district_name"], "row_limit": 20, "show_legend": True}),
        ("Lab Subjects by Teachers",        "bar", ds_ids["subjects_lab_subjects"],                   {"metrics": [m_sum("total_teachers")], "columns": [], "groupby": ["subject_name"],   "row_limit": 20, "show_legend": True}),
        # Table
        ("Subject Leaderboard",             "table", ds_ids["subjects_full_leaderboard"], {"groupby": ["Subject", "Level", "Category", "Science", "Lab Required", "Mandatory", "Examinable", "Teachers"], "show_cell_bars": True, "page_length": 30}),
    ]

# ── Markdown ───────────────────────────────────────────────────
MARKDOWN = (
    "# EMIS Teaching Subjects Overview\n\n"
    "**Teaching subject assignments by discipline, school level, science vs arts split, and district.**\n\n"
    "---\n\n"
    "### Primary Audience\n"
    "- Commissioner Planning / Statistics\n"
    "- MoES Senior Management\n"
    "- Curriculum Development Specialists\n"
    "- District Education Officers (DEOs)\n\n"
    "### Primary Questions Answered\n"
    "- How many teachers are teaching Science vs Arts subjects?\n"
    "- Which subjects have the most teachers nationally?\n"
    "- Which districts have the lowest Science teacher percentages?\n"
    "- How many teachers are assigned to lab-based subjects?\n"
    "- What is the split between O Level, A Level and Primary subjects?\n\n"
    "### Note on Coverage\n"
    "Subject data is captured for 66,000 out of 272,219 teachers (24%). "
    "The remaining 76% have not yet had subject assignments recorded in EMIS. "
    "As data capture improves this dashboard will become more comprehensive."
)

# ── Main ───────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("EMIS DW — Teaching Subjects Dashboard Builder")
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
        create_dashboard("EMIS Teaching Subjects Overview", chart_ids, MARKDOWN)

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
