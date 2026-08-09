-- User Tables for Fitness Copilot
-- Run this SQL script manually in your Lakebase Postgres database after 01_setup_core_tables.sql

-- 1. User Profiles: Demographics and experience level (PII-safe: email is hashed)
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id_hash TEXT PRIMARY KEY,
    age INTEGER,
    height_cm INTEGER,
    weight_kg DECIMAL(5,2),
    experience TEXT,
    limitations TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- 2. User Programs: Which program each user is currently following
CREATE TABLE IF NOT EXISTS user_programs (
    user_id_hash TEXT PRIMARY KEY,
    program_id INTEGER,
    frequency INTEGER,
    current_week INTEGER DEFAULT 1,
    assigned_at TIMESTAMP DEFAULT now()
);

-- 3. User Tests: 1RM test results for each exercise
CREATE TABLE IF NOT EXISTS user_tests (
    user_id_hash TEXT,
    program_id INTEGER,
    exercise_name TEXT,
    test_weight DECIMAL(8,2),
    test_reps INTEGER,
    step_size DECIMAL(5,2),
    test_date DATE DEFAULT now(),
    PRIMARY KEY (user_id_hash, program_id, exercise_name)
);

-- 4. User Workouts: Logged workout performance
CREATE TABLE IF NOT EXISTS user_workouts (
    id SERIAL PRIMARY KEY,
    user_id_hash TEXT,
    exercise_name TEXT,
    weight_kg DECIMAL(8,2),
    reps_done INTEGER,
    logged_at TIMESTAMP DEFAULT now()
);

-- 5. User Exercise Overrides: Agent-recommended exercise substitutions
CREATE TABLE IF NOT EXISTS user_exercise_overrides (
    id SERIAL PRIMARY KEY,
    user_id_hash TEXT,
    program_id INTEGER,
    old_exercise_name TEXT,
    new_exercise_name TEXT,
    reason TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- 6. Intensity Overrides: Agent-adjusted percentages for specific exercises
CREATE TABLE IF NOT EXISTS intensity_overrides (
    user_id_hash TEXT,
    program_id INTEGER,
    exercise_name TEXT,
    new_percentage DECIMAL(5,2),
    PRIMARY KEY (user_id_hash, program_id, exercise_name)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_programs_program_id ON user_programs(program_id);
CREATE INDEX IF NOT EXISTS idx_user_tests_user_id ON user_tests(user_id_hash);
CREATE INDEX IF NOT EXISTS idx_user_workouts_user_id ON user_workouts(user_id_hash);
CREATE INDEX IF NOT EXISTS idx_user_workouts_logged_at ON user_workouts(logged_at);