import requests
import math
import lakebase

# ---- Coefficient (reps -> % of 1RM) ----
def get_coefficient(reps):
    row = lakebase.run_query("SELECT percentage FROM coefficients WHERE reps = %s", (reps,))
    if not row:
        raise ValueError(f"No coefficient for {reps} reps")
    return row[0]['percentage'] / 100.0

def calculate_1rm(weight, reps):
    return weight / get_coefficient(reps)

def round_to_step(value, step=2.5):
    return round(value / step) * step

# ---- Program & user helpers ----
def get_user_program(user_hash):
    row = lakebase.run_query("SELECT program_id, current_week FROM user_programs WHERE user_id_hash = %s", (user_hash,))
    return row[0] if row else None

def get_program_template(program_id, week):
    rows = lakebase.run_query("""
                              SELECT exercise_name, percentage_1rm, sets, reps, step_size
                              FROM program_exercises
                              WHERE program_id = %s AND week = %s
                              """, (program_id, week))
    return rows

def get_user_tests(user_hash, program_id):
    rows = lakebase.run_query("""
                              SELECT exercise_name, test_weight, test_reps, step_size
                              FROM user_tests
                              WHERE user_id_hash = %s AND program_id = %s
                              """, (user_hash, program_id))
    return {r['exercise_name']: r for r in rows}

def generate_workout(user_hash, program_id, week):
    tests = get_user_tests(user_hash, program_id)
    template = get_program_template(program_id, week)
    workout = []
    for ex in template:
        if ex['exercise_name'] not in tests:
            continue
        test = tests[ex['exercise_name']]
        one_rm = calculate_1rm(test['test_weight'], test['test_reps'])
        target = one_rm * (ex['percentage_1rm'] / 100.0)
        step = ex['step_size'] or test['step_size'] or 2.5
        weight = round_to_step(target, step)
        workout.append({
            'exercise': ex['exercise_name'],
            'weight_kg': weight,
            'sets': ex['sets'],
            'reps': ex['reps']
        })
    return workout

# ---- WGER API (no key, free) ----
WGER_URL = "https://wger.de/api/v2/exerciseinfo/"

def fetch_exercise_info(exercise_name):
    # Check cache first
    cached = lakebase.run_query("SELECT * FROM exercise_metadata WHERE name = %s", (exercise_name,))
    if cached:
        return cached[0]

    url = WGER_URL
    params = {"language": 2, "name": exercise_name}
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        return {"error": "API request failed"}

    data = resp.json().get('results', [])
    if not data:
        return {"error": "Exercise not found"}

    item = data[0]
    info = {
        'name': item.get('name'),
        'description': item.get('description') or "",
        'muscles': [m['name'] for m in item.get('muscles', [])],
        'equipment': [e['name'] for e in item.get('equipment', [])],
        'instructions': item.get('instructions', ""),
        'gif_url': item.get('image', [{}])[0].get('image') if item.get('image') else ""
    }
    # Insert/update cache
    lakebase.run_write("""
                       INSERT INTO exercise_metadata (name, description, muscles, equipment, instructions, gif_url)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (name) DO UPDATE SET
                                                        description = EXCLUDED.description,
                                                        muscles = EXCLUDED.muscles,
                                                        equipment = EXCLUDED.equipment,
                                                        instructions = EXCLUDED.instructions,
                                                        gif_url = EXCLUDED.gif_url
                       """, (info['name'], info['description'], info['muscles'], info['equipment'], info['instructions'], info['gif_url']))
    return info

# ---- Customization tools with guardrails ----
def replace_exercise(user_hash, program_id, old_exercise, new_exercise, reason):
    # Guard: check muscle groups
    old_info = fetch_exercise_info(old_exercise)
    new_info = fetch_exercise_info(new_exercise)
    if 'error' in old_info or 'error' in new_info:
        return {"error": "One or both exercises not found in database."}
    old_muscles = set(old_info.get('muscles', []))
    new_muscles = set(new_info.get('muscles', []))
    if not old_muscles & new_muscles:
        return {"warning": "These exercises target different muscle groups. Are you sure?"}
    # Store override
    lakebase.run_write("""
                       INSERT INTO user_exercise_overrides (user_id_hash, program_id, old_exercise_name, new_exercise_name, reason)
                       VALUES (%s, %s, %s, %s, %s)
                       """, (user_hash, program_id, old_exercise, new_exercise, reason))
    return {"status": "success", "message": f"Replaced {old_exercise} with {new_exercise}."}

def adjust_intensity(user_hash, program_id, exercise, change_percent):
    # Get current percentage from program_exercises
    rows = lakebase.run_query("""
                              SELECT percentage_1rm FROM program_exercises
                              WHERE program_id = %s AND exercise_name = %s
                              """, (program_id, exercise))
    if not rows:
        return {"error": "Exercise not found in program"}
    current = rows[0]['percentage_1rm']
    new_pct = current + change_percent
    if new_pct > 110:
        return {"error": "Cannot exceed 110% of 1RM. Adjust to 110%?"}
    if new_pct < 50:
        return {"error": "Below 50% is too light for strength gains."}
    # Store override for all weeks of this exercise
    lakebase.run_write("""
                       INSERT INTO intensity_overrides (user_id_hash, program_id, exercise_name, new_percentage)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (user_id_hash, program_id, exercise_name) DO UPDATE SET new_percentage = EXCLUDED.new_percentage
                       """, (user_hash, program_id, exercise, new_pct))
    return {"status": "success", "message": f"Intensity for {exercise} adjusted to {new_pct}% of 1RM."}