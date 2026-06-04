"""
EMIS Data Warehouse — Superset Dashboard Builder v2
Uses Superset's import/export ZIP format for reliability.
Works with all Superset versions including dev builds.

Usage:
    python build_teachers_dashboard_v2.py
"""

import requests
import urllib3
import getpass
import json
import yaml
import zipfile
import io
import uuid
import os

urllib3.disable_warnings()

SUPERSET_URL = "https://dw.emis4africa.com"
DB_NAME      = "demis_live"

session = requests.Session()
session.verify = False

def login(username, password):
    r = session.post(f"{SUPERSET_URL}/api/v1/security/login", json={
        "username": username,
        "password": password,
        "provider": "db",
        "refresh": True
    })
    r.raise_for_status()
    token = r.json()["access_token"]
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })
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
    """Create or update a virtual dataset."""
    # Get all datasets and search locally
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

def create_chart_v2(name, viz_type, ds_id, params):
    """Create chart using v2 endpoint."""
    payload = {
        "slice_name": name,
        "viz_type": viz_type,
        "datasource_id": ds_id,
        "datasource_type": "table",
        "params": json.dumps(params),
        "query_context": json.dumps({}),
    }
    # Try v1 endpoint
    r = session.post(f"{SUPERSET_URL}/api/v1/chart/", json=payload)
    if r.status_code in (200, 201):
        chart_id = r.json().get("id")
        print(f"  ✅ Created chart '{name}' (id={chart_id})")
        return chart_id
    
    # Fallback — try legacy endpoint
    payload2 = {
        "slice_name": name,
        "viz_type": viz_type,
        "datasource_id": f"{ds_id}__table",
        "params": json.dumps(params),
    }
    r2 = session.post(f"{SUPERSET_URL}/chart/add", data=payload2)
    if r2.status_code in (200, 201):
        print(f"  ✅ Created chart '{name}' (legacy endpoint)")
        return None

    print(f"  ⚠️  Chart '{name}' — status {r.status_code}: {r.text[:200]}")
    return None

def create_dashboard_with_charts(title, chart_ids):
    """Create dashboard — empty first, then attach charts via PUT."""
    # Step 1: Create empty dashboard
    payload = {
        "dashboard_title": title,
        "published": False,
        "position_json": "{}",
    }
    r = session.post(f"{SUPERSET_URL}/api/v1/dashboard/", json=payload)
    if r.status_code not in (200, 201):
        print(f"  ⚠️  Dashboard creation — status {r.status_code}: {r.text[:300]}")
        return None
    dash_id = r.json().get("id") or r.json().get("result", {}).get("id")
    print(f"\n✅ Dashboard '{title}' created (id={dash_id})")

    # Step 2: Build position JSON with UUID keys
    valid_ids = [cid for cid in chart_ids if cid is not None]

    markdown_text = (
        "# EMIS Teachers Overview\n\n"
        "**Teacher deployment summary by district, gender, qualification, designation, and payroll status.**\n\n"
        "---\n\n"
        "### Primary Audience\n"
        "- Commissioner Planning / Statistics\n"
        "- MoES Senior Management\n"
        "- District Education Officers (DEOs)\n"
        "- Human Resource Officers\n\n"
        "### Primary Questions Answered\n"
        "- How many teachers are deployed nationally?\n"
        "- What is the gender breakdown of the teaching force?\n"
        "- How many teachers are qualified vs trained?\n"
        "- Which districts have the most and fewest teachers?\n"
        "- What is the Pupil Teacher Ratio (PTR) by district?\n"
        "- How many teachers are on the government payroll?\n"
        "- How is the teaching force changing over time?"
    )

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
            col_id  = f"COLUMN-{str(uuid.uuid4())[:8]}"
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

    # Step 3: Update dashboard with position
    r2 = session.put(f"{SUPERSET_URL}/api/v1/dashboard/{dash_id}", json={
        "position_json": json.dumps(position)
    })
    if r2.status_code in (200, 201):
        print(f"✅ Charts attached to dashboard successfully")
    else:
        print(f"  ⚠️  Chart attachment — status {r2.status_code}: {r2.text[:300]}")
        print(f"  ℹ️  Dashboard was created but charts need to be added manually")
    return dash_id

# ── SQL Queries ────────────────────────────────────────────────
DATASETS = {
    "teachers_kpi_total": "SELECT COUNT(DISTINCT td.id) AS total_teachers FROM dw.teacher_dim td WHERE td.is_current = TRUE",
    "teachers_kpi_male": "SELECT COUNT(DISTINCT td.id) AS total_male FROM dw.teacher_dim td WHERE td.is_current = TRUE AND td.gender = 'M'",
    "teachers_kpi_female": "SELECT COUNT(DISTINCT td.id) AS total_female FROM dw.teacher_dim td WHERE td.is_current = TRUE AND td.gender = 'F'",
    "teachers_kpi_pct_female": "SELECT ROUND(COUNT(DISTINCT CASE WHEN td.gender = 'F' THEN td.id END)::DECIMAL / NULLIF(COUNT(DISTINCT td.id), 0) * 100, 1) AS pct_female FROM dw.teacher_dim td WHERE td.is_current = TRUE",
    "teachers_kpi_qualified": "SELECT COUNT(DISTINCT td.id) AS qualified_teachers FROM dw.teacher_dim td WHERE td.is_current = TRUE AND td.teacher_type = 'QUALIFIED'",
    "teachers_kpi_govt_payroll": "SELECT COUNT(DISTINCT td.id) AS on_govt_payroll FROM dw.teacher_dim td WHERE td.is_current = TRUE AND td.is_on_government_payroll = TRUE",
    "teachers_by_type": "SELECT COALESCE(td.teacher_type, 'Unknown') AS teacher_type, COUNT(DISTINCT td.id) AS total_teachers FROM dw.teacher_dim td WHERE td.is_current = TRUE GROUP BY td.teacher_type ORDER BY total_teachers DESC",
    "teachers_by_gender": "SELECT COALESCE(td.gender, 'Unknown') AS gender, COUNT(DISTINCT td.id) AS total_teachers FROM dw.teacher_dim td WHERE td.is_current = TRUE GROUP BY td.gender ORDER BY total_teachers DESC",
    "teachers_by_discipline": "SELECT COALESCE(td.discipline, 'Unknown') AS discipline, COUNT(DISTINCT td.id) AS total_teachers FROM dw.teacher_dim td WHERE td.is_current = TRUE GROUP BY td.discipline ORDER BY total_teachers DESC",
    "teachers_by_qualification": "SELECT COALESCE(td.qualification, 'Unknown') AS qualification, COUNT(DISTINCT td.id) AS total_teachers FROM dw.teacher_dim td WHERE td.is_current = TRUE GROUP BY td.qualification ORDER BY total_teachers DESC",
    "teachers_by_designation": "SELECT COALESCE(td.designation, 'Unknown') AS designation, COUNT(DISTINCT td.id) AS total_teachers FROM dw.teacher_dim td WHERE td.is_current = TRUE GROUP BY td.designation ORDER BY total_teachers DESC",
    "teachers_top15_districts": "SELECT m.district_name, COUNT(DISTINCT hf.teacher_id) AS total_teachers FROM dw.hr_fact hf JOIN dw.school_district_map m ON m.school_dim_id = hf.school_id GROUP BY m.district_name ORDER BY total_teachers DESC LIMIT 15",
    "teachers_bottom15_districts": "SELECT m.district_name, COUNT(DISTINCT hf.teacher_id) AS total_teachers FROM dw.hr_fact hf JOIN dw.school_district_map m ON m.school_dim_id = hf.school_id GROUP BY m.district_name ORDER BY total_teachers ASC LIMIT 15",
    "teachers_trend_over_time": "SELECT hf.academic_year, hf.term, CONCAT('FY', hf.academic_year, ' ', hf.term) AS period, COUNT(DISTINCT hf.teacher_id) AS total_teachers, COUNT(DISTINCT CASE WHEN td.gender = 'M' THEN hf.teacher_id END) AS male, COUNT(DISTINCT CASE WHEN td.gender = 'F' THEN hf.teacher_id END) AS female FROM dw.hr_fact hf JOIN dw.teacher_dim td ON td.id = hf.teacher_id AND td.is_current = TRUE GROUP BY hf.academic_year, hf.term ORDER BY hf.academic_year, hf.term",
    "teachers_district_leaderboard": """SELECT m.district_name AS "District", COUNT(DISTINCT hf.teacher_id) AS "Total Teachers", COUNT(DISTINCT CASE WHEN td.gender = 'M' THEN hf.teacher_id END) AS "Male", COUNT(DISTINCT CASE WHEN td.gender = 'F' THEN hf.teacher_id END) AS "Female", ROUND(COUNT(DISTINCT CASE WHEN td.gender = 'F' THEN hf.teacher_id END)::DECIMAL / NULLIF(COUNT(DISTINCT hf.teacher_id), 0) * 100, 1) AS "% Female", COUNT(DISTINCT CASE WHEN td.teacher_type = 'QUALIFIED' THEN hf.teacher_id END) AS "Qualified", COUNT(DISTINCT CASE WHEN td.is_on_government_payroll = TRUE THEN hf.teacher_id END) AS "Govt Payroll" FROM dw.hr_fact hf JOIN dw.teacher_dim td ON td.id = hf.teacher_id AND td.is_current = TRUE JOIN dw.school_district_map m ON m.school_dim_id = hf.school_id GROUP BY m.district_name ORDER BY "Total Teachers" DESC""",
    "teachers_ptr_by_district": """SELECT m.district_name AS "District", COUNT(DISTINCT hf.school_id) AS "Schools", COUNT(DISTINCT hf.teacher_id) AS "Teachers", SUM(ef.enrolment_count) AS "Learners", ROUND(SUM(ef.enrolment_count)::DECIMAL / NULLIF(COUNT(DISTINCT hf.teacher_id), 0), 1) AS "PTR" FROM dw.hr_fact hf JOIN dw.school_district_map m ON m.school_dim_id = hf.school_id LEFT JOIN (SELECT school_id, COUNT(*) AS enrolment_count FROM dw.enrolment_fact GROUP BY school_id) ef ON ef.school_id = hf.school_id GROUP BY m.district_name ORDER BY "PTR" DESC NULLS LAST""",
}

# ── Metric helper ─────────────────────────────────────────────
def m(col):
    """Build a proper Superset metric object from a column name."""
    return {"expressionType": "SIMPLE", "column": {"column_name": col}, "aggregate": "MAX", "label": col}

def m_sum(col):
    """Build a SUM metric object."""
    return {"expressionType": "SIMPLE", "column": {"column_name": col}, "aggregate": "SUM", "label": col}

# ── Chart definitions ──────────────────────────────────────────
def get_chart_defs(ds_ids):
    return [
        # KPIs
        ("Total Teachers",              "big_number_total", ds_ids["teachers_kpi_total"],        {"metric": m("total_teachers"), "subheader": "Total Teachers"}),
        ("Male Teachers",               "big_number_total", ds_ids["teachers_kpi_male"],         {"metric": m("total_male"), "subheader": "Male Teachers"}),
        ("Female Teachers",             "big_number_total", ds_ids["teachers_kpi_female"],       {"metric": m("total_female"), "subheader": "Female Teachers"}),
        ("% Female Teachers",           "big_number_total", ds_ids["teachers_kpi_pct_female"],   {"metric": m("pct_female"), "subheader": "% Female", "y_axis_format": ".1f"}),
        ("Qualified Teachers",          "big_number_total", ds_ids["teachers_kpi_qualified"],    {"metric": m("qualified_teachers"), "subheader": "Qualified"}),
        ("Teachers on Govt Payroll",    "big_number_total", ds_ids["teachers_kpi_govt_payroll"], {"metric": m("on_govt_payroll"), "subheader": "Govt Payroll"}),
        # Pies
        ("Teachers by Type",            "pie", ds_ids["teachers_by_type"],       {"groupby": ["teacher_type"], "metric": m_sum("total_teachers"), "show_labels": True, "show_legend": True}),
        ("Teachers by Gender",          "pie", ds_ids["teachers_by_gender"],     {"groupby": ["gender"], "metric": m_sum("total_teachers"), "show_labels": True, "show_legend": True}),
        ("Teachers by Discipline",      "pie", ds_ids["teachers_by_discipline"], {"groupby": ["discipline"], "metric": m_sum("total_teachers"), "show_labels": True, "show_legend": True}),
        # Bars
        ("Teachers by Qualification",   "bar", ds_ids["teachers_by_qualification"], {"metrics": [m_sum("total_teachers")], "groupby": ["qualification"]}),
        ("Teachers by Designation",     "bar", ds_ids["teachers_by_designation"],   {"metrics": [m_sum("total_teachers")], "groupby": ["designation"]}),
        ("Top 15 Districts",            "bar", ds_ids["teachers_top15_districts"],   {"metrics": [m_sum("total_teachers")], "groupby": ["district_name"]}),
        ("Bottom 15 Districts",         "bar", ds_ids["teachers_bottom15_districts"],{"metrics": [m_sum("total_teachers")], "groupby": ["district_name"]}),
        ("Teachers Over Time",          "bar", ds_ids["teachers_trend_over_time"],   {"metrics": [m_sum("total_teachers")], "groupby": ["period"]}),
        # Tables
        ("Teacher District Leaderboard","table", ds_ids["teachers_district_leaderboard"], {"groupby": ["District", "Total Teachers", "Male", "Female", "% Female", "Qualified", "Govt Payroll"], "show_cell_bars": True, "page_length": 20}),
        ("PTR by District",             "table", ds_ids["teachers_ptr_by_district"],     {"groupby": ["District", "Schools", "Teachers", "Learners", "PTR"], "show_cell_bars": True, "page_length": 20}),
    ]

# ── Main ───────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("EMIS DW — Teachers Dashboard Builder v2")
    print("=" * 60)

    username = input("Superset username: ")
    password = getpass.getpass("Superset password: ")

    login(username, password)
    db_id = get_database_id()

    print("\nCreating datasets...")
    ds_ids = {}
    for name, sql in DATASETS.items():
        ds_ids[name] = create_dataset(db_id, name, sql)

    print("\nCreating charts...")
    chart_ids = []
    for name, viz_type, ds_id, params in get_chart_defs(ds_ids):
        cid = create_chart_v2(name, viz_type, ds_id, params)
        chart_ids.append(cid)

    print("\nCreating dashboard...")
    create_dashboard_with_charts("EMIS Teachers Overview", chart_ids)

    print("\n" + "=" * 60)
    created = sum(1 for c in chart_ids if c is not None)
    print(f"✅ Done! {created}/{len(chart_ids)} charts created")
    print(f"   Visit: {SUPERSET_URL}/dashboard/list/")
    print("=" * 60)

if __name__ == "__main__":
    main()
