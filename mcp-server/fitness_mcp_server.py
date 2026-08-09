import os
import logging
from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import lakebase
import fitness_broker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fitness-mcp")

mcp = FastMCP("fitness-copilot")

# ---- Context: get user_hash from request ----
_request_ctx = {}

class UserContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        email = request.headers.get('x-forwarded-user') or "anonymous"
        user_hash = lakebase.hash_email(email)
        _request_ctx['user_hash'] = user_hash
        response = await call_next(request)
        return response

def get_user_hash():
    return _request_ctx.get('user_hash')

@mcp.tool
def get_program_recommendation(experience: str, goal: str, limitations: str = "") -> dict:
    """
    Recommend a program based on experience and limitations.
    """
    if limitations and ("back" in limitations.lower() or "spine" in limitations.lower()):
        prog = lakebase.run_query("SELECT id, name, description FROM workout_programs WHERE version = '4.0'")
        reasoning = "No-Axial-Load Program is recommended to protect your spine."
    else:
        # Fixed mapping: beginner → 3.0 (easier), intermediate/advanced → 2.0 (harder)
        mapping = {'beginner': '3.0', 'intermediate': '2.0', 'advanced': '2.0'}
        version = mapping.get(experience.lower(), '3.0')
        prog = lakebase.run_query("SELECT id, name, description FROM workout_programs WHERE version = %s", (version,))
        reasoning = f"Based on your experience ({experience}), this program is best."
    if not prog:
        return {"error": "No program found"}
    return {"program_id": prog[0]['id'], "name": prog[0]['name'], "description": prog[0]['description'], "reasoning": reasoning}

@mcp.tool
def assign_program(user_hash: str, program_id: int, frequency: int) -> dict:
    """
    Assign a program to the user. user_hash can be email or pre-hashed value.
    """
    # If user_hash looks like an email, hash it
    if '@' in user_hash:
        user_hash = lakebase.hash_email(user_hash)
    
    lakebase.run_write("""
                       INSERT INTO user_programs (user_id_hash, program_id, frequency)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (user_id_hash) DO UPDATE SET program_id = EXCLUDED.program_id, frequency = EXCLUDED.frequency
                       """, (user_hash, program_id, frequency))
    return {"status": "success", "message": "Program assigned."}

@mcp.tool
def get_workout(user_hash: str, week: int = None) -> dict:
    """
    Get the workout for a specific week (or current week). user_hash can be email or pre-hashed value.
    """
    # If user_hash looks like an email, hash it
    if '@' in user_hash:
        user_hash = lakebase.hash_email(user_hash)
    
    prog = lakebase.run_query("SELECT program_id, current_week FROM user_programs WHERE user_id_hash = %s", (user_hash,))
    if not prog:
        return {"error": "No program assigned"}
    program_id = prog[0]['program_id']
    current_week = prog[0]['current_week'] or 1
    week = week or current_week
    exercises = fitness_broker.generate_workout(user_hash, program_id, week)
    return {"week": week, "exercises": exercises}

@mcp.tool
def log_workout(user_hash: str, exercise: str, weight: float, reps: int) -> dict:
    """
    Log a completed set. user_hash can be email or pre-hashed value.
    """
    # If user_hash looks like an email, hash it
    if '@' in user_hash:
        user_hash = lakebase.hash_email(user_hash)
    
    lakebase.run_write("""
                       INSERT INTO user_workouts (user_id_hash, exercise_name, weight_kg, reps_done)
                       VALUES (%s, %s, %s, %s)
                       """, (user_hash, exercise, weight, reps))
    return {"status": "logged"}

@mcp.tool
def replace_exercise(user_hash: str, old: str, new: str, reason: str) -> dict:
    """Replace an exercise across the entire program. user_hash can be email or pre-hashed value."""
    # If user_hash looks like an email, hash it
    if '@' in user_hash:
        user_hash = lakebase.hash_email(user_hash)
    
    prog = lakebase.run_query("SELECT program_id FROM user_programs WHERE user_id_hash = %s", (user_hash,))
    if not prog:
        return {"error": "No program"}
    return fitness_broker.replace_exercise(user_hash, prog[0]['program_id'], old, new, reason)

@mcp.tool
def adjust_intensity(user_hash: str, exercise: str, change_percent: float) -> dict:
    """Adjust the weight percentage for an exercise. user_hash can be email or pre-hashed value."""
    # If user_hash looks like an email, hash it
    if '@' in user_hash:
        user_hash = lakebase.hash_email(user_hash)
    
    prog = lakebase.run_query("SELECT program_id FROM user_programs WHERE user_id_hash = %s", (user_hash,))
    if not prog:
        return {"error": "No program"}
    return fitness_broker.adjust_intensity(user_hash, prog[0]['program_id'], exercise, change_percent)

@mcp.tool
def get_exercise_details(exercise_name: str) -> dict:
    """Get exercise instructions, muscles, GIF."""
    return fitness_broker.fetch_exercise_info(exercise_name)

@mcp.tool
def search_exercises(query: str) -> list:
    """Semantic search over exercise descriptions (uses embeddings)."""
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
    return rows

if __name__ == "__main__":
    if hasattr(mcp, 'app') and mcp.app is not None:
        mcp.app.add_middleware(UserContextMiddleware)
    port = int(os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", 8000)))
    mcp.run(transport="http", host="0.0.0.0", port=port)