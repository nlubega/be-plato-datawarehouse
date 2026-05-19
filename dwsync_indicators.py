import os
import subprocess
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("dwsync_indicators.log", encoding="utf-8")
    ]
)
log = logging.getLogger(__name__)

LOCAL_DB = {
    "host":     os.getenv("LOCAL_DB_HOST"),
    "port":     os.getenv("LOCAL_DB_PORT", "5432"),
    "dbname":   os.getenv("LOCAL_DB_NAME"),
    "user":     os.getenv("LOCAL_DB_USER"),
    "password": os.getenv("LOCAL_DB_PASSWORD")
}

INDICATORS_ETL_SCRIPTS = [
    "sql/05_etl/indicators/00_load_population_data.sql",
    "sql/05_etl/indicators/01_compute_enrolment_indicators.sql",
    "sql/05_etl/indicators/02_compute_school_indicators.sql",
    "sql/05_etl/indicators/03_load_indicator_facts.sql",
    "sql/05_etl/indicators/04_dq_checks_indicators.sql",
]


def run_sql_script(script_path):
    abs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"SQL script not found: {abs_path}")

    env = os.environ.copy()
    env["PGPASSWORD"] = LOCAL_DB["password"]

    result = subprocess.run(
        [
            "psql",
            "-h", LOCAL_DB["host"],
            "-p", LOCAL_DB["port"],
            "-U", LOCAL_DB["user"],
            "-d", LOCAL_DB["dbname"],
            "-v", "ON_ERROR_STOP=1",
            "-f", abs_path
        ],
        env=env,
        capture_output=True,
        text=True
    )

    if result.stdout:
        for line in result.stdout.splitlines():
            if line.strip():
                log.info(f"  {line}")

    if result.returncode != 0:
        raise Exception(result.stderr)


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("EMIS DW Termly Sync — Indicators Mart")
    log.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        for script_path in INDICATORS_ETL_SCRIPTS:
            script_name = os.path.basename(script_path)
            log.info(f"Running ETL script: {script_name}")
            start = datetime.now()
            run_sql_script(script_path)
            elapsed = (datetime.now() - start).total_seconds()
            log.info(f"  {script_name} completed in {elapsed:.1f}s")

        log.info("=" * 60)
        log.info("ALL STEPS COMPLETED SUCCESSFULLY")
        log.info("=" * 60)

    except Exception as e:
        log.error("=" * 60)
        log.error(f"SYNC FAILED: {e}")
        log.error("=" * 60)
        raise SystemExit(1)
