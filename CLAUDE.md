# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered travel assistant built with LangGraph and xAI's Grok model. Uses a multi-node agent workflow (entry routing, web search for hotels via DuckDuckGo, flight recommendations via Amadeus API, general conversation) with streaming responses served through a Gradio web UI. API keys are fetched at runtime from AWS Secrets Manager via cross-account STS role assumption.

## Setup

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in AWS_ROLE_ARN, SECRET_NAME, EXTERNAL_ID in .env

## Common Commands

# Launch the Gradio web UI (opens a shareable link)
python gradio_app.py

# Run the agent directly (CLI, uses hardcoded test query)
python agents.py

# Run input validation tests
python test_input_validation.py

## Environment Variables

| Variable | Purpose | Required |
|---|---|---|
| `AWS_ROLE_ARN` | IAM role ARN for cross-account Secrets Manager access | Yes |
| `SECRET_NAME` | Secrets Manager secret containing API keys | Yes |
| `EXTERNAL_ID` | STS external ID for role assumption | Yes |
| `XAI_API_KEY` | xAI/Grok API key (loaded from Secrets Manager at runtime) | Auto |
| `AMADEUS_API_KEY` | Amadeus flight API key (loaded from Secrets Manager at runtime) | Auto |
| `AMADEUS_API_SECRET` | Amadeus flight API secret (loaded from Secrets Manager at runtime) | Auto |
| `LANGSMITH_API_KEY` | LangSmith tracing key (loaded from Secrets Manager at runtime) | Auto |

## Architecture

The agent workflow is a LangGraph `StateGraph` with conditional routing:

1. **entry_node** — LLM extracts flight details and intent (hotels/flights/conversational) from user query
2. **web_search_agent** — DuckDuckGo search for hotel recommendations, summarized by Grok
3. **flight_search_agent** — Amadeus API for flight data, combined with hotel results if both requested
4. **conversational_node** — General travel Q&A fallback

Routing: `entry_node` -> hotels? -> `web_search_agent` -> flights? -> `flight_search_agent` -> END
                       -> flights only? -> `flight_search_agent` -> END
                       -> neither? -> `conversational_node` -> END

Key files:
- `agents.py` — LangGraph workflow definition, agent nodes, Amadeus/web search helpers
- `gradio_app.py` — Gradio UI with streaming token display via background thread
- `credentials.py` — AWS STS role assumption and Secrets Manager retrieval
- `input_validator.py` — Prompt injection detection and input sanitization

All LLM calls use xAI's Grok (`grok-4-fast`) via OpenAI-compatible endpoint. Conversation history is managed via LangGraph's `MemorySaver` checkpointer with an `Annotated[list, add]` message accumulator.

## Testing

# Run the input validation test suite (no framework, script-based)
python test_input_validation.py

Tests cover prompt injection detection, length limits, special character blocking, and location/price validation. No pytest — tests are in a standalone script with pass/fail assertions.
