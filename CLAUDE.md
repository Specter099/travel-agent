# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered travel assistant using LangGraph and Amazon Bedrock with a Gradio web UI. The agent uses a multi-node LangGraph workflow to provide hotel recommendations (via DuckDuckGo web search) and flight information (via Amadeus API). It uses Grok (xAI) as the LLM backend with streaming responses and maintains conversation history via LangGraph checkpointing.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your AWS_ROLE_ARN, SECRET_NAME, and EXTERNAL_ID
```

## Common Commands

```bash
# Run the Gradio web UI
python gradio_app.py

# Run tests
python test_input_validation.py

# Lint
ruff check .
```

## Directory Structure

```
gradio_app.py              # Gradio web UI with chat interface, flight detail inputs, streaming updates
agents.py                  # LangGraph workflow: entry_node, web_search, flight_search, conversational nodes
credentials.py             # AWS credential management via STS role assumption and Secrets Manager
input_validator.py          # Input validation/sanitization for user queries, locations, and prices
test_input_validation.py   # Tests for input validation
.env.example               # Template for required environment variables
```

## Architecture

LangGraph `StateGraph` workflow with conditional routing:

1. **entry_node** -- Extracts flight details (origin, destination, dates, price) from the user query using the LLM. Determines whether to recommend hotels, flights, or both.
2. **web_search_agent** -- Searches DuckDuckGo for hotel recommendations, streams LLM response with search context.
3. **flight_search_agent** -- Provides flight booking advice using Amadeus API data and LLM streaming.
4. **conversational_node** -- Handles general travel queries that do not require hotel/flight search.

Routing: `entry_node` routes to `web_search_agent`, `flight_search_agent`, or `conversational_node` based on extracted intent. After hotels, conditionally routes to flights.

Conversation memory is managed by LangGraph's `MemorySaver` checkpointer with thread-based sessions.

## Environment Variables

| Variable | Purpose |
|---|---|
| `AWS_ROLE_ARN` | IAM role ARN for STS assume-role (credential retrieval) |
| `SECRET_NAME` | AWS Secrets Manager secret name containing API keys |
| `EXTERNAL_ID` | STS external ID for cross-account access |
| `XAI_API_KEY` | xAI/Grok API key (retrieved from Secrets Manager at startup) |
| `AMADEUS_API_KEY` | Amadeus API key (retrieved from Secrets Manager) |
| `AMADEUS_API_SECRET` | Amadeus API secret (retrieved from Secrets Manager) |
| `LANGSMITH_API_KEY` | LangSmith tracing key (optional, retrieved from Secrets Manager) |

## Code Style

- Python with type hints via `TypedDict` and `pydantic`
- LangGraph for workflow orchestration
- Gradio for the web UI
- Input validation via custom `InputValidator` class
- Ruff for linting
