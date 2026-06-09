"""
Grant Gamma role access to one or more dashboards.
Usage: python grant_gamma_access.py

Enter dashboard IDs when prompted (comma separated).
e.g. 21,22,23,24,25
"""
import requests, urllib3, getpass
urllib3.disable_warnings()

SUPERSET_URL = "https://dw.emis4africa.com"
GAMMA_ROLE_ID = 4

session = requests.Session()
session.verify = False

username = input("Username: ")
password = getpass.getpass("Password: ")

r = session.post(f"{SUPERSET_URL}/api/v1/security/login", json={
    "username": username, "password": password, "provider": "db", "refresh": True})
r.raise_for_status()
session.headers.update({
    "Authorization": f"Bearer {r.json()['access_token']}",
    "Content-Type": "application/json"
})
csrf = session.get(f"{SUPERSET_URL}/api/v1/security/csrf_token/")
session.headers["X-CSRFToken"] = csrf.json()["result"]
print("✅ Logged in\n")

# Get all dashboards and show list
r = session.get(f"{SUPERSET_URL}/api/v1/dashboard/?q=(page_size:100)")
dashboards = r.json().get("result", [])
print("Available dashboards:")
for d in dashboards:
    print(f"  id={d['id']:3}  {d['dashboard_title']}")

print()
ids_input = input("Enter dashboard ID(s) to grant Gamma access (comma separated, or 'all'): ")

if ids_input.strip().lower() == "all":
    dashboard_ids = [d["id"] for d in dashboards]
else:
    dashboard_ids = [int(x.strip()) for x in ids_input.split(",")]

print()
for did in dashboard_ids:
    r2 = session.put(f"{SUPERSET_URL}/api/v1/dashboard/{did}",
                     json={"roles": [GAMMA_ROLE_ID]})
    if r2.status_code in (200, 201):
        title = next((d["dashboard_title"] for d in dashboards if d["id"] == did), f"id={did}")
        print(f"  ✅ Gamma access granted to: {title}")
    else:
        print(f"  ⚠️  Failed for id={did}: {r2.status_code}: {r2.text[:150]}")

print("\nDone. Log in as emis_viewer to verify.")
