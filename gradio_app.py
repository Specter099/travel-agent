"""Gradio web UI for the travel agent.

Key safety properties:
- Each browser session gets its own LangGraph thread_id (no cross-talk).
- The streaming callback is per-invocation, not instance state.
- ``launch(share=...)`` and basic auth are driven by env vars; ``share`` is
  off by default so the app is not exposed to the public internet.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from queue import Empty, Queue

import gradio as gr
from langchain_core.messages import HumanMessage

from agents import build_workflow_from_env
from input_validator import InputValidationError, InputValidator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_workflow = None


def get_workflow():
    """Lazy-build the workflow so import is side-effect free (e.g., for tests)."""
    global _workflow
    if _workflow is None:
        _workflow = build_workflow_from_env(model="grok-4-fast")
    return _workflow


def _render(parts: dict) -> str:
    """Render the partial responses into a single assistant message."""
    if parts.get("conversational"):
        return parts["conversational"]
    hotel = parts.get("hotel")
    flight = parts.get("flight")
    if hotel and flight:
        return (
            f"\U0001f3e8 **Hotel Recommendations:**\n{hotel}\n\n"
            f"✈️ **Flight Information:**\n{flight}"
        )
    if flight:
        return f"✈️ **Flight Information:**\n{flight}"
    if hotel:
        return f"\U0001f3e8 **Hotel Recommendations:**\n{hotel}"
    return ""


def travel_agent_chat(
    message: str,
    history: list,
    origin: str,
    destination: str,
    max_price,
    session_id: str,
    request: gr.Request,
):
    if not message or not message.strip():
        yield history, "", session_id
        return

    try:
        InputValidator.validate_user_query(message)
        if origin:
            origin = InputValidator.validate_location(origin)
        if destination:
            destination = InputValidator.validate_location(destination)
        if max_price:
            max_price = InputValidator.validate_price(max_price)
    except InputValidationError as exc:
        history = list(history) + [
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": f"⚠️ Input validation error: {exc}\n\nPlease rephrase your query and try again.",
            },
        ]
        yield history, "", session_id
        return

    # Per-session thread id (one conversation memory per browser tab).
    thread_id = (
        session_id or (request.session_hash if request else None) or str(uuid.uuid4())
    )

    history = list(history) + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": "🔍 Searching for recommendations..."},
    ]
    yield history, "", thread_id

    state = {
        "user_query": message,
        "messages": [HumanMessage(content=message)],
        "flight_origin": origin.strip() if origin else None,
        "flight_destination": destination.strip() if destination else None,
        "flight_max_price": float(max_price) if max_price else None,
        "flight_departure_date": None,
        "flight_arrival_date": None,
        "web_search_agent_response": None,
        "flight_search_agent_response": None,
    }

    logger.info("Processing query (thread=%s): %r", thread_id[:8], message[:80])

    update_queue: Queue = Queue()
    DONE = object()

    def streaming_callback(partial: str, response_type: str):
        update_queue.put((response_type, partial))

    def run_workflow():
        try:
            for _ in get_workflow().run_streaming(
                state, thread_id=thread_id, streaming_callback=streaming_callback
            ):
                pass
        except Exception as exc:  # noqa: BLE001
            logger.error("Workflow execution error: %s", exc, exc_info=True)
            update_queue.put(("__error__", str(exc)))
        finally:
            update_queue.put((DONE, None))

    worker = threading.Thread(target=run_workflow, daemon=True)
    worker.start()

    parts: dict = {"hotel": "", "flight": "", "conversational": ""}
    while True:
        try:
            response_type, payload = update_queue.get(timeout=120)
        except Empty:
            history[-1]["content"] = "⚠️ Request timed out. Please try again."
            yield history, "", thread_id
            return

        if response_type is DONE:
            break
        if response_type == "__error__":
            history[-1]["content"] = f"⚠️ Something went wrong: {payload}"
            yield history, "", thread_id
            return

        parts[response_type] = payload
        rendered = _render(parts)
        if rendered:
            history[-1]["content"] = rendered
            yield history, "", thread_id

    worker.join(timeout=5)
    yield history, "", thread_id


def _new_session_id() -> str:
    return str(uuid.uuid4())


with gr.Blocks(title="Travel AI Agent") as demo:
    gr.Markdown("# 🌍 Travel AI Agent")
    gr.Markdown("Get personalized hotel and flight recommendations for your next trip!")

    session_state = gr.State(value=_new_session_id)

    with gr.Row():
        with gr.Column(scale=2):
            chatbot = gr.Chatbot(
                height=500,
                placeholder="Ask me about hotels and flights for your destination...",
                type="messages",
            )
            with gr.Row():
                msg = gr.Textbox(
                    placeholder="Where would you like to travel?",
                    label="Your Message",
                    lines=1,
                    scale=4,
                    container=False,
                    interactive=True,
                )
                submit_btn = gr.Button("Send", scale=1)

        with gr.Column(scale=1):
            gr.Markdown("### Flight Details (Optional)")
            origin = gr.Textbox(
                label="Departure City/Airport",
                placeholder="e.g., NYC, LHR, San Francisco",
            )
            destination = gr.Textbox(
                label="Destination City/Airport",
                placeholder="e.g., Paris, DUB, Tokyo",
            )
            max_price = gr.Number(
                label="Max Flight Budget ($)",
                value=1000,
                minimum=0,
            )

            gr.Markdown("### Examples")
            gr.Examples(
                examples=[
                    ["Find hotels in Paris for a romantic getaway"],
                    ["I need accommodation and flights to Tokyo"],
                    ["Best hotels in Bali under $200 per night"],
                    ["Plan a trip to Iceland with flight options"],
                ],
                inputs=msg,
            )

    inputs = [msg, chatbot, origin, destination, max_price, session_state]
    outputs = [chatbot, msg, session_state]

    msg.submit(travel_agent_chat, inputs=inputs, outputs=outputs)
    submit_btn.click(travel_agent_chat, inputs=inputs, outputs=outputs)


def _auth_from_env():
    user = os.environ.get("GRADIO_AUTH_USER")
    password = os.environ.get("GRADIO_AUTH_PASSWORD")
    if user and password:
        return (user, password)
    return None


if __name__ == "__main__":
    auth = _auth_from_env()
    share = os.environ.get("GRADIO_SHARE", "").lower() in {"1", "true", "yes"}
    if share and not auth:
        raise RuntimeError(
            "Refusing to launch a public share=True tunnel without auth. "
            "Set GRADIO_AUTH_USER and GRADIO_AUTH_PASSWORD, or unset GRADIO_SHARE."
        )
    if not auth:
        logger.warning(
            "GRADIO_AUTH_USER/PASSWORD not set; running without authentication. "
            "Only bind to localhost in this mode."
        )
    demo.launch(share=share, auth=auth)
