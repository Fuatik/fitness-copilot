import os
from flask import Flask, request, jsonify, render_template, redirect, url_for
import lakebase
import fitness_broker

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

# ---- Onboarding ----
@app.route("/", methods=["GET", "POST"])
def onboarding():
    if request.method == "POST":
        email = request.form.get("email")
        user_hash = lakebase.hash_email(email)
        # Store profile
        lakebase.run_write("""
                           INSERT INTO user_profiles (user_id_hash, age, height_cm, weight_kg, experience, limitations)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON CONFLICT (user_id_hash) DO UPDATE SET
                                                                    age = EXCLUDED.age,
                                                                    height_cm = EXCLUDED.height_cm,
                                                                    weight_kg = EXCLUDED.weight_kg,
                                                                    experience = EXCLUDED.experience,
                                                                    limitations = EXCLUDED.limitations
                           """, (
                               user_hash,
                               int(request.form.get("age")),
                               int(request.form.get("height")),
                               float(request.form.get("weight")),
                               request.form.get("experience"),
                               request.form.get("limitations_desc")
                           ))
        # Auto-assign program based on experience and limitations
        exp = request.form.get("experience")
        lim = request.form.get("limitations_desc")
        if lim and ("back" in lim.lower() or "spine" in lim.lower()):
            prog = lakebase.run_query("SELECT id FROM workout_programs WHERE version = '4.0'")
        else:
            mapping = {'beginner': '2.0', 'intermediate': '3.0', 'advanced': '4.0'}
            version = mapping.get(exp, '2.0')
            prog = lakebase.run_query("SELECT id FROM workout_programs WHERE version = %s", (version,))
        if prog:
            freq = int(request.form.get("frequency", 3))
            lakebase.run_write("""
                               INSERT INTO user_programs (user_id_hash, program_id, frequency)
                               VALUES (%s, %s, %s)
                               ON CONFLICT (user_id_hash) DO UPDATE SET program_id = EXCLUDED.program_id, frequency = EXCLUDED.frequency
                               """, (user_hash, prog[0]['id'], freq))
        return redirect(url_for('dashboard', user_hash=user_hash))
    return render_template("onboarding.html")

@app.route("/dashboard")
def dashboard():
    user_hash = request.args.get('user_hash')
    if not user_hash:
        return redirect(url_for('onboarding'))
    return render_template("index.html", user_hash=user_hash)

@app.route("/api/workout")
def api_workout():
    user_hash = request.args.get('user_hash')
    week = int(request.args.get('week', 1))
    prog = lakebase.run_query("SELECT program_id FROM user_programs WHERE user_id_hash = %s", (user_hash,))
    if not prog:
        return jsonify({"error": "No program"}), 400
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