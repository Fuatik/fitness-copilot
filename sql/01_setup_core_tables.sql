-- Core Tables for Fitness Copilot
-- Run this SQL script manually in your Lakebase Postgres database before running the notebook

-- Enable pgvector extension for embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Coefficients table: Maps reps to percentage of 1RM
CREATE TABLE IF NOT EXISTS coefficients (
    reps INTEGER PRIMARY KEY,
    percentage DECIMAL(5,2) NOT NULL
);

-- 2. Workout Programs: Program templates (e.g., Strength 2.0, Beginner 3.0)
CREATE TABLE IF NOT EXISTS workout_programs (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT,
    description TEXT,
    target TEXT,
    periodization_type TEXT,
    embedding VECTOR(384),
    UNIQUE(name, version)
);

-- 3. Program Exercises: Week-by-week exercise prescription for each program
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
);

-- 4. Exercise Metadata: Unstructured exercise descriptions from WGER API
CREATE TABLE IF NOT EXISTS exercise_metadata (
    name TEXT PRIMARY KEY,
    description TEXT,
    muscles TEXT[],
    equipment TEXT[],
    instructions TEXT,
    gif_url TEXT,
    embedding VECTOR(384)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_program_exercises_program_id ON program_exercises(program_id);
CREATE INDEX IF NOT EXISTS idx_program_exercises_week ON program_exercises(week);
CREATE INDEX IF NOT EXISTS idx_workout_programs_embedding ON workout_programs USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_exercise_metadata_embedding ON exercise_metadata USING ivfflat (embedding vector_cosine_ops);