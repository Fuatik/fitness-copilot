# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Ingest All Exercises from WGER & Embed
# MAGIC %md
# MAGIC # Ingest ALL Exercises from WGER API & Embed
# MAGIC
# MAGIC This notebook:
# MAGIC 1. **Fetches ALL exercises** from WGER API (paginated, no key)
# MAGIC 2. Stores them in `exercise_metadata`
# MAGIC 3. Computes embeddings for new exercises
# MAGIC 4. Enables semantic search over all exercises
# MAGIC
# MAGIC **Run this periodically** to keep exercise database up‑to‑date.

# COMMAND ----------

# DBTITLE 1,Install all required packages
# MAGIC %pip uninstall -y psycopg2 psycopg2-binary
# MAGIC %pip install -q 'databricks-sdk>=0.118.0' sentence-transformers requests

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Configuration
import base64
import psycopg2
from psycopg2.extras import RealDictCursor
from databricks.sdk import WorkspaceClient
import requests
import time
import json

w = WorkspaceClient()

# ---- Lakebase connection ----
secret = w.secrets.get_secret(scope="database", key="lakebase-url")
LAKEBASE_URL = base64.b64decode(secret.value).decode("utf-8")

def get_conn():
    return psycopg2.connect(LAKEBASE_URL, cursor_factory=RealDictCursor)

# ---- Configuration ----
WGER_URL = "https://wger.de/api/v2/exerciseinfo/"
LANGUAGE = 2  # English
PAGE_SIZE = 50
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
BATCH_SIZE = 32
EMBEDDING_DIM = 384

print("Fetching ALL exercises from WGER API (no key required).")

# COMMAND ----------

# DBTITLE 1,Test Connection
try:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()
            print(f"✅ Connected to Lakebase: {version['version']}")
except Exception as e:
    print(f"❌ Connection error: {e}")
    dbutils.notebook.exit("Connection failed.")

# COMMAND ----------

# DBTITLE 1,Fetch ALL Exercises from WGER (Paginated)
def fetch_all_exercises():
    """Fetch all exercises from WGER API with pagination."""
    all_exercises = []
    page = 1

    print("Fetching exercises from WGER...")

    while True:
        try:
            url = f"{WGER_URL}?language={LANGUAGE}&limit={PAGE_SIZE}&offset={(page-1)*PAGE_SIZE}"
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            results = data.get('results', [])
            if not results:
                break

            all_exercises.extend(results)
            print(f"  Page {page}: fetched {len(results)} exercises (total: {len(all_exercises)})")

            # Check if we have all pages
            if data.get('next') is None:
                break

            page += 1
            time.sleep(0.5)  # Be polite to the API

        except requests.exceptions.RequestException as e:
            print(f"  Error on page {page}: {e}")
            break

    return all_exercises

exercises = fetch_all_exercises()
print(f"\n✅ Total exercises fetched: {len(exercises)}")

# COMMAND ----------

# DBTITLE 1,Parse and Store Exercises in Lakebase
def parse_exercise(item):
    """Parse WGER response into our schema."""
    # Find English translation (language ID = 2)
    translations = item.get('translations', [])
    english = [t for t in translations if t.get('language') == 2]
    
    if not english:
        return None  # Skip exercises without English translation
    
    trans = english[0]
    name = trans.get('name', '').strip()
    description = trans.get('description', '') or f"{name} – a strength training exercise."
    
    # Get first image from images array
    images = item.get('images', [])
    gif_url = images[0].get('image', '') if images else ''
    
    return {
        'name': name,
        'description': description,
        'muscles': [m.get('name_en') or m.get('name', '') for m in item.get('muscles', [])],
        'equipment': [e.get('name', '') for e in item.get('equipment', [])],
        'instructions': description,  # WGER combines description+instructions now
        'gif_url': gif_url
    }

print("Storing exercises in Lakebase...")
stored_count = 0
skipped_count = 0
with get_conn() as conn:
    with conn.cursor() as cur:
        for i, item in enumerate(exercises):
            ex = parse_exercise(item)
            if ex is None or not ex.get('name'):
                skipped_count += 1
                if skipped_count <= 3:
                    print(f"  ⚠️  Skipped exercise {i+1}: no English translation or empty name")
                continue
            cur.execute("""
                        INSERT INTO exercise_metadata (name, description, muscles, equipment, instructions, gif_url)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE SET
                                                         description = EXCLUDED.description,
                                                         muscles = EXCLUDED.muscles,
                                                         equipment = EXCLUDED.equipment,
                                                         instructions = EXCLUDED.instructions,
                                                         gif_url = EXCLUDED.gif_url
                        """, (ex['name'], ex['description'], ex['muscles'], ex['equipment'], ex['instructions'], ex['gif_url']))
            stored_count += 1
            if stored_count % 100 == 0:
                print(f"  Progress: {stored_count} stored...")
        conn.commit()
print(f"\n✅ Stored/updated {stored_count} exercises")
print(f"⚠️  Skipped {skipped_count} exercises (empty names)")

# COMMAND ----------

# DBTITLE 1,Load Unembedded Exercises
print("Loading exercises without embeddings...")
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
                    SELECT name, description, muscles, equipment, instructions
                    FROM exercise_metadata
                    WHERE description IS NOT NULL
                      AND description != ''
                      AND embedding IS NULL
                    ORDER BY name
                    LIMIT 500
                    """)
        unembedded = cur.fetchall()
print(f"Found {len(unembedded)} exercises without embeddings.")

if not unembedded:
    print("✅ All exercises already embedded. Skipping.")
    dbutils.notebook.exit("All exercises embedded.")

# COMMAND ----------

# DBTITLE 1,Compute Embeddings
from sentence_transformers import SentenceTransformer
import time

print(f"Loading embedding model: {EMBEDDING_MODEL}")
model = SentenceTransformer(EMBEDDING_MODEL)

print("Computing embeddings...")
embeddings_to_store = []
for i, ex in enumerate(unembedded):
    vec = model.encode(ex['description']).tolist()
    embeddings_to_store.append({
        'name': ex['name'],
        'embedding': vec
    })
    if (i + 1) % 10 == 0:
        print(f"  Processed {i + 1}/{len(unembedded)} exercises")

print(f"Computed {len(embeddings_to_store)} embeddings.")

# COMMAND ----------

# DBTITLE 1,Store Embeddings
print("Storing embeddings in Lakebase...")
with get_conn() as conn:
    with conn.cursor() as cur:
        for ex in embeddings_to_store:
            cur.execute("""
                        UPDATE exercise_metadata
                        SET embedding = %s::vector
                        WHERE name = %s
                        """, (str(ex['embedding']), ex['name']))
        conn.commit()
print(f"✅ Stored {len(embeddings_to_store)} embeddings in exercise_metadata.")

# COMMAND ----------

# DBTITLE 1,Verify Results
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
                    SELECT COUNT(*) AS total,
                           COUNT(embedding) AS embedded
                    FROM exercise_metadata
                    """)
        result = cur.fetchone()
        print(f"\n📊 Summary:")
        print(f"  Total exercises: {result['total']}")
        print(f"  Embedded: {result['embedded']}")
        print(f"  Pending: {result['total'] - result['embedded']}")

        cur.execute("""
                    SELECT name, description
                    FROM exercise_metadata
                    WHERE embedding IS NOT NULL
                    LIMIT 5
                    """)
        sample = cur.fetchall()
        print("\n📝 Sample embedded exercises:")
        for ex in sample:
            print(f"  - {ex['name']}")

print("\n🎉 Pipeline complete! All exercises are now available for semantic search.")