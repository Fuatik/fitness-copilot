import os
from flask import Flask, request, jsonify, render_template
import lakebase
import fitness_broker

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

@app.route("/")
def index():
    user_hash = request.args.get('user_hash', '')
    return render_template("index.html", user_hash=user_hash)

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
    
    if not user_hash or not program_id:
        return jsonify({"error": "Missing user_hash or program_id"}), 400
    
    # Check if program exists
    prog = lakebase.run_query("SELECT id, name FROM workout_programs WHERE id = %s", (program_id,))
    if not prog:
        return jsonify({"error": "Program not found"}), 404
    
    # Insert or update user program assignment
    lakebase.run_query("""
        INSERT INTO user_programs (user_id_hash, program_id, start_date)
        VALUES (%s, %s, CURRENT_DATE)
        ON CONFLICT (user_id_hash) 
        DO UPDATE SET program_id = EXCLUDED.program_id, start_date = EXCLUDED.start_date
    """, (user_hash, program_id))
    
    return jsonify({
        "success": True,
        "message": f"Assigned program '{prog[0]['name']}' to user"
    })

@app.route("/api/enter_test_results", methods=["POST"])
def api_enter_test_results():
    """Save 1RM test results for a user."""
    data = request.get_json()
    user_hash = data.get('user_hash')
    exercise_name = data.get('exercise_name')
    one_rm = data.get('one_rm')
    
    if not user_hash or not exercise_name or one_rm is None:
        return jsonify({"error": "Missing required fields"}), 400
    
    # Insert or update test result
    lakebase.run_query("""
        INSERT INTO user_test_results (user_id_hash, exercise_name, one_rm, test_date)
        VALUES (%s, %s, %s, CURRENT_DATE)
        ON CONFLICT (user_id_hash, exercise_name) 
        DO UPDATE SET one_rm = EXCLUDED.one_rm, test_date = EXCLUDED.test_date
    """, (user_hash, exercise_name, float(one_rm)))
    
    return jsonify({
        "success": True,
        "exercise": exercise_name,
        "one_rm": one_rm
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


if __name__ == "__main__":
    port = int(os.getenv("FLASK_RUN_PORT", 8001))
    app.run(debug=True, host="0.0.0.0", port=port)