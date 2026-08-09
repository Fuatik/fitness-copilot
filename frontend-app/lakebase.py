import base64
import os
import hashlib
import psycopg2
from psycopg2.extras import RealDictCursor
from databricks.sdk import WorkspaceClient

_w = WorkspaceClient()
SCOPE = os.environ.get("LAKEBASE_SECRET_SCOPE", "database")
KEY = os.environ.get("LAKEBASE_SECRET_KEY", "lakebase-url")

def _lakebase_url():
    secret = _w.secrets.get_secret(scope=SCOPE, key=KEY)
    return base64.b64decode(secret.value).decode("utf-8")

def get_connection():
    return psycopg2.connect(_lakebase_url(), cursor_factory=RealDictCursor)

def run_query(sql, params=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

def run_write(sql, params=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.rowcount

def hash_email(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()