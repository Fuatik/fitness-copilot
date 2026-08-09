import os
import hashlib
from flask import Flask, request, jsonify, render_template
import lakebase
import fitness_broker

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

def hash_email(email):
    """Hash email address using SHA-256 for privacy."""
    if not email:
        return ''
    return hashlib.sha256(email.encode('utf-8')).hexdigest()

@app.route("/")
def index():
    # Get authenticated user from Databricks context
    # In Databricks Apps, user email is available in request headers
    user_email = (
        request.headers.get('X-Forwarded-Email') or
        request.headers.get('X-Forwarded-User') or
        request.args.get('user_email', '')
    )
    # Hash the email for storage but display the actual email
    user_hash = hash_email(user_email)
    return render_template("index.html", user_email=user_email, user_hash=user_hash)

@app.route("/api/recommend_program", methods=["POST"])
def api_recommend_program():
    data = request.get_json()
    experience = data.get('experience', 'beginner')
    limitations = data.get('limitations', '')
    
    # Program recommendation logic
    if limitations and ('back' in limitations.lower() or 'spine' in limitations.lower()):
        version = '3.0'  # Intermediate program with back-friendly modifications
    else:
        mapping = {'beginner': '2.0', 'intermediate': '3.0', 'advanced': '3.0'}
        version = mapping.get(experience, '2.0')
    
    prog = lakebase.run_query("SELECT id, name, description FROM workout_programs WHERE version = %s", (version,))
    if not prog:
        return jsonify({"error": "Program not found"}), 404
    
    return jsonify({
        "program_id": prog[0]['id'],
        "name": prog[0]['name'],
        "description": prog[0]['description'],
        "reasoning": f"Based on your experience ({experience}), this program is best."
    })



@app.route("/api/assign_program", methods=["POST"])
def api_assign_program():
    """Assign a recommended program to a user."""
    data = request.get_json()
    user_hash = data.get('user_hash')
    program_id = data.get('program_id')
    days_per_week = data.get('days_per_week', 3)  # Default to 3 days
    
    if not user_hash or not program_id:
        return jsonify({"error": "Missing user_hash or program_id"}), 400
    
    # Check if program exists
    prog = lakebase.run_query("SELECT id, name FROM workout_programs WHERE id = %s", (program_id,))
    if not prog:
        return jsonify({"error": "Program not found"}), 404
    
    # Insert or update user program assignment (using 'frequency' column that exists in DB)
    lakebase.run_write("""
        INSERT INTO user_programs (user_id_hash, program_id, frequency)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id_hash) 
        DO UPDATE SET program_id = EXCLUDED.program_id, frequency = EXCLUDED.frequency
    """, (user_hash, program_id, days_per_week))
    
    return jsonify({
        "success": True,
        "message": f"Assigned program '{prog[0]['name']}' to user"
    })

@app.route("/api/enter_test_results", methods=["POST"])
def api_enter_test_results():
    """Save test results for a user (weight and reps, not calculated 1RM)."""
    data = request.get_json()
    user_hash = data.get('user_hash')
    exercise_name = data.get('exercise_name')
    test_weight = data.get('test_weight')  # Changed from one_rm
    test_reps = data.get('test_reps', 5)  # Default to 5 reps
    step_size = data.get('step_size', 2.5)  # Default plate increment
    
    if not user_hash or not exercise_name or test_weight is None:
        return jsonify({"error": "Missing required fields"}), 400
    
    # Get user's program_id
    prog = lakebase.run_query("SELECT program_id FROM user_programs WHERE user_id_hash = %s", (user_hash,))
    if not prog:
        return jsonify({"error": "No program assigned"}), 400
    program_id = prog[0]['program_id']
    
    # Insert or update test result in user_tests table (not user_test_results)
    lakebase.run_write("""
        INSERT INTO user_tests (user_id_hash, program_id, exercise_name, test_weight, test_reps, step_size, test_date)
        VALUES (%s, %s, %s, %s, %s, %s, CURRENT_DATE)
        ON CONFLICT (user_id_hash, program_id, exercise_name) 
        DO UPDATE SET test_weight = EXCLUDED.test_weight, test_reps = EXCLUDED.test_reps, 
                      step_size = EXCLUDED.step_size, test_date = EXCLUDED.test_date
    """, (user_hash, program_id, exercise_name, float(test_weight), int(test_reps), float(step_size)))
    
    return jsonify({
        "success": True,
        "exercise": exercise_name,
        "test_weight": test_weight,
        "test_reps": test_reps
    })

@app.route("/api/user_status")
def api_user_status():
    """Check if user has completed onboarding and get their current state."""
    user_hash = request.args.get('user_hash')
    
    if not user_hash:
        return jsonify({"error": "Missing user_hash"}), 400
    
    print(f"[API] /api/user_status called for user_hash: {user_hash[:16]}...")
    
    # Check if user has a program assigned
    prog = lakebase.run_query(
        "SELECT program_id, current_week FROM user_programs WHERE user_id_hash = %s", 
        (user_hash,)
    )
    
    if not prog:
        print(f"[API] No program found - returning step 1 (onboarding)")
        return jsonify({
            "has_program": False,
            "has_test_results": False,
            "step": 1  # Onboarding
        })
    
    program_id = prog[0]['program_id']
    current_week = prog[0].get('current_week', 1)
    print(f"[API] Found program_id={program_id}, current_week={current_week}")
    
    # Check if user has test results (from user_tests table, not user_test_results)
    test_results = lakebase.run_query(
        "SELECT COUNT(*) as count FROM user_tests WHERE user_id_hash = %s AND program_id = %s",
        (user_hash, program_id)
    )
    has_tests = test_results and test_results[0]['count'] > 0
    print(f"[API] Test results count: {test_results[0]['count'] if test_results else 0}, has_tests={has_tests}")
    
    # Get program info
    program_info = lakebase.run_query(
        "SELECT id, name, description FROM workout_programs WHERE id = %s",
        (program_id,)
    )
    
    step = 3 if has_tests else 2
    print(f"[API] Returning step={step} (has_tests={has_tests})")
    
    result = {
        "has_program": True,
        "has_test_results": has_tests,
        "step": step,  # Skip to program view if tests done, otherwise test week
        "current_week": current_week,
        "program": {
            "program_id": program_info[0]['id'],
            "name": program_info[0]['name'],
            "description": program_info[0]['description']
        } if program_info else None
    }
    print(f"[API] Full response: {result}")
    return jsonify(result)

@app.route("/api/available_weeks")
def api_available_weeks():
    """Get list of weeks that have programmed exercises for a user's program."""
    user_hash = request.args.get('user_hash')
    
    if not user_hash:
        return jsonify({"error": "Missing user_hash"}), 400
    
    # Get user's program
    prog = lakebase.run_query("SELECT program_id FROM user_programs WHERE user_id_hash = %s", (user_hash,))
    if not prog:
        return jsonify({"error": "No program assigned"}), 400
    
    program_id = prog[0]['program_id']
    
    # Query distinct weeks that have exercises in this program
    weeks = lakebase.run_query(
        "SELECT DISTINCT week FROM program_exercises WHERE program_id = %s ORDER BY week",
        (program_id,)
    )
    
    # Extract week numbers into a simple list
    available_weeks = [row['week'] for row in weeks] if weeks else []
    
    return jsonify({
        "program_id": program_id,
        "available_weeks": available_weeks
    })

@app.route("/api/workout")
def api_workout():
    user_hash = request.args.get('user_hash')
    week = int(request.args.get('week', 1))
    
    if not user_hash:
        return jsonify({"error": "Missing user_hash"}), 400
    
    prog = lakebase.run_query("SELECT program_id FROM user_programs WHERE user_id_hash = %s", (user_hash,))
    if not prog:
        return jsonify({"error": "No program assigned. Please complete onboarding first."}), 400
    
    workout = fitness_broker.generate_workout(user_hash, prog[0]['program_id'], week)
    return jsonify({"week": week, "exercises": workout})

@app.route("/api/exercise/<name>")
def api_exercise(name):
    return jsonify(fitness_broker.fetch_exercise_info(name))

@app.route("/api/search_exercises")
def api_search():
    query = request.args.get('q', '')
    if not query:
        return jsonify([])
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    vec = model.encode(query).tolist()
    rows = lakebase.run_query("""
                              SELECT name, description,
                                     1 - (embedding <=> %s::vector) AS similarity
                              FROM exercise_metadata
                              WHERE embedding IS NOT NULL
                              ORDER BY embedding <=> %s::vector
                              LIMIT 10
                              """, (str(vec), str(vec)))
    return jsonify(rows)

@app.route("/api/custom_exercises", methods=["POST"])
def api_add_custom_exercise():
    """Add a custom exercise to user's program."""
    data = request.get_json()
    user_hash = data.get('user_hash')
    week = data.get('week')
    exercise_name = data.get('exercise_name')
    sets = data.get('sets', 3)
    reps = data.get('reps', '8-10')
    intensity = data.get('intensity')  # % of 1RM
    weight_override = data.get('weight_override')  # Manual weight
    notes = data.get('notes', '')
    
    if not user_hash or not week or not exercise_name:
        return jsonify({"error": "Missing required fields"}), 400
    
    # Get user's program
    prog = lakebase.run_query("SELECT program_id FROM user_programs WHERE user_id_hash = %s", (user_hash,))
    if not prog:
        return jsonify({"error": "No program assigned"}), 400
    
    program_id = prog[0]['program_id']
    
    # Insert custom exercise
    lakebase.run_write("""
        INSERT INTO user_custom_exercises 
        (user_id_hash, program_id, week, exercise_name, sets, reps, intensity, weight_override, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (user_hash, program_id, week, exercise_name, sets, reps, intensity, weight_override, notes))
    
    return jsonify({
        "success": True,
        "message": f"Added {exercise_name} to week {week}"
    })

@app.route("/api/custom_exercises/<int:exercise_id>", methods=["PUT"])
def api_update_custom_exercise(exercise_id):
    """Update a custom exercise."""
    data = request.get_json()
    user_hash = data.get('user_hash')
    
    if not user_hash:
        return jsonify({"error": "Missing user_hash"}), 400
    
    # Build update query dynamically based on provided fields
    update_fields = []
    params = []
    
    if 'exercise_name' in data:
        update_fields.append("exercise_name = %s")
        params.append(data['exercise_name'])
    if 'sets' in data:
        update_fields.append("sets = %s")
        params.append(data['sets'])
    if 'reps' in data:
        update_fields.append("reps = %s")
        params.append(data['reps'])
    if 'intensity' in data:
        update_fields.append("intensity = %s")
        params.append(data['intensity'])
    if 'weight_override' in data:
        update_fields.append("weight_override = %s")
        params.append(data['weight_override'])
    if 'notes' in data:
        update_fields.append("notes = %s")
        params.append(data['notes'])
    
    if not update_fields:
        return jsonify({"error": "No fields to update"}), 400
    
    update_fields.append("updated_at = CURRENT_TIMESTAMP")
    params.extend([exercise_id, user_hash])
    
    lakebase.run_write(f"""
        UPDATE user_custom_exercises 
        SET {', '.join(update_fields)}
        WHERE id = %s AND user_id_hash = %s
    """, tuple(params))
    
    return jsonify({"success": True, "message": "Exercise updated"})

@app.route("/api/custom_exercises/<int:exercise_id>", methods=["DELETE"])
def api_delete_custom_exercise(exercise_id):
    """Delete a custom exercise."""
    user_hash = request.args.get('user_hash')
    
    if not user_hash:
        return jsonify({"error": "Missing user_hash"}), 400
    
    lakebase.run_write(
        "DELETE FROM user_custom_exercises WHERE id = %s AND user_id_hash = %s",
        (exercise_id, user_hash)
    )
    
    return jsonify({"success": True, "message": "Exercise deleted"})

@app.route("/api/programs")
def api_list_programs():
    """List all available workout programs."""
    programs = lakebase.run_query("""
        SELECT id, name, version, description, target, periodization_type
        FROM workout_programs 
        ORDER BY name
    """)
    return jsonify(programs or [])

@app.route("/api/switch_program", methods=["POST"])
def api_switch_program():
    """Switch user to a different program (resets progress)."""
    data = request.get_json()
    user_hash = data.get('user_hash')
    new_program_id = data.get('program_id')
    
    if not user_hash or not new_program_id:
        return jsonify({"error": "Missing required fields"}), 400
    
    # Verify program exists
    prog = lakebase.run_query("SELECT id, name FROM workout_programs WHERE id = %s", (new_program_id,))
    if not prog:
        return jsonify({"error": "Program not found"}), 404
    
    # Update user's program and reset week to 1
    lakebase.run_write("""
        UPDATE user_programs 
        SET program_id = %s, current_week = 1 
        WHERE user_id_hash = %s
    """, (new_program_id, user_hash))
    
    # Delete old test results (they belong to the old program)
    lakebase.run_write(
        "DELETE FROM user_tests WHERE user_id_hash = %s",
        (user_hash,)
    )
    
    # Delete old custom exercises
    lakebase.run_write(
        "DELETE FROM user_custom_exercises WHERE user_id_hash = %s",
        (user_hash,)
    )
    
    return jsonify({
        "success": True,
        "message": f"Switched to {prog[0]['name']}",
        "program_name": prog[0]['name'],
        "requires_test_week": True
    })


if __name__ == "__main__":
    port = int(os.getenv("FLASK_RUN_PORT", 8001))
    app.run(debug=True, host="0.0.0.0", port=port)