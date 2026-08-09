# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# DBTITLE 1,Ingest Fitness Programs & Embed Unstructured Data
# MAGIC %md
# MAGIC # Ingest Fitness Programs & Embed Unstructured Data
# MAGIC
# MAGIC **⚠️ PREREQUISITES:** Before running this notebook, you must manually create the database tables by executing `sql/01_setup_core_tables.sql` and `sql/02_setup_user_tables.sql` against your Lakebase Postgres database. See main README.md for detailed instructions.
# MAGIC
# MAGIC **This notebook populates your Lakebase with CORE data (run every time data changes):**
# MAGIC * Coefficient data (reps → % of 1RM)
# MAGIC * Strength Program 2.0 template (weeks 5-7)
# MAGIC * 6 exercise descriptions (unstructured data for semantic search)
# MAGIC * Sentence-transformer embeddings (384-dim vectors)
# MAGIC
# MAGIC **For test users and demo data:** Run `setup_test_users.py` ONCE after this notebook completes.

# COMMAND ----------

# DBTITLE 1,Install all required packages
# MAGIC %pip uninstall -y psycopg2 psycopg2-binary
# MAGIC %pip install -q 'databricks-sdk>=0.118.0' sentence-transformers requests

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Test Connection
# Simple connection test first
import base64
import psycopg2
from psycopg2.extras import RealDictCursor
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Get Lakebase URL from secrets
secret = w.secrets.get_secret(scope="database", key="lakebase-url")
LAKEBASE_URL = base64.b64decode(secret.value).decode("utf-8")

def get_conn():
    return psycopg2.connect(LAKEBASE_URL, cursor_factory=RealDictCursor)

# Test connection
try:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()
            print(f"✅ Connected to: {version['version']}")
except Exception as e:
    print(f"❌ Connection error: {e}")

# COMMAND ----------

# DBTITLE 1,Setup + Create Tables + Insert Core Data
# NOTE: Tables must be created first by running sql/01_setup_core_tables.sql and sql/02_setup_user_tables.sql

print("Inserting core data into Lakebase...\n")

# ---- 1. Insert coefficients ----
coeff_data = [
    (1, 100), (2, 95), (3, 92.5), (4, 90), (5, 87), (6, 85),
    (7, 83), (8, 80), (9, 78), (10, 75), (11, 73), (12, 70),
    (13, 68), (14, 66), (15, 64), (16, 62), (17, 60), (18, 58),
    (19, 56), (20, 54)
]
with get_conn() as conn:
    with conn.cursor() as cur:
        for reps, pct in coeff_data:
            cur.execute(
                "INSERT INTO coefficients (reps, percentage) VALUES (%s, %s) ON CONFLICT (reps) DO NOTHING",
                (reps, pct)
            )
        conn.commit()
print(f"✅ Inserted {len(coeff_data)} coefficients.")

# ---- 2. Insert Strength Program 2.0 ----
program_desc = """
Strength Program 2.0 – a 16-week linear periodization program focused on building raw strength.
It includes a preparatory phase, a test week, and three 6-week mesocycles with increasing intensity.
"""
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
                    INSERT INTO workout_programs (name, version, description, target, periodization_type)
                    VALUES ('Strength Program 2.0', '2.0', %s, 'strength', 'linear')
                    ON CONFLICT (name, version) DO NOTHING
                    RETURNING id
                    """, (program_desc,))
        row = cur.fetchone()
        if row:
            program_id = row['id']
            exercises_week5 = [
                ('Bench Press', 1, 70.0, 4, 5, 2.5),
                ('Back Squat', 1, 70.0, 4, 5, 2.5),
                ('Bent Over Row', 2, 70.0, 4, 5, 2.5),
                ('Deadlift', 2, 70.0, 4, 5, 2.5),
                ('Seated Dumbbell Press', 3, 70.0, 4, 5, 2.5),
                ('Lat Pulldown', 3, 70.0, 4, 5, 2.5),
            ]
            for ex in exercises_week5:
                cur.execute("""
                            INSERT INTO program_exercises (program_id, day, exercise_name, week, percentage_1rm, sets, reps, step_size)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (program_id, ex[1], ex[0], 5, ex[2], ex[3], ex[4], ex[5]))
            for week, pct in [(6, 75), (7, 80)]:
                for ex in exercises_week5:
                    cur.execute("""
                                INSERT INTO program_exercises (program_id, day, exercise_name, week, percentage_1rm, sets, reps, step_size)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                """, (program_id, ex[1], ex[0], week, pct, ex[3], ex[4], ex[5]))
            conn.commit()
            print(f"✅ Inserted Strength Program 2.0 with id {program_id}.")
        else:
            print("ℹ️ Program already exists, skipping.")

print("✅ Core data setup complete.")

# COMMAND ----------

# DBTITLE 1,Fetch Exercise Data from WGER API
import requests

# Since WGER API has issues, we'll create minimal exercise metadata manually
# This demonstrates unstructured data storage with embeddings
print("Creating exercise metadata with sample descriptions...")

EXERCISE_DATA = [
    {
        'name': 'Bench Press',
        'description': 'Compound upper body exercise targeting chest, shoulders, and triceps. Performed lying on a bench pressing a barbell or dumbbells.',
        'muscles': ['Pectoralis major', 'Anterior deltoid', 'Triceps brachii'],
        'equipment': ['Barbell', 'Bench'],
        'instructions': 'Lie on bench, grip bar slightly wider than shoulders, lower to chest, press up to full extension.',
        'gif_url': ''
    },
    {
        'name': 'Back Squat',
        'description': 'Fundamental lower body exercise targeting quads, glutes, and hamstrings. Barbell positioned on upper back.',
        'muscles': ['Quadriceps', 'Gluteus maximus', 'Hamstrings'],
        'equipment': ['Barbell', 'Squat rack'],
        'instructions': 'Bar on upper back, feet shoulder width, descend until thighs parallel to ground, drive up through heels.',
        'gif_url': ''
    },
    {
        'name': 'Deadlift',
        'description': 'Full body compound lift emphasizing posterior chain. Lift barbell from floor to hip level.',
        'muscles': ['Erector spinae', 'Gluteus maximus', 'Hamstrings', 'Trapezius'],
        'equipment': ['Barbell'],
        'instructions': 'Grip bar, flat back, drive through legs and hips to stand upright, reverse motion to lower.',
        'gif_url': ''
    },
    {
        'name': 'Bent Over Row',
        'description': 'Upper back exercise targeting lats and rhomboids. Pull barbell to torso while bent forward at hips.',
        'muscles': ['Latissimus dorsi', 'Rhomboids', 'Trapezius'],
        'equipment': ['Barbell'],
        'instructions': 'Hinge at hips, slight knee bend, pull bar to lower chest, squeeze shoulder blades together.',
        'gif_url': ''
    },
    {
        'name': 'Seated Dumbbell Press',
        'description': 'Shoulder pressing movement with dumbbells performed seated for stability.',
        'muscles': ['Anterior deltoid', 'Lateral deltoid', 'Triceps'],
        'equipment': ['Dumbbells', 'Bench'],
        'instructions': 'Sit upright, dumbbells at shoulder height, press overhead to full extension, lower controlled.',
        'gif_url': ''
    },
    {
        'name': 'Lat Pulldown',
        'description': 'Cable-based pulling exercise for back development, targets lats and upper back.',
        'muscles': ['Latissimus dorsi', 'Biceps', 'Rhomboids'],
        'equipment': ['Cable machine', 'Lat bar'],
        'instructions': 'Grip wide bar overhead, pull down to upper chest, squeeze shoulder blades, return controlled.',
        'gif_url': ''
    }
]

# Insert exercise metadata
with get_conn() as conn:
    with conn.cursor() as cur:
        for ex in EXERCISE_DATA:
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
            print(f"  ✅ Inserted: {ex['name']}")
        conn.commit()

print(f"\n✅ Successfully inserted {len(EXERCISE_DATA)} exercise descriptions (unstructured data for semantic search).")

# COMMAND ----------

# DBTITLE 1,Generate Embeddings for Semantic Search
from sentence_transformers import SentenceTransformer

print("Loading embedding model (this may take a minute)...")
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
print("✅ Model loaded successfully.")

# Embed program descriptions
print("\nEmbedding program descriptions...")
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT id, description FROM workout_programs WHERE description IS NOT NULL")
        progs = cur.fetchall()
        for p in progs:
            vec = model.encode(p['description']).tolist()
            cur.execute(
                "UPDATE workout_programs SET embedding = %s::vector WHERE id = %s",
                (str(vec), p['id'])
            )
            print(f"  ✅ Embedded program ID {p['id']}")
        conn.commit()
print("✅ Program descriptions embedded.")

# Embed exercise descriptions (unstructured text)
print("\nEmbedding exercise descriptions...")
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT name, description FROM exercise_metadata WHERE description IS NOT NULL AND description != ''")
        rows = cur.fetchall()
        embedded_count = 0
        for row in rows:
            vec = model.encode(row['description']).tolist()
            cur.execute(
                "UPDATE exercise_metadata SET embedding = %s::vector WHERE name = %s",
                (str(vec), row['name'])
            )
            print(f"  ✅ Embedded: {row['name']}")
            embedded_count += 1
        conn.commit()
print(f"\n✅ Exercise descriptions embedded ({embedded_count} exercises with unstructured data).")

print("\n🎉 Pipeline complete! Your app is ready.")