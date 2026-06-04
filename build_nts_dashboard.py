"""
EMIS Data Warehouse — Superset Dashboard Builder
Non-Teaching Staff Dashboard
All lessons learned applied:
- Proper metric objects (not plain strings)
- bar chart type with correct params
- Markdown at top with UUID keys
- Two-step dashboard creation
"""

import requests
import urllib3
import getpass
import json
import uuid
import sys

urllib3.disable_warnings()

SUPERSET_URL = "https://dw.emis4africa.com"
DB_NAME      = "demis_live"

session = requests.Session()
session.verify = False

# ── Auth ───────────────────────────────────────────────────────
def login(username, password):
    r = session.post(f"{SUPERSET_URL}/api/v1/security/login", json={
        "username": username, "password": password,
        "provider": "db", "refresh": True
    })
    r.raise_for_status()
    token = r.json()["access_token"]
    session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
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

# ── Dataset ────────────────────────────────────────────────────
def create_dataset(db_id, name, sql):
    r = session.get(f"{SUPERSET_URL}/api/v1/dataset/?q=(page_size:1000)")
    all_ds = r.json().get("result", [])
    for ds in all_ds:
        if ds.get("table_name") == name:
            ds_id = ds["id"]
            session.put(f"{SUPERSET_URL}/api/v1/dataset/{ds_id}", json={"sql": sql})
            print(f"  ♻️  Updated dataset '{name}' (id={ds_id})")
            return ds_id
    payload = {"database": db_id, "schema": "dw", "table_name": name, "sql": sql}
    r = session.post(f"{SUPERSET_URL}/api/v1/dataset/", json=payload)
    r.raise_for_status()
    ds_id = r.json()["id"]
    print(f"  ✅ Created dataset '{name}' (id={ds_id})")
    return ds_id

# ── Metric helpers ─────────────────────────────────────────────
def m(col):
    return {"expressionType": "SIMPLE", "column": {"column_name": col}, "aggregate": "MAX", "label": col}

def m_sum(col):
    return {"expressionType": "SIMPLE", "column": {"column_name": col}, "aggregate": "SUM", "label": col}

# ── Chart ──────────────────────────────────────────────────────
def create_chart(name, viz_type, ds_id, params):
    payload = {
        "slice_name": name,
        "viz_type": viz_type,
        "datasource_id": ds_id,
        "datasource_type": "table",
        "params": json.dumps(params),
        "query_context": json.dumps({}),
    }
    r = session.post(f"{SUPERSET_URL}/api/v1/chart/", json=payload)
    if r.status_code in (200, 201):
        chart_id = r.json().get("id")
        print(f"  ✅ Created chart '{name}' (id={chart_id})")
        return chart_id
    print(f"  ⚠️  Chart '{name}' — status {r.status_code}: {r.text[:150]}")
    return None

# ── Dashboard ──────────────────────────────────────────────────
def create_dashboard(title, chart_ids, markdown_text):
    # Step 1: Create empty dashboard
    r = session.post(f"{SUPERSET_URL}/api/v1/dashboard/", json={
        "dashboard_title": title,
        "published": False,
        "position_json": "{}",
    })
    if r.status_code not in (200, 201):
        print(f"  ⚠️  Dashboard — status {r.status_code}: {r.text[:300]}")
        return None
    dash_id = r.json().get("id") or r.json().get("result", {}).get("id")
    print(f"\n✅ Dashboard '{title}' created (id={dash_id})")

    # Step 2: Build position with Markdown at top + charts
    valid_ids = [cid for cid in chart_ids if cid is not None]

    md_row_id = f"ROW-{str(uuid.uuid4())[:8]}"
    md_col_id = f"COLUMN-{str(uuid.uuid4())[:8]}"
    md_id     = f"MARKDOWN-{str(uuid.uuid4())[:8]}"

    position = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
        md_row_id: {
            "type": "ROW", "id": md_row_id,
            "children": [md_col_id],
            "parents": ["GRID_ID", "ROOT_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"}
        },
        md_col_id: {
            "type": "COLUMN", "id": md_col_id,
            "children": [md_id],
            "parents": [md_row_id, "GRID_ID", "ROOT_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT", "width": 12}
        },
        md_id: {
            "type": "MARKDOWN", "id": md_id,
            "children": [],
            "parents": [md_col_id, md_row_id, "GRID_ID", "ROOT_ID"],
            "meta": {"width": 12, "height": 14, "code": markdown_text}
        },
    }
    rows = [md_row_id]

    for i in range(0, len(valid_ids), 3):
        row_charts = valid_ids[i:i+3]
        row_id = f"ROW-{str(uuid.uuid4())[:8]}"
        cols = []
        for j, cid in enumerate(row_charts):
            col_id    = f"COLUMN-{str(uuid.uuid4())[:8]}"
            chart_key = f"CHART-{str(uuid.uuid4())[:8]}"
            position[col_id] = {
                "type": "COLUMN", "id": col_id,
                "children": [chart_key],
                "parents": [row_id, "GRID_ID", "ROOT_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT", "width": 4}
            }
            position[chart_key] = {
                "type": "CHART", "id": chart_key,
                "children": [],
                "parents": [col_id, row_id, "GRID_ID", "ROOT_ID"],
                "meta": {"chartId": cid, "width": 4, "height": 50, "sliceName": f"Chart {cid}"}
            }
            cols.append(col_id)
        position[row_id] = {
            "type": "ROW", "id": row_id,
            "children": cols,
            "parents": ["GRID_ID", "ROOT_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"}
        }
        rows.append(row_id)

    position["GRID_ID"]["children"] = rows

    # Step 3: Update with position
    r2 = session.put(f"{SUPERSET_URL}/api/v1/dashboard/{dash_id}", json={
        "position_json": json.dumps(position)
    })
    if r2.status_code in (200, 201):
        print(f"✅ Charts and Markdown attached to dashboard successfully")
    else:
        print(f"  ⚠️  Attachment — status {r2.status_code}: {r2.text[:300]}")
    return dash_id

# ── SQL Queries ────────────────────────────────────────────────
DATASETS = {

    "nts_kpi_total": """
SELECT COUNT(DISTINCT ns.id) AS total_staff
FROM dw.non_teaching_staff_dim ns
WHERE ns.is_current = TRUE""",

    "nts_kpi_male": """
SELECT COUNT(DISTINCT ns.id) AS total_male
FROM dw.non_teaching_staff_dim ns
WHERE ns.is_current = TRUE AND ns.gender = 'M'""",

    "nts_kpi_female": """
SELECT COUNT(DISTINCT ns.id) AS total_female
FROM dw.non_teaching_staff_dim ns
WHERE ns.is_current = TRUE AND ns.gender = 'F'""",

    "nts_kpi_pct_female": """
SELECT ROUND(
    COUNT(DISTINCT CASE WHEN ns.gender = 'F' THEN ns.id END)::DECIMAL /
    NULLIF(COUNT(DISTINCT ns.id), 0) * 100
, 1) AS pct_female
FROM dw.non_teaching_staff_dim ns
WHERE ns.is_current = TRUE""",

    "nts_kpi_govt_payroll": """
SELECT COUNT(DISTINCT ns.id) AS on_govt_payroll
FROM dw.non_teaching_staff_dim ns
WHERE ns.is_current = TRUE AND ns.is_on_government_payroll = TRUE""",

    "nts_kpi_schools": """
SELECT COUNT(DISTINCT nf.school_id) AS schools_with_nts
FROM dw.non_teaching_staff_fact nf""",

    "nts_by_category": """
SELECT
    COALESCE(ns.category, 'Unknown') AS category,
    COUNT(DISTINCT ns.id)            AS total_staff
FROM dw.non_teaching_staff_dim ns
WHERE ns.is_current = TRUE
GROUP BY ns.category
ORDER BY total_staff DESC""",

    "nts_by_gender": """
SELECT
    COALESCE(ns.gender, 'Unknown') AS gender,
    COUNT(DISTINCT ns.id)          AS total_staff
FROM dw.non_teaching_staff_dim ns
WHERE ns.is_current = TRUE
GROUP BY ns.gender
ORDER BY total_staff DESC""",

    "nts_by_role": """
SELECT
    COALESCE(ns.role, 'Unknown') AS role,
    COUNT(DISTINCT ns.id)        AS total_staff
FROM dw.non_teaching_staff_dim ns
WHERE ns.is_current = TRUE
GROUP BY ns.role
ORDER BY total_staff DESC""",

    "nts_by_employment_status": """
SELECT
    COALESCE(ns.employment_status, 'Unknown') AS employment_status,
    COUNT(DISTINCT ns.id)                     AS total_staff
FROM dw.non_teaching_staff_dim ns
WHERE ns.is_current = TRUE
GROUP BY ns.employment_status
ORDER BY total_staff DESC""",

    "nts_by_education_level": """
SELECT
    COALESCE(ns.highest_education_level, 'Unknown') AS education_level,
    COUNT(DISTINCT ns.id)                           AS total_staff
FROM dw.non_teaching_staff_dim ns
WHERE ns.is_current = TRUE
GROUP BY ns.highest_education_level
ORDER BY total_staff DESC""",

    "nts_top15_districts": """
SELECT
    m.district_name,
    COUNT(DISTINCT nf.staff_id) AS total_staff
FROM dw.non_teaching_staff_fact nf
JOIN dw.school_district_map m ON m.school_dim_id = nf.school_id
GROUP BY m.district_name
ORDER BY total_staff DESC
LIMIT 15""",

    "nts_bottom15_districts": """
SELECT
    m.district_name,
    COUNT(DISTINCT nf.staff_id) AS total_staff
FROM dw.non_teaching_staff_fact nf
JOIN dw.school_district_map m ON m.school_dim_id = nf.school_id
GROUP BY m.district_name
ORDER BY total_staff ASC
LIMIT 15""",

    "nts_trend_over_time": """
SELECT
    nf.academic_year,
    nf.term,
    CONCAT('FY', nf.academic_year, ' ', nf.term) AS period,
    COUNT(DISTINCT nf.staff_id)                  AS total_staff
FROM dw.non_teaching_staff_fact nf
GROUP BY nf.academic_year, nf.term
ORDER BY nf.academic_year, nf.term""",

    "nts_district_leaderboard": """
SELECT
    m.district_name                                                          AS "District",
    COUNT(DISTINCT nf.staff_id)                                             AS "Total Staff",
    COUNT(DISTINCT CASE WHEN ns.gender = 'M' THEN nf.staff_id END)         AS "Male",
    COUNT(DISTINCT CASE WHEN ns.gender = 'F' THEN nf.staff_id END)         AS "Female",
    ROUND(COUNT(DISTINCT CASE WHEN ns.gender = 'F' THEN nf.staff_id END)::DECIMAL /
        NULLIF(COUNT(DISTINCT nf.staff_id), 0) * 100, 1)                   AS "% Female",
    COUNT(DISTINCT CASE WHEN ns.category = 'ADMINISTRATIVE'
          THEN nf.staff_id END)                                             AS "Administrative",
    COUNT(DISTINCT CASE WHEN ns.category = 'SUPPORT'
          THEN nf.staff_id END)                                             AS "Support",
    COUNT(DISTINCT CASE WHEN ns.is_on_government_payroll = TRUE
          THEN nf.staff_id END)                                             AS "Govt Payroll"
FROM dw.non_teaching_staff_fact nf
JOIN dw.non_teaching_staff_dim ns  ON ns.id = nf.staff_id AND ns.is_current = TRUE
JOIN dw.school_district_map m      ON m.school_dim_id = nf.school_id
GROUP BY m.district_name
ORDER BY "Total Staff" DESC""",
}

# ── Chart definitions ──────────────────────────────────────────
def get_chart_defs(ds_ids):
    return [
        # KPIs
        ("Total Non-Teaching Staff",    "big_number_total", ds_ids["nts_kpi_total"],        {"metric": m("total_staff"),      "subheader": "Total Non-Teaching Staff"}),
        ("Male Staff",                  "big_number_total", ds_ids["nts_kpi_male"],         {"metric": m("total_male"),       "subheader": "Male"}),
        ("Female Staff",                "big_number_total", ds_ids["nts_kpi_female"],       {"metric": m("total_female"),     "subheader": "Female"}),
        ("% Female Staff",              "big_number_total", ds_ids["nts_kpi_pct_female"],   {"metric": m("pct_female"),       "subheader": "% Female", "y_axis_format": ".1f"}),
        ("Staff on Govt Payroll",       "big_number_total", ds_ids["nts_kpi_govt_payroll"], {"metric": m("on_govt_payroll"),  "subheader": "Govt Payroll"}),
        ("Schools with Non-Teaching Staff", "big_number_total", ds_ids["nts_kpi_schools"], {"metric": m("schools_with_nts"), "subheader": "Schools Reporting"}),
        # Pies
        ("Staff by Category",           "pie", ds_ids["nts_by_category"],          {"groupby": ["category"],          "metric": m_sum("total_staff"), "show_labels": True, "show_legend": True, "label_type": "key_percent", "row_limit": 50}),
        ("Staff by Gender",             "pie", ds_ids["nts_by_gender"],            {"groupby": ["gender"],            "metric": m_sum("total_staff"), "show_labels": True, "show_legend": True, "label_type": "key_percent", "row_limit": 50}),
        ("Staff by Employment Status",  "pie", ds_ids["nts_by_employment_status"], {"groupby": ["employment_status"], "metric": m_sum("total_staff"), "show_labels": True, "show_legend": True, "label_type": "key_percent", "row_limit": 50}),
        # Bars
        ("Staff by Role",               "bar", ds_ids["nts_by_role"],              {"metrics": [m_sum("total_staff")], "columns": [], "groupby": ["role"],            "row_limit": 50, "show_legend": True}),
        ("Staff by Education Level",    "bar", ds_ids["nts_by_education_level"],   {"metrics": [m_sum("total_staff")], "columns": [], "groupby": ["education_level"], "row_limit": 50, "show_legend": True}),
        ("Top 15 Districts",            "bar", ds_ids["nts_top15_districts"],      {"metrics": [m_sum("total_staff")], "columns": [], "groupby": ["district_name"],   "row_limit": 15, "show_legend": True}),
        ("Bottom 15 Districts",         "bar", ds_ids["nts_bottom15_districts"],   {"metrics": [m_sum("total_staff")], "columns": [], "groupby": ["district_name"],   "row_limit": 15, "show_legend": True}),
        ("Staff Over Time",             "bar", ds_ids["nts_trend_over_time"],      {"metrics": [m_sum("total_staff")], "columns": [], "groupby": ["period"],           "row_limit": 50, "show_legend": True}),
        # Table
        ("Non-Teaching Staff District Leaderboard", "table", ds_ids["nts_district_leaderboard"], {"groupby": ["District", "Total Staff", "Male", "Female", "% Female", "Administrative", "Support", "Govt Payroll"], "show_cell_bars": True, "page_length": 20}),
    ]

# ── Markdown ───────────────────────────────────────────────────
MARKDOWN = (
    "# EMIS Non-Teaching Staff Overview\n\n"
    "**Non-teaching staff summary by district, category, role, gender, and payroll status.**\n\n"
    "---\n\n"
    "### Primary Audience\n"
    "- Commissioner Planning / Statistics\n"
    "- MoES Senior Management\n"
    "- District Education Officers (DEOs)\n"
    "- Human Resource Officers\n\n"
    "### Primary Questions Answered\n"
    "- How many non-teaching staff are deployed nationally?\n"
    "- What is the breakdown between Administrative and Support staff?\n"
    "- What roles are most common across Uganda's schools?\n"
    "- Which districts have the most and fewest non-teaching staff?\n"
    "- What is the gender breakdown of non-teaching staff?\n"
    "- How many are on the government payroll?\n"
    "- How is the non-teaching workforce changing over time?"
)

# ── Main ───────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("EMIS DW — Non-Teaching Staff Dashboard Builder")
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
        create_dashboard("EMIS Non-Teaching Staff Overview", chart_ids, MARKDOWN)

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
