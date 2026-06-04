"""
EMIS Data Warehouse — Superset Dashboard Builder
Infrastructure Dashboard
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

    "infra_kpi_total_records": """
SELECT COUNT(*) AS total_records
FROM dw.infrastructure_fact""",

    "infra_kpi_schools": """
SELECT COUNT(DISTINCT school_id) AS schools_with_data
FROM dw.infrastructure_fact""",

    "infra_kpi_total_structures": """
SELECT SUM(total_number) AS total_structures
FROM dw.infrastructure_fact
WHERE total_number > 0""",

    "infra_kpi_complete": """
SELECT SUM(total_number) AS complete_structures
FROM dw.infrastructure_fact
WHERE UPPER(completion_status) = 'COMPLETE'
  AND total_number > 0""",

    "infra_kpi_permanent": """
SELECT SUM(total_number) AS permanent_structures
FROM dw.infrastructure_fact
WHERE UPPER(usage_mode) = 'PERMANENT'
  AND total_number > 0""",

    "infra_kpi_pct_complete": """
SELECT ROUND(
    SUM(CASE WHEN UPPER(completion_status) = 'COMPLETE' THEN total_number ELSE 0 END)::DECIMAL /
    NULLIF(SUM(total_number), 0) * 100
, 1) AS pct_complete
FROM dw.infrastructure_fact
WHERE total_number > 0""",

    "infra_by_completion_status": """
SELECT
    COALESCE(UPPER(completion_status), 'Unknown') AS completion_status,
    SUM(total_number)                              AS total_structures
FROM dw.infrastructure_fact
WHERE total_number > 0
GROUP BY completion_status
ORDER BY total_structures DESC""",

    "infra_by_usage_mode": """
SELECT
    COALESCE(UPPER(usage_mode), 'Unknown') AS usage_mode,
    SUM(total_number)                       AS total_structures
FROM dw.infrastructure_fact
WHERE total_number > 0
GROUP BY usage_mode
ORDER BY total_structures DESC""",

    "infra_by_structure_condition": """
SELECT
    COALESCE(UPPER(structure_condition), 'Not Recorded') AS structure_condition,
    SUM(total_number)                                     AS total_structures
FROM dw.infrastructure_fact
WHERE total_number > 0
GROUP BY structure_condition
ORDER BY total_structures DESC""",

    "infra_by_type": """
SELECT
    itd.type_name                           AS structure_type,
    SUM(inf.total_number)                   AS total_structures,
    COUNT(DISTINCT inf.school_id)           AS schools
FROM dw.infrastructure_fact inf
JOIN dw.infrastructure_type_dim itd ON itd.id = inf.infra_type_id
WHERE inf.total_number > 0
GROUP BY itd.type_name
ORDER BY total_structures DESC""",

    "infra_classrooms_by_district": """
SELECT
    m.district_name                         AS "District",
    SUM(inf.total_number)                   AS "Total Classrooms",
    COUNT(DISTINCT inf.school_id)           AS "Schools",
    ROUND(SUM(inf.total_number)::DECIMAL /
        NULLIF(COUNT(DISTINCT inf.school_id), 0), 1) AS "Avg Classrooms per School"
FROM dw.infrastructure_fact inf
JOIN dw.infrastructure_type_dim itd ON itd.id = inf.infra_type_id
JOIN dw.school_district_map m       ON m.school_dim_id = inf.school_id
WHERE itd.type_name ILIKE '%Classroom%'
  AND inf.total_number > 0
GROUP BY m.district_name
ORDER BY "Total Classrooms" DESC
LIMIT 20""",

    "infra_latrines_by_district": """
SELECT
    m.district_name                         AS "District",
    SUM(inf.total_number)                   AS "Total Latrine Stances",
    COUNT(DISTINCT inf.school_id)           AS "Schools",
    ROUND(SUM(inf.total_number)::DECIMAL /
        NULLIF(COUNT(DISTINCT inf.school_id), 0), 1) AS "Avg Stances per School"
FROM dw.infrastructure_fact inf
JOIN dw.infrastructure_type_dim itd ON itd.id = inf.infra_type_id
JOIN dw.school_district_map m       ON m.school_dim_id = inf.school_id
WHERE itd.type_name ILIKE '%Latrine%'
  AND inf.total_number > 0
GROUP BY m.district_name
ORDER BY "Total Latrine Stances" DESC
LIMIT 20""",

    "infra_labs_by_district": """
SELECT
    m.district_name                         AS "District",
    SUM(inf.total_number)                   AS "Total Labs",
    COUNT(DISTINCT inf.school_id)           AS "Schools with Labs"
FROM dw.infrastructure_fact inf
JOIN dw.infrastructure_type_dim itd ON itd.id = inf.infra_type_id
JOIN dw.school_district_map m       ON m.school_dim_id = inf.school_id
WHERE (itd.type_name ILIKE '%Lab%' OR itd.type_name ILIKE '%Science%')
  AND inf.total_number > 0
GROUP BY m.district_name
ORDER BY "Total Labs" DESC
LIMIT 20""",

    "infra_top15_districts": """
SELECT
    m.district_name                         AS district_name,
    COUNT(DISTINCT inf.school_id)           AS schools_with_infra_data,
    SUM(inf.total_number)                   AS total_structures
FROM dw.infrastructure_fact inf
JOIN dw.school_district_map m ON m.school_dim_id = inf.school_id
WHERE inf.total_number > 0
GROUP BY m.district_name
ORDER BY total_structures DESC
LIMIT 15""",

    "infra_full_leaderboard": """
SELECT
    m.district_name                                                         AS "District",
    COUNT(DISTINCT inf.school_id)                                          AS "Schools",
    SUM(CASE WHEN itd.type_name ILIKE '%Classroom%'
             THEN inf.total_number ELSE 0 END)                             AS "Classrooms",
    SUM(CASE WHEN itd.type_name ILIKE '%Latrine%'
             THEN inf.total_number ELSE 0 END)                             AS "Latrines",
    SUM(CASE WHEN itd.type_name ILIKE '%Lab%' OR itd.type_name ILIKE '%Science%'
             THEN inf.total_number ELSE 0 END)                             AS "Labs",
    SUM(CASE WHEN itd.type_name ILIKE '%Library%'
             THEN inf.total_number ELSE 0 END)                             AS "Libraries",
    SUM(CASE WHEN itd.type_name ILIKE '%Computer%'
             THEN inf.total_number ELSE 0 END)                             AS "Computer Labs",
    SUM(inf.total_number)                                                  AS "Total Structures"
FROM dw.infrastructure_fact inf
JOIN dw.infrastructure_type_dim itd ON itd.id = inf.infra_type_id
JOIN dw.school_district_map m       ON m.school_dim_id = inf.school_id
WHERE inf.total_number > 0
GROUP BY m.district_name
ORDER BY "Total Structures" DESC""",
}

# ── Chart definitions ──────────────────────────────────────────
def get_chart_defs(ds_ids):
    return [
        # KPIs
        ("Total Infrastructure Records",    "big_number_total", ds_ids["infra_kpi_total_records"],   {"metric": m("total_records"),       "subheader": "Infrastructure Records"}),
        ("Schools with Infrastructure Data","big_number_total", ds_ids["infra_kpi_schools"],         {"metric": m("schools_with_data"),   "subheader": "Schools Reporting"}),
        ("Total Structures",                "big_number_total", ds_ids["infra_kpi_total_structures"], {"metric": m_sum("total_structures"),"subheader": "Total Structures"}),
        ("Complete Structures",             "big_number_total", ds_ids["infra_kpi_complete"],         {"metric": m_sum("complete_structures"), "subheader": "Complete Structures"}),
        ("Permanent Structures",            "big_number_total", ds_ids["infra_kpi_permanent"],        {"metric": m_sum("permanent_structures"), "subheader": "Permanent Structures"}),
        ("% Complete Structures",           "big_number_total", ds_ids["infra_kpi_pct_complete"],     {"metric": m("pct_complete"),        "subheader": "% Complete", "y_axis_format": ".1f"}),
        # Pies
        ("Structures by Completion Status", "pie", ds_ids["infra_by_completion_status"],   {"groupby": ["completion_status"], "metric": m_sum("total_structures"), "show_labels": True, "show_legend": True, "label_type": "key_percent", "row_limit": 10}),
        ("Structures by Usage Mode",        "pie", ds_ids["infra_by_usage_mode"],          {"groupby": ["usage_mode"],        "metric": m_sum("total_structures"), "show_labels": True, "show_legend": True, "label_type": "key_percent", "row_limit": 10}),
        ("Structures by Condition",         "pie", ds_ids["infra_by_structure_condition"], {"groupby": ["structure_condition"],"metric": m_sum("total_structures"), "show_labels": True, "show_legend": True, "label_type": "key_percent", "row_limit": 10}),
        # Bars
        ("Structures by Type",              "bar", ds_ids["infra_by_type"],             {"metrics": [m_sum("total_structures")], "columns": [], "groupby": ["structure_type"], "row_limit": 25, "show_legend": True}),
        ("Top 15 Districts by Structures",  "bar", ds_ids["infra_top15_districts"],     {"metrics": [m_sum("total_structures")], "columns": [], "groupby": ["district_name"],  "row_limit": 15, "show_legend": True}),
        ("Labs by District (Top 20)",       "bar", ds_ids["infra_labs_by_district"],    {"metrics": [m_sum("Total Labs")],       "columns": [], "groupby": ["District"],       "row_limit": 20, "show_legend": True}),
        # Tables
        ("Classrooms by District",          "table", ds_ids["infra_classrooms_by_district"], {"groupby": ["District", "Total Classrooms", "Schools", "Avg Classrooms per School"], "show_cell_bars": True, "page_length": 20}),
        ("Latrines by District",            "table", ds_ids["infra_latrines_by_district"],   {"groupby": ["District", "Total Latrine Stances", "Schools", "Avg Stances per School"], "show_cell_bars": True, "page_length": 20}),
        ("Infrastructure District Leaderboard", "table", ds_ids["infra_full_leaderboard"],   {"groupby": ["District", "Schools", "Classrooms", "Latrines", "Labs", "Libraries", "Computer Labs", "Total Structures"], "show_cell_bars": True, "page_length": 20}),
    ]

# ── Markdown ───────────────────────────────────────────────────
MARKDOWN = (
    "# EMIS School Infrastructure Overview\n\n"
    "**School infrastructure summary by structure type, completion status, condition, and district.**\n\n"
    "---\n\n"
    "### Primary Audience\n"
    "- Commissioner Planning / Statistics\n"
    "- MoES Senior Management\n"
    "- District Education Officers (DEOs)\n"
    "- School Facilities Planners\n"
    "- Development Partners\n\n"
    "### Primary Questions Answered\n"
    "- How many classrooms, latrines, labs and libraries do Uganda's schools have?\n"
    "- What proportion of structures are complete vs incomplete?\n"
    "- What proportion are permanent vs temporary?\n"
    "- Which districts have the most and least infrastructure?\n"
    "- Which districts have the fewest science labs?\n"
    "- What is the overall condition of school infrastructure?\n\n"
    "### Note on Coverage\n"
    "Infrastructure data is captured for 12,425 schools out of 90,858 registered schools (13.7%). "
    "As more schools complete the annual school census, coverage will improve."
)

# ── Main ───────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("EMIS DW — Infrastructure Dashboard Builder")
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
        create_dashboard("EMIS School Infrastructure Overview", chart_ids, MARKDOWN)

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
