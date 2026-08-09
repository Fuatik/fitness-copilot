# Databricks notebook source
# MAGIC %md
# MAGIC # Ingest Fitness Programs & Embed Unstructured Data
# MAGIC
# MAGIC This notebook populates Lakebase with:
# MAGIC - Coefficient table (reps → % of 1RM)
# MAGIC - Strength Program 2.0 template
# MAGIC - Unstructured exercise descriptions from WGER API (no key)
# MAGIC - Embeddings for program descriptions and exercise descriptions

# COMMAND ----------

# MAGIC %pip install -q psycopg2-binary sentence-transformers requests

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import base64
import psycopg2
from psycopg2.extras import RealDictCursor
from databricks.sdk import WorkspaceClient
from sentence_transformers import SentenceTransformer
import requests

w = WorkspaceClient()

# Get Lakebase URL from secrets
secret = w.secrets.get_secret(scope="database", key="lakebase-url")
LAKEBASE_URL = base64.b64decode(secret.value).decode("utf-8")

def get_conn():
    return psycopg2.connect(LAKEBASE_URL, cursor_factory=RealDictCursor)

# ---- 1. Create tables ----
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS coefficients (
                                                                reps INTEGER PRIMARY KEY,
                                                                percentage DECIMAL(5,2) NOT NULL
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS workout_programs (
                                                                    id SERIAL PRIMARY KEY,
                                                                    name TEXT NOT NULL,
                                                                    version TEXT,
                                                                    description TEXT,
                                                                    target TEXT,
                                                                    periodization_type TEXT,
                                                                    embedding VECTOR(384)
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS program_exercises (
                                                                     id SERIAL PRIMARY KEY,
                                                                     program_id INTEGER REFERENCES workout_programs(id),
                                                                     day INTEGER NOT NULL,
                                                                     exercise_name TEXT NOT NULL,
                                                                     week INTEGER NOT NULL,
                                                                     percentage_1rm DECIMAL(5,2),
                                                                     sets INTEGER,
                                                                     reps INTEGER,
                                                                     step_size DECIMAL(5,2)
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS exercise_metadata (
                                                                     name TEXT PRIMARY KEY,
                                                                     description TEXT,
                                                                     muscles TEXT[],
                                                                     equipment TEXT[],
                                                                     instructions TEXT,
                                                                     gif_url TEXT,
                                                                     embedding VECTOR(384)
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                                                                 user_id_hash TEXT PRIMARY KEY,
                                                                 age INTEGER,
                                                                 height_cm INTEGER,
                                                                 weight_kg DECIMAL(5,2),
                                                                 experience TEXT,
                                                                 limitations TEXT,
                                                                 created_at TIMESTAMP DEFAULT now()
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_programs (
                                                                 user_id_hash TEXT PRIMARY KEY,
                                                                 program_id INTEGER,
                                                                 frequency INTEGER,
                                                                 current_week INTEGER DEFAULT 1,
                                                                 assigned_at TIMESTAMP DEFAULT now()
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_tests (
                                                              user_id_hash TEXT,
                                                              program_id INTEGER,
                                                              exercise_name TEXT,
                                                              test_weight DECIMAL(8,2),
                                                              test_reps INTEGER,
                                                              step_size DECIMAL(5,2),
                                                              test_date DATE DEFAULT now(),
                                                              PRIMARY KEY (user_id_hash, program_id, exercise_name)
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_workouts (
                                                                 id SERIAL PRIMARY KEY,
                                                                 user_id_hash TEXT,
                                                                 exercise_name TEXT,
                                                                 weight_kg DECIMAL(8,2),
                                                                 reps_done INTEGER,
                                                                 logged_at TIMESTAMP DEFAULT now()
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_exercise_overrides (
                                                                           id SERIAL PRIMARY KEY,
                                                                           user_id_hash TEXT,
                                                                           program_id INTEGER,
                                                                           old_exercise_name TEXT,
                                                                           new_exercise_name TEXT,
                                                                           reason TEXT,
                                                                           created_at TIMESTAMP DEFAULT now()
                    )
                    """)
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS intensity_overrides (
                                                                       user_id_hash TEXT,
                                                                       program_id INTEGER,
                                                                       exercise_name TEXT,
                                                                       new_percentage DECIMAL(5,2),
                                                                       PRIMARY KEY (user_id_hash, program_id, exercise_name)
                    )
                    """)
        conn.commit()
print("✅ Tables created/verified.")

# ---- 2. Insert coefficients ----
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

# ---- 3. Insert Strength Program 2.0 ----
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

# ---- 4. Fetch unstructured data from WGER (no key) ----
COMMON_EXERCISES = [
    "bench press", "squat", "deadlift", "overhead press",
    "bent over row", "pull up", "dip", "lunge",
    "leg press", "lat pulldown", "seated cable row"
]

def fetch_wger_description(name):
    try:
        url = f"https://wger.de/api/v2/exerciseinfo/?language=2&name={name}"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json().get('results', [])
        if not data:
            return None
        item = data[0]
        return {
            'name': item.get('name'),
            'description': item.get('description') or "",
            'muscles': [m['name'] for m in item.get('muscles', [])],
            'equipment': [e['name'] for e in item.get('equipment', [])],
            'instructions': item.get('instructions', ""),
            'gif_url': item.get('image', [{}])[0].get('image') if item.get('image') else ""
        }
    except Exception as e:
        print(f"Error fetching {name}: {e}")
        return None

with get_conn() as conn:
    with conn.cursor() as cur:
        for ex_name in COMMON_EXERCISES:
            data = fetch_wger_description(ex_name)
            if data:
                cur.execute("""
                            INSERT INTO exercise_metadata (name, description, muscles, equipment, instructions, gif_url)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (name) DO UPDATE SET
                                                             description = EXCLUDED.description,
                                                             muscles = EXCLUDED.muscles,
                                                             equipment = EXCLUDED.equipment,
                                                             instructions = EXCLUDED.instructions,
                                                             gif_url = EXCLUDED.gif_url
                            """, (data['name'], data['description'], data['muscles'], data['equipment'], data['instructions'], data['gif_url']))
        conn.commit()
print("✅ Pre-fetched unstructured exercise descriptions from WGER.")

# ---- 5. Embed program descriptions and exercise descriptions ----
model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# Embed programs
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
        conn.commit()
print("✅ Program descriptions embedded.")

# Embed exercise descriptions (unstructured text)
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT name, description FROM exercise_metadata WHERE description IS NOT NULL")
        rows = cur.fetchall()
        for row in rows:
            vec = model.encode(row['description']).tolist()
            cur.execute(
                "UPDATE exercise_metadata SET embedding = %s::vector WHERE name = %s",
                (str(vec), row['name'])
            )
        conn.commit()
print("✅ Exercise descriptions embedded (unstructured data).")

print("\n🎉 Pipeline complete! Your app is ready.")

# COMMAND ----------

# DBTITLE 1,Add Beginner Program and Test Users
# ---- 6. Insert Beginner Program 3.0 (more program variety) ----
beginner_desc = """
Beginner Program 3.0 – a 12-week foundation-building program for lifters with less than 6 months experience.
Focuses on technique development, neural adaptation, and gradual load progression starting at 60% of 1RM.
"""
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
                    INSERT INTO workout_programs (name, version, description, target, periodization_type)
                    VALUES ('Beginner Program 3.0', '3.0', %s, 'foundation', 'linear')
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """, (beginner_desc,))
        row = cur.fetchone()
        if row:
            beginner_id = row['id']
            # Week 1: Start at 60% for technique focus
            beginner_exercises = [
                ('Bench Press', 1, 60.0, 3, 8, 2.5),
                ('Goblet Squat', 1, 60.0, 3, 8, 2.5),
                ('Dumbbell Row', 2, 60.0, 3, 8, 2.5),
                ('Romanian Deadlift', 2, 60.0, 3, 8, 2.5),
                ('Dumbbell Press', 3, 60.0, 3, 8, 2.5),
                ('Lat Pulldown', 3, 60.0, 3, 8, 2.5),
            ]
            for ex in beginner_exercises:
                cur.execute("""
                            INSERT INTO program_exercises (program_id, day, exercise_name, week, percentage_1rm, sets, reps, step_size)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (beginner_id, ex[1], ex[0], 1, ex[2], ex[3], ex[4], ex[5]))
            # Weeks 2-3: Progress to 65%
            for week in [2, 3]:
                for ex in beginner_exercises:
                    cur.execute("""
                                INSERT INTO program_exercises (program_id, day, exercise_name, week, percentage_1rm, sets, reps, step_size)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                """, (beginner_id, ex[1], ex[0], week, 65.0, ex[3], ex[4], ex[5]))
            conn.commit()
            print(f"✅ Inserted Beginner Program 3.0 with id {beginner_id}.")
        else:
            print("ℹ️ Beginner Program already exists, skipping.")

# ---- 7. Insert Test Users for Demo ----
import hashlib

def hash_email(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()

# Test User 1: Intermediate lifter
test_user1_email = "alice@example.com"
test_user1_hash = hash_email(test_user1_email)

with get_conn() as conn:
    with conn.cursor() as cur:
        # Profile
        cur.execute("""
                    INSERT INTO user_profiles (user_id_hash, age, height_cm, weight_kg, experience, limitations)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id_hash) DO NOTHING
                    """, (test_user1_hash, 28, 165, 68.0, 'intermediate', ''))
        
        # Get program ID for Strength 2.0
        cur.execute("SELECT id FROM workout_programs WHERE version = '2.0' LIMIT 1")
        prog = cur.fetchone()
        if prog:
            prog_id = prog['id']
            # Assign program
            cur.execute("""
                        INSERT INTO user_programs (user_id_hash, program_id, frequency, current_week)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (user_id_hash) DO UPDATE SET program_id = EXCLUDED.program_id
                        """, (test_user1_hash, prog_id, 3, 5))
            
            # Test results (1RM estimates)
            test_data = [
                ('Bench Press', 80.0, 5, 2.5),  # ~92kg 1RM
                ('Back Squat', 100.0, 5, 2.5),  # ~115kg 1RM
                ('Bent Over Row', 70.0, 5, 2.5),  # ~80kg 1RM
                ('Deadlift', 120.0, 5, 2.5),  # ~138kg 1RM
                ('Seated Dumbbell Press', 25.0, 5, 1.25),  # ~29kg 1RM per dumbbell
                ('Lat Pulldown', 60.0, 5, 2.5),  # ~69kg 1RM
            ]
            for ex_name, weight, reps, step in test_data:
                cur.execute("""
                            INSERT INTO user_tests (user_id_hash, program_id, exercise_name, test_weight, test_reps, step_size)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (user_id_hash, program_id, exercise_name) DO NOTHING
                            """, (test_user1_hash, prog_id, ex_name, weight, reps, step))
        conn.commit()
print(f"✅ Test User 1: {test_user1_email} (intermediate, week 5)")

# Test User 2: Beginner
test_user2_email = "bob@example.com"
test_user2_hash = hash_email(test_user2_email)

with get_conn() as conn:
    with conn.cursor() as cur:
        # Profile
        cur.execute("""
                    INSERT INTO user_profiles (user_id_hash, age, height_cm, weight_kg, experience, limitations)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id_hash) DO NOTHING
                    """, (test_user2_hash, 22, 178, 75.0, 'beginner', ''))
        
        # Get program ID for Beginner 3.0
        cur.execute("SELECT id FROM workout_programs WHERE version = '3.0' LIMIT 1")
        prog = cur.fetchone()
        if prog:
            prog_id = prog['id']
            # Assign program
            cur.execute("""
                        INSERT INTO user_programs (user_id_hash, program_id, frequency, current_week)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (user_id_hash) DO UPDATE SET program_id = EXCLUDED.program_id
                        """, (test_user2_hash, prog_id, 3, 1))
            
            # Test results (lighter weights for beginner)
            test_data = [
                ('Bench Press', 40.0, 8, 2.5),  # ~50kg 1RM
                ('Goblet Squat', 20.0, 8, 2.5),  # ~25kg 1RM
                ('Dumbbell Row', 15.0, 8, 1.25),  # ~19kg 1RM per hand
                ('Romanian Deadlift', 50.0, 8, 2.5),  # ~62.5kg 1RM
                ('Dumbbell Press', 12.0, 8, 1.25),  # ~15kg 1RM per dumbbell
                ('Lat Pulldown', 35.0, 8, 2.5),  # ~44kg 1RM
            ]
            for ex_name, weight, reps, step in test_data:
                cur.execute("""
                            INSERT INTO user_tests (user_id_hash, program_id, exercise_name, test_weight, test_reps, step_size)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (user_id_hash, program_id, exercise_name) DO NOTHING
                            """, (test_user2_hash, prog_id, ex_name, weight, reps, step))
        conn.commit()
print(f"✅ Test User 2: {test_user2_email} (beginner, week 1)")

# Test User 3: User with back limitations (for No-Axial-Load recommendation)
test_user3_email = "charlie@example.com"
test_user3_hash = hash_email(test_user3_email)

with get_conn() as conn:
    with conn.cursor() as cur:
        # Profile with limitations
        cur.execute("""
                    INSERT INTO user_profiles (user_id_hash, age, height_cm, weight_kg, experience, limitations)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id_hash) DO NOTHING
                    """, (test_user3_hash, 35, 175, 82.0, 'intermediate', 'Lower back pain, herniated disc'))
        conn.commit()
print(f"✅ Test User 3: {test_user3_email} (back limitations, no program assigned yet)")

print("\n🎉 Test users created! Ready for agent demo.")
print(f"   • alice@example.com: Intermediate, Strength 2.0, Week 5")
print(f"   • bob@example.com: Beginner, Beginner 3.0, Week 1")
print(f"   • charlie@example.com: Intermediate with back issues (needs program recommendation)")