# Fitness Copilot – AI‑Powered Strength Program Generator

This project turns periodization Excel logic into an interactive AI coaching assistant. It uses 1RM‑based calculations, coefficient tables, and linear progression from tested spreadsheets, and adds an AI agent that can recommend, customize, and log workouts.

## Architecture

- **MCP Server** (`mcp-server/`): FastMCP server exposing tools (recommend, replace, log, adjust) for the Agent Bricks agent.
- **Frontend App** (`frontend-app/`): Flask UI for onboarding, viewing weekly workouts, and exercise details (GIF/instructions).
- **Spark Pipeline** (`spark-pipeline/`): Ingests hardcoded program templates and coefficient tables into Lakebase, and fetches unstructured exercise descriptions from WGER API (no key), then embeds them for semantic search.
- **Lakebase (Postgres + pgvector)**: Stores user profiles, test results, program templates, and embeddings.

## Unstructured Data Requirement

Unstructured data (free‑text exercise descriptions and instructions) is fetched from the WGER API, stored in Lakebase, and embedded using `sentence-transformers`. The agent can perform semantic search over this text via the `search_exercises` tool.

## Setup

1. Create Databricks secrets using `scripts/setup_secrets.py`.
2. Run the Spark notebook `spark-pipeline/ingest_and_embed.py` to create tables and load data.
3. Deploy the MCP server and frontend as separate Databricks Apps.
4. Register the MCP server as an external MCP tool in Agent Bricks.
5. Create an agent with the provided system prompt.

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
