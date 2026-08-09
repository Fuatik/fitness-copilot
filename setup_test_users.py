# Databricks notebook source
# DBTITLE 1,Setup Test Users and Demo Data
# MAGIC %md
# MAGIC # Setup Test Users and Demo Data
# MAGIC
# MAGIC **⚠️ RUN THIS ONCE** after initial pipeline execution.
# MAGIC
# MAGIC This notebook creates:
# MAGIC * **Beginner Program 3.0** - A 12-week foundation program for new lifters
# MAGIC * **3 Test Users** for MCP agent demo:
# MAGIC   * alice@example.com - Intermediate, Strength 2.0, Week 5
# MAGIC   * bob@example.com - Beginner, Beginner 3.0, Week 1  
# MAGIC   * charlie@example.com - Intermediate with back issues (no program assigned)
# MAGIC
# MAGIC **Prerequisites:**
# MAGIC * Tables created via `sql/01_setup_core_tables.sql` and `sql/02_setup_user_tables.sql`
# MAGIC * Core ETL pipeline `spark-pipeline/ingest_and_embed.py` executed successfully

# COMMAND ----------

# DBTITLE 1,Install Dependencies
# MAGIC %pip install -q 'databricks-sdk>=0.118.0'

# COMMAND ----------

# DBTITLE 1,Setup Connection
import base64
import hashlib
import psycopg2
from psycopg2.extras import RealDictCursor
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Get Lakebase URL from secrets
secret = w.secrets.get_secret(scope="database", key="lakebase-url")
LAKEBASE_URL = base64.b64decode(secret.value).decode("utf-8")

def get_conn():
    return psycopg2.connect(LAKEBASE_URL, cursor_factory=RealDictCursor)

def hash_email(email):
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()

# COMMAND ----------

# DBTITLE 1,Insert Beginner Program 3.0
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

# COMMAND ----------

# DBTITLE 1,Create Test User 1: Alice (Intermediate)
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

# COMMAND ----------

# DBTITLE 1,Create Test User 2: Bob (Beginner)
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

# COMMAND ----------

# DBTITLE 1,Create Test User 3: Charlie (Back Limitations)
# Test User 3: User with back limitations (for program recommendation demo)
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

# COMMAND ----------

