import requests
import math
import lakebase

# ========================================
# 1RM CALCULATION & COEFFICIENT LOOKUP
# ========================================
# The coefficient table maps the number of reps completed to a percentage of 1RM.
# Example: If you lift 100kg for 5 reps, the coefficient for 5 reps is 87%,
#          so your estimated 1RM = 100 / 0.87 ≈ 115kg.
# This is based on the Epley formula and empirical research.

def get_coefficient(reps):
    """
    Look up the percentage of 1RM that corresponds to a given rep count.
    
    Args:
        reps (int): Number of reps completed (typically 1-20)
    
    Returns:
        float: Coefficient as a decimal (e.g., 0.87 for 5 reps = 87% of 1RM)
    
    Raises:
        ValueError: If no coefficient exists for the given rep count
    """
    row = lakebase.run_query("SELECT percentage FROM coefficients WHERE reps = %s", (reps,))
    if not row:
        raise ValueError(f"No coefficient for {reps} reps")
    return float(row[0]['percentage']) / 100.0

def calculate_1rm(weight, reps):
    """
    Calculate estimated 1RM (one-rep max) from a multi-rep test.
    
    Formula: 1RM = test_weight / coefficient(reps)
    Example: 100kg × 5 reps → 100 / 0.87 = 115kg 1RM
    
    Args:
        weight (float): Weight lifted in kg
        reps (int): Number of reps completed
    
    Returns:
        float: Estimated 1RM in kg
    """
    return float(weight) / get_coefficient(reps)

def round_to_step(value, step=2.5):
    """
    Round a weight to the nearest plate increment (e.g., 2.5kg).
    
    Example: 82.7kg with 2.5kg plates → 82.5kg
             15.6kg with 1.25kg plates → 15.625kg
    
    Args:
        value (float): Calculated weight
        step (float): Plate increment (default 2.5kg for barbells, 1.25kg for dumbbells)
    
    Returns:
        float: Rounded weight
    """
    return round(value / step) * step

# ========================================
# PROGRAM & USER DATA HELPERS
# ========================================
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
    """
    Generate a personalized workout by combining user test results with program template.
    
    Process:
    1. Fetch user's 1RM test results (e.g., Bench Press: 80kg × 5 reps)
    2. Fetch program template for this week (e.g., Week 5: 70% of 1RM)
    3. Calculate target weight: 1RM × percentage
       Example: (80 / 0.87) × 0.70 = 64.4kg → rounded to 65kg
    4. Return list of exercises with calculated weights, sets, reps
    
    Args:
        user_hash (str): SHA-256 hash of user's email
        program_id (int): ID of assigned program
        week (int): Week number in program (1-16 for Strength 2.0)
    
    Returns:
        list[dict]: Workout with calculated weights
            [{'exercise': 'Bench Press', 'weight_kg': 65.0, 'sets': 4, 'reps': 5}, ...]
    """
    tests = get_user_tests(user_hash, program_id)
    template = get_program_template(program_id, week)
    workout = []
    for ex in template:
        if ex['exercise_name'] not in tests:
            continue  # Skip exercises user hasn't tested
        test = tests[ex['exercise_name']]
        
        # Step 1: Calculate 1RM from test results
        one_rm = calculate_1rm(test['test_weight'], test['test_reps'])
        
        # Step 2: Apply program percentage (e.g., 70% for Week 5)
        target = one_rm * (float(ex['percentage_1rm']) / 100.0)
        
        # Step 3: Round to nearest plate increment
        step = float(ex['step_size'] or test['step_size'] or 2.5)
        weight = round_to_step(target, step)
        
        workout.append({
            'exercise': ex['exercise_name'],
            'weight_kg': weight,
            'sets': ex['sets'],
            'reps': ex['reps']
        })
    return workout

# ========================================
# THIRD-PARTY API: WGER EXERCISE DATABASE
# ========================================
# WGER is a free, open-source exercise database with no API key required.
# We fetch unstructured text (descriptions, instructions) and structured metadata
# (muscle groups, equipment) for semantic search and exercise substitution.
WGER_URL = "https://wger.de/api/v2/exerciseinfo/"

def _insert_exercise_with_embedding(info):
    """
    Insert exercise into database with computed embedding.
    
    Args:
        info (dict): Exercise info with keys: name, description, muscles, equipment, instructions, gif_url
    """
    from sentence_transformers import SentenceTransformer
    
    # Validate required fields
    if not info.get('name'):
        raise ValueError("Exercise name is required")
    
    # Compute embedding from description and muscle groups
    text = f"{info['description']} Targets: {', '.join(info.get('muscles', []))}"
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    embedding = model.encode(text).tolist()
    
    # Insert/update cache with embedding
    lakebase.run_write("""
                       INSERT INTO exercise_metadata (name, description, muscles, equipment, instructions, gif_url, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                       ON CONFLICT (name) DO UPDATE SET
                                                        description = EXCLUDED.description,
                                                        muscles = EXCLUDED.muscles,
                                                        equipment = EXCLUDED.equipment,
                                                        instructions = EXCLUDED.instructions,
                                                        gif_url = EXCLUDED.gif_url,
                                                        embedding = EXCLUDED.embedding
                       """, (info['name'], info['description'], info['muscles'], info['equipment'], 
                             info['instructions'], info['gif_url'], str(embedding)))

# FALLBACK: Manual knowledge base for common exercises not in WGER
MANUAL_EXERCISES = {
    'Hyperextension': {
        'name': 'Hyperextension',
        'description': 'Back extension exercise targeting lower back, glutes, and hamstrings. Performed on a hyperextension bench.',
        'muscles': ['Erector spinae', 'Gluteus maximus', 'Hamstrings'],
        'equipment': ['Hyperextension bench'],
        'instructions': 'Position yourself on the hyperextension bench with ankles secured. Lower your torso by bending at the waist. Raise back up to starting position.',
        'gif_url': ''
    },
    'Back Extension': {
        'name': 'Back Extension',
        'description': 'Lower back strengthening exercise targeting erector spinae muscles.',
        'muscles': ['Erector spinae', 'Gluteus maximus'],
        'equipment': ['Hyperextension bench'],
        'instructions': 'Lie face down on hyperextension bench. Lower torso down, then extend back up.',
        'gif_url': ''
    }
}

def fetch_exercise_info(exercise_name):
    # Check cache first
    cached = lakebase.run_query("SELECT * FROM exercise_metadata WHERE name = %s", (exercise_name,))
    if cached:
        return cached[0]

    # Check manual knowledge base
    if exercise_name in MANUAL_EXERCISES:
        info = MANUAL_EXERCISES[exercise_name]
        _insert_exercise_with_embedding(info)
        return info

    # Try WGER API
    url = WGER_URL
    params = {"language": 2, "name": exercise_name}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json().get('results', [])
            if data:
                item = data[0]
                # Validate name before processing
                if not item.get('name'):
                    return {"error": "Exercise found but has no name"}
                
                info = {
                    'name': item.get('name'),
                    'description': item.get('description') or "",
                    'muscles': [m['name'] for m in item.get('muscles', [])],
                    'equipment': [e['name'] for e in item.get('equipment', [])],
                    'instructions': item.get('instructions', ""),
                    'gif_url': item.get('image', [{}])[0].get('image') if item.get('image') else ""
                }
                _insert_exercise_with_embedding(info)
                return info
    except Exception as e:
        pass  # Fall through to error case

    return {"error": f"Exercise '{exercise_name}' not found in database or WGER API"}

# ========================================
# CUSTOMIZATION TOOLS WITH SAFETY GUARDRAILS
# ========================================
def replace_exercise(user_hash, program_id, old_exercise, new_exercise, reason):
    """
    Replace an exercise across the entire program with muscle-group validation.
    
    GUARDRAIL: Prevents unsafe substitutions that target different muscle groups.
    Example:
      - Safe: Barbell Bench Press → Dumbbell Bench Press (both target chest/shoulders/triceps)
      - Unsafe: Squat → Bicep Curl (quads/glutes vs biceps - NO OVERLAP)
    
    Args:
        user_hash (str): User identifier
        program_id (int): Program ID
        old_exercise (str): Exercise to replace
        new_exercise (str): Replacement exercise
        reason (str): User's reason (e.g., "No barbell available", "Elbow pain")
    
    Returns:
        dict: {"status": "success"} or {"warning": "muscle group mismatch"} or {"error": ...}
    """
    # GUARDRAIL: Validate muscle group overlap using WGER metadata
    old_info = fetch_exercise_info(old_exercise)
    new_info = fetch_exercise_info(new_exercise)
    
    if 'error' in old_info or 'error' in new_info:
        return {"error": "One or both exercises not found in database."}
    
    old_muscles = set(old_info.get('muscles', []))
    new_muscles = set(new_info.get('muscles', []))
    
    # Check for muscle overlap (set intersection)
    if not old_muscles & new_muscles:
        return {"warning": "These exercises target different muscle groups. Are you sure?"}
    
    # Store override in audit log
    lakebase.run_write("""
                       INSERT INTO user_exercise_overrides (user_id_hash, program_id, old_exercise_name, new_exercise_name, reason)
                       VALUES (%s, %s, %s, %s, %s)
                       """, (user_hash, program_id, old_exercise, new_exercise, reason))
    return {"status": "success", "message": f"Replaced {old_exercise} with {new_exercise}."}

def adjust_intensity(user_hash, program_id, exercise, change_percent):
    """
    Adjust the intensity (% of 1RM) for a specific exercise with safety bounds.
    
    GUARDRAILS:
      - Maximum 110% of 1RM (risk of injury/failure)
      - Minimum 50% of 1RM (insufficient stimulus for strength gains)
    
    Use cases:
      - Progressive overload: User finds 70% too easy → increase to 75-80%
      - Deload: User is fatigued/recovering → decrease to 60-65%
    
    Args:
        user_hash (str): User identifier
        program_id (int): Program ID
        exercise (str): Exercise name
        change_percent (float): Delta to apply (e.g., +5, -10)
    
    Returns:
        dict: {"status": "success"} or {"error": "out of bounds"}
    """
    # Fetch current intensity from program template
    rows = lakebase.run_query("""
                              SELECT percentage_1rm FROM program_exercises
                              WHERE program_id = %s AND exercise_name = %s
                              """, (program_id, exercise))
    if not rows:
        return {"error": "Exercise not found in program"}
    
    current = rows[0]['percentage_1rm']
    new_pct = current + change_percent
    
    # GUARDRAIL: Enforce safe intensity bounds
    if new_pct > 110:
        return {"error": "Cannot exceed 110% of 1RM. Risk of injury. Adjust to 110%?"}
    if new_pct < 50:
        return {"error": "Below 50% is too light for strength gains. Minimum is 50%."}
    
    # Store user-specific override (affects all weeks of this exercise)
    lakebase.run_write("""
                       INSERT INTO intensity_overrides (user_id_hash, program_id, exercise_name, new_percentage)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (user_id_hash, program_id, exercise_name) DO UPDATE SET new_percentage = EXCLUDED.new_percentage
                       """, (user_hash, program_id, exercise, new_pct))
    return {"status": "success", "message": f"Intensity for {exercise} adjusted to {new_pct}% of 1RM."}