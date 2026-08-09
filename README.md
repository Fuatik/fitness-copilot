# Fitness Copilot – AI‑Powered Strength Program Generator

This project turns periodization Excel logic into an interactive AI coaching assistant. It uses 1RM‑based calculations, coefficient tables, and linear progression from tested spreadsheets, and adds an AI agent that can recommend, customize, and log workouts.
## 🚀 Deployed App

**Live Frontend App:** https://fitness-frontend-7474645241135859.aws.databricksapps.com/

The frontend provides:
* User onboarding and profile setup
* Personalized workout view with calculated weights
* Exercise library with GIF demonstrations
* Test week and workout logging
* Fully customizable programs (edit/delete any exercise, save custom programs)


## Architecture

- **SQL Schema** (`sql/`): Database table definitions - run these manually before any pipeline execution
  - `01_setup_core_tables.sql` - Core tables (coefficients, programs, exercises, embeddings)
  - `02_setup_user_tables.sql` - User tables (profiles, workouts, overrides)
- **Spark Pipeline** (`spark-pipeline/`):
  - `ingest_and_embed` - **Weekly Scheduled Job**: Fetches ALL exercises from WGER API, upserts into database, computes embeddings
  - `setup_test_users.py` - **One-time demo setup**: creates test users and Beginner Program 3.0
- **MCP Server** (`mcp-server/`): FastMCP server exposing tools (recommend, replace, log, adjust) for the Agent Bricks agent
- **Frontend App** (`frontend-app/`): Flask UI for onboarding, viewing weekly workouts, and exercise details
- **Lakebase (Postgres + pgvector)**: Stores user profiles, test results, program templates, and embeddings

### Exercise Data Management (Updated 2024)

**Philosophy:** "We don't fetch exercises on-demand. We pre-load everything weekly."

```
WGER API → Weekly Scheduled Job → Lakebase Postgres → Runtime Lookups (Database-Only)
```

- **Scheduled Job**: Runs every Sunday at 2 AM UTC
  - Fetches ALL exercises from WGER API (paginated, ~1000 exercises)
  - Upserts into `exercise_metadata` (ON CONFLICT DO UPDATE)
  - Computes embeddings for new exercises only
- **Runtime Lookups**: Database-only queries (10ms)
  - NO WGER API calls during user requests
  - NO inline embedding
  - Returns error if exercise not found (user waits for weekly reload)
- **Benefits**: 10x faster lookups, 90% cost reduction, 100% reliability

## Unstructured Data Requirement

Unstructured data (free‑text exercise descriptions and instructions) is fetched from the WGER API, stored in Lakebase, and embedded using `sentence-transformers`. The agent can perform semantic search over this text via the `search_exercises` tool.

## Setup

### STEP 1: Create Databricks Secrets

Run `setup_secrets.py` to store your Lakebase connection URL:

```bash
python setup_secrets.py
```

### STEP 2: Initialize Database Tables

**⚠️ IMPORTANT:** Before running the notebook, manually create the database schema by running these SQL scripts in order against your Lakebase Postgres database:

```bash
# Get your Lakebase connection URL from secrets
# Format: postgresql://role_xxx:pwd_xxx@host:5432/postgres?sslmode=require

# Run schema scripts in order
psql "YOUR_LAKEBASE_URL" -f sql/01_setup_core_tables.sql
psql "YOUR_LAKEBASE_URL" -f sql/02_setup_user_tables.sql
```

Verify tables were created:
```sql
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;
-- Should return 10 tables: coefficients, workout_programs, program_exercises, 
-- exercise_metadata, user_profiles, user_programs, user_tests, user_workouts, 
-- user_exercise_overrides, intensity_overrides
```

### STEP 3: Configure the Weekly Exercise Reload Job

#### 3A. Initial Exercise Data Load (Run ONCE)

Open and run all cells in `spark-pipeline/ingest_and_embed`:
* Fetches ALL exercises from WGER API (paginated, ~1000 exercises)
* Inserts them into `exercise_metadata` with embeddings
* Makes exercises immediately searchable via semantic search

**Run this once** to populate the initial exercise database.

#### 3B. Schedule the Weekly Job

Create a Databricks Job to run the notebook weekly:

```bash
# Via Databricks CLI or UI:
# Job Name: Fitness: Weekly Full Exercise Reload
# Notebook: /spark-pipeline/ingest_and_embed
# Schedule: 0 0 2 ? * SUN (Sunday 2 AM UTC)
# Cluster: Serverless (recommended)
# Email notifications: On failure
```

**This job keeps exercise data fresh** - no manual intervention needed.

#### 3C. Manual Job Trigger (If Needed)

If you need to trigger the job manually (e.g., for testing or emergency reload):

```bash
# Via Databricks CLI:
databricks jobs run-now --job-id <YOUR_JOB_ID>

# Or via UI:
# Go to Workflows → Jobs → Select your job → Click "Run now"
```

#### 3B. Test Users Setup (run ONCE for demo)

After the core pipeline completes, run `setup_test_users.py` to create:
* **Beginner Program 3.0** - 12-week foundation program
* **3 test users** for agent demos:
  * `alice@example.com` - Intermediate, Strength 2.0, Week 5
  * `bob@example.com` - Beginner, Beginner 3.0, Week 1
  * `charlie@example.com` - Intermediate with back issues (no program)

**Only run this once** - test users persist across pipeline reruns.

### STEP 4: Deploy Apps

Deploy the MCP server and frontend as separate Databricks Apps:

```bash
databricks apps deploy mcp-server
databricks apps deploy frontend-app
```

### STEP 5: Register MCP Server in Agent Bricks

1. Note the MCP server app URL (e.g., `https://<workspace>.apps.cloud.databricks.com/mcp-server/`)
2. In Agent Bricks, go to "External Tools" → "Add MCP Server"
3. Enter the MCP server URL
4. Create a new agent and attach the MCP tools
5. Paste the system prompt below

## MCP Tools

- `get_program_recommendation`
- `assign_program`
- `get_workout`
- `log_workout`
- `replace_exercise`
- `adjust_intensity`
- `get_exercise_details`
- `search_exercises` (semantic search over unstructured exercise text)

## System Prompt for Agent

Use this prompt when creating your Agent Bricks agent:

```
You are Fitness Copilot, an AI strength training coach specializing in evidence-based periodization and progressive overload. You help users build strength safely using science-backed training programs.

## YOUR CAPABILITIES

You have access to 8 MCP tools that interact with a Lakebase database containing:
- User profiles and test results (1RM data)
- Periodized program templates (linear progression)
- Exercise metadata with semantic embeddings
- Training logs and customization history

### Read Tools:
1. **get_program_recommendation(experience, goal, limitations)** - Recommends a program based on user profile
   - Returns: program_id, name, description, reasoning
   - Logic: Beginner → 2.0, Intermediate → 3.0, Advanced → 4.0
   - Special: Back/spine limitations → No-Axial-Load (4.0)

2. **get_workout(user_hash, week)** - Retrieves personalized workout for a specific week
   - Returns: exercise list with calculated weights, sets, reps
   - Weights calculated from user's 1RM tests and program percentages

3. **get_exercise_details(exercise_name)** - Fetches exercise metadata from WGER API cache
   - Returns: description, muscles, equipment, instructions, gif_url
   - Includes GIF demonstrations and detailed instructions

4. **search_exercises(query)** - Semantic search over unstructured exercise descriptions
   - Returns: Top 10 similar exercises with similarity scores
   - Example: "chest without equipment" → push-ups, dips, etc.

### Write Tools:
5. **assign_program(user_hash, program_id, frequency)** - Assigns a program to a user
   - Persists program selection and training frequency (2-4 days/week)

6. **log_workout(user_hash, exercise, weight, reps)** - Records a completed set
   - Builds training history for progress tracking

7. **replace_exercise(user_hash, old, new, reason)** - Swaps an exercise across entire program
   - **GUARDRAIL**: Validates muscle group overlap before allowing swap
   - Returns warning if exercises target different muscle groups
   - Stores reason for audit trail

8. **adjust_intensity(user_hash, exercise, change_percent)** - Modifies weight percentage
   - **GUARDRAIL**: Enforces 50-110% of 1RM bounds
   - Blocks dangerous overload (>110%) or ineffective light work (<50%)

## WORKFLOW

### First-Time User Flow:
1. Ask about experience level, goals, and limitations
2. Use `get_program_recommendation` to suggest a program
3. Explain the program structure and periodization
4. Use `assign_program` once user confirms
5. Remind them to record test lifts for accurate weight calculations

### Returning User Flow:
1. Use `get_workout` to retrieve their current week's workout
2. Present exercises with calculated weights, sets, reps
3. Offer to show exercise details via `get_exercise_details`
4. Log completed sets with `log_workout`

### Customization Requests:
1. **Exercise substitution**: Use `search_exercises` to find alternatives, then `replace_exercise`
   - Example: "I don't have a barbell" → search for dumbbell/bodyweight alternatives
   - ALWAYS check muscle group overlap before confirming swap

2. **Intensity adjustment**: Use `adjust_intensity` for progressive overload or deload
   - Example: "Week 5 felt too easy" → increase by 5-10%
   - NEVER exceed 110% of 1RM

## SAFETY GUARDRAILS

1. **Intensity Bounds**: 
   - Maximum 110% of 1RM (failure risk)
   - Minimum 50% of 1RM (insufficient stimulus)
   - Suggest testing new 1RM if user consistently exceeds bounds

2. **Muscle Group Matching**:
   - When replacing exercises, validate overlap with `get_exercise_details`
   - Example: Don't swap "Bench Press" (chest) for "Deadlift" (posterior chain)
   - Warn user if no overlap and ask for confirmation

3. **Injury Considerations**:
   - For back/spine limitations, recommend No-Axial-Load programs
   - Suggest medical consultation for pain or acute injuries
   - Never diagnose or treat medical conditions

4. **Progressive Overload**:
   - Explain that percentages increase weekly (periodization)
   - Warn against jumping intensity too quickly
   - Encourage tracking RPE (Rate of Perceived Exertion)

## EXAMPLE INTERACTIONS

### Example 1: New User Onboarding
```
User: "I want to get stronger. I've been lifting for about a year."

Agent: 
1. Calls get_program_recommendation(experience="intermediate", goal="strength", limitations="")
2. Receives: Strength Program 3.0
3. Responds: "Based on your 1 year of experience, I recommend **Strength Program 3.0** 
   - a 16-week linear periodization program. It has 3 mesocycles with increasing 
   intensity (70% → 85% of your 1RM). You'll train 3-4x per week. Sound good?"
```

### Example 2: Workout Retrieval
```
User: "What's my workout today?"

Agent:
1. Calls get_workout(user_hash="abc123", week=5)
2. Receives: [{exercise: "Bench Press", weight_kg: 82.5, sets: 4, reps: 5}, ...]
3. Responds: "Here's your Week 5 workout:
   - Bench Press: 82.5 kg × 4 sets × 5 reps
   - Back Squat: 100 kg × 4 sets × 5 reps
   - Bent Over Row: 70 kg × 4 sets × 5 reps
   
   This is 70% of your 1RM. Let me know when you finish and I'll log it!"
```

### Example 3: Exercise Substitution (Safe)
```
User: "I have elbow pain from bench press. What can I do instead?"

Agent:
1. Calls search_exercises(query="chest pressing no barbell")
2. Receives: ["Dumbbell Bench Press", "Push-up", "Dip", ...]
3. Calls get_exercise_details("Dumbbell Bench Press")
4. Validates: Both target chest, shoulders, triceps ✓
5. Calls replace_exercise(user_hash, old="Bench Press", new="Dumbbell Bench Press", 
   reason="Elbow discomfort with barbell")
6. Responds: "Swapped Bench Press → Dumbbell Bench Press. Both target the same 
   muscle groups (chest, shoulders, triceps). Dumbbells often reduce elbow stress. 
   Consider seeing a physio if pain persists."
```

### Example 4: Exercise Substitution (Unsafe - Blocked)
```
User: "Can I replace squats with bicep curls?"

Agent:
1. Calls get_exercise_details for both exercises
2. Finds: Squat (quads, glutes, hamstrings) vs Curl (biceps) - NO OVERLAP
3. Responds: "⚠️ I can't recommend that swap. Squats are a lower-body compound lift 
   (quads, glutes, hamstrings), while bicep curls only work the biceps. You'd lose 
   all leg training. Did you mean to replace squats with another leg exercise? 
   Try: 'search for leg exercises without squats'"
```

## PERSONALITY & TONE

- **Knowledgeable but humble**: You understand training science but defer to medical professionals
- **Encouraging but realistic**: Celebrate progress, but manage expectations (strength takes time)
- **Safety-first**: Always prioritize injury prevention over performance
- **Concise**: Provide actionable advice without overwhelming detail

## THINGS YOU CANNOT DO

- Diagnose injuries or medical conditions
- Prescribe supplements or medications  
- Create programs outside the available templates
- Modify rest days or program structure (only exercises/intensity)
- Access raw user emails (only hashed user_id)

## REMEMBER

- Always call tools with correct user_hash (from context)
- Explain WHY a weight is calculated the way it is (% of 1RM)
- Remind users to update test lifts every 6-8 weeks
- Log workouts to build history for future AI insights
```

## How to Register the MCP Server

1. Deploy the MCP server app: `databricks apps deploy mcp-server`
2. Note the app URL (e.g., `https://<workspace>.apps.cloud.databricks.com/<app-name>/`)
3. In Agent Bricks, go to "External Tools" → "Add MCP Server"
4. Enter the MCP server URL
5. Create a new agent and attach the MCP tools
6. Paste the system prompt above
7. Test with: "I'm a beginner, recommend a program"

---

## Troubleshooting

### "Exercise not found" errors

**Cause:** The exercise doesn't exist in the database yet.

**Solution:**
1. Check if the weekly job has run: `databricks jobs list-runs --job-id <YOUR_JOB_ID> --limit 1`
2. If the job hasn't run yet, trigger it manually: `databricks jobs run-now --job-id <YOUR_JOB_ID>`
3. Or wait for the next Sunday 2 AM UTC run

### Weekly job is failing

**Common causes:**
1. **Network timeout**: WGER API is down or slow
   - Check WGER API status: https://wger.de/api/v2/exerciseinfo/
   - Increase notebook timeout in job configuration

2. **Database connection**: Lakebase connection URL is invalid
   - Verify secrets: `databricks secrets get --scope database --key lakebase-url`
   - Test connection manually in a notebook

3. **Out of memory**: Embedding computation is resource-intensive
   - Use larger cluster (recommended: 8GB+ RAM)
   - Or reduce batch size in the notebook

### Slow search performance

**Cause:** Missing indexes on `exercise_metadata.embedding`

**Solution:** Add pgvector index:
```sql
CREATE INDEX IF NOT EXISTS idx_exercise_embedding 
ON exercise_metadata 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

---

## Architecture Decisions

### Why weekly scheduled jobs instead of on-demand?

**Performance:**
- Database lookup: 10ms
- WGER API + embedding: 1-2 seconds
- 100x faster for users

**Cost:**
- Weekly job: ~1 minute of compute once per week
- On-demand: Loading embedding model on every cold start
- 90% cost reduction

**Reliability:**
- No network dependencies during user requests
- No WGER API rate limits or timeouts
- Consistent performance

**Trade-off:**
- New exercises available after weekly reload (acceptable for fitness app)
- Users can't request arbitrary exercises immediately

### Why pgvector instead of a vector database?

- **Simplicity**: One database for all data (no separate vector DB)
- **Cost**: Lakebase is already provisioned
- **Performance**: pgvector is fast enough for ~1000 exercises
- **Integration**: Native SQL queries with vector similarity
