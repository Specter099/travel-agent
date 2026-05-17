"""Travel-agent LangGraph workflow.

Secrets are passed in via the AgentWorkflow constructor rather than read from
os.environ, so they cannot leak into child processes. The Amadeus OAuth token
is refreshed lazily when it nears expiry.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from operator import add
from typing import Annotated, Optional, TypedDict

import requests
from ddgs import DDGS
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from input_validator import InputValidationError, InputValidator

logger = logging.getLogger(__name__)

_AMADEUS_TOKEN_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
_AMADEUS_FLIGHT_DESTINATIONS_URL = (
    "https://test.api.amadeus.com/v1/shopping/flight-destinations"
)
_HTTP_TIMEOUT_SECONDS = 30
_TOKEN_REFRESH_LEEWAY = timedelta(seconds=60)


class AgentState(TypedDict, total=False):
    user_query: str
    should_recommend_hotels: bool
    should_recommend_flights: bool
    web_search_agent_response: Optional[str]
    flight_search_agent_response: Optional[str]
    flight_origin: Optional[str]
    flight_destination: Optional[str]
    flight_max_price: Optional[float]
    flight_departure_date: Optional[str]
    flight_arrival_date: Optional[str]
    messages: Annotated[list, add]


class FlightExtraction(BaseModel):
    """Structured extraction from a free-form user query."""

    flight_origin: Optional[str] = Field(
        None, description="IATA airport code or city name"
    )
    flight_destination: Optional[str] = Field(
        None, description="IATA airport code or city name"
    )
    flight_max_price: Optional[float] = Field(None, description="Maximum price in USD")
    flight_departure_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    flight_arrival_date: Optional[str] = Field(None, description="YYYY-MM-DD")
    should_recommend_flights: bool = False
    should_recommend_hotels: bool = False


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for information using DuckDuckGo.

    Returns an empty string on failure so the workflow degrades gracefully
    instead of aborting the whole conversation when DDG rate-limits.
    """
    try:
        with DDGS() as ddgs:
            results = [
                f"{r['title']}: {r['body']} (URL: {r['href']})"
                for r in ddgs.text(query, max_results=max_results)
            ]
        return "\n".join(results)
    except Exception as exc:
        logger.warning("Web search failed for query %r: %s", query[:80], exc)
        return ""


class AmadeusClient:
    """Holds Amadeus client credentials and lazily refreshes the OAuth token."""

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: Optional[str] = None
        self._expires_at: Optional[datetime] = None
        self._lock = threading.Lock()

    def _token_valid(self) -> bool:
        return bool(
            self._token
            and self._expires_at
            and datetime.now(timezone.utc) < self._expires_at - _TOKEN_REFRESH_LEEWAY
        )

    def access_token(self) -> Optional[str]:
        with self._lock:
            if self._token_valid():
                return self._token
            try:
                response = requests.post(
                    _AMADEUS_TOKEN_URL,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    timeout=_HTTP_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
                self._token = payload["access_token"]
                self._expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=int(payload.get("expires_in", 1800))
                )
                logger.info(
                    "Refreshed Amadeus OAuth token (expires %s)", self._expires_at
                )
                return self._token
            except Exception as exc:  # noqa: BLE001 — any failure must clear token state
                logger.error("Amadeus token request failed: %s", exc)
                self._token = None
                self._expires_at = None
                return None

    def flight_destinations(self, origin: str, max_price: int = 200) -> Optional[dict]:
        token = self.access_token()
        if not token:
            return None
        try:
            response = requests.get(
                _AMADEUS_FLIGHT_DESTINATIONS_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={"origin": origin, "maxPrice": max_price},
                timeout=_HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.error("Amadeus flight destinations request failed: %s", exc)
            return None


def _format_history(messages: list) -> str:
    """Render prior turns as a readable transcript, excluding the current one."""
    if len(messages) <= 1:
        return ""
    lines = []
    for msg in messages[:-1]:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        lines.append(f"{role}: {msg.content}")
    return "\n\nPrevious conversation:\n" + "\n".join(lines)


def _streaming_callback_from_config(config: Optional[RunnableConfig]):
    if not config:
        return None
    return config.get("configurable", {}).get("streaming_callback")


class AgentWorkflow:
    """LangGraph workflow that routes between hotel search, flight info, and chat."""

    def __init__(
        self,
        model: str,
        xai_api_key: str,
        amadeus: Optional[AmadeusClient] = None,
    ):
        if not xai_api_key:
            raise ValueError("xai_api_key is required")
        self.model = model
        self._xai_api_key = xai_api_key
        self.amadeus = amadeus
        self.memory = MemorySaver()
        self.workflow = self._build_graph()

    def _llm(self, streaming: bool = False) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.model,
            api_key=self._xai_api_key,
            base_url="https://api.x.ai/v1",
            streaming=streaming,
        )

    def _stream(
        self,
        llm: ChatOpenAI,
        prompt: str,
        response_type: str,
        callback,
    ) -> str:
        chunks: list[str] = []
        for chunk in llm.stream(prompt):
            if chunk.content:
                chunks.append(chunk.content)
                if callback:
                    try:
                        callback("".join(chunks), response_type)
                    except Exception as exc:  # noqa: BLE001 — callback is user-supplied
                        logger.warning("Streaming callback raised: %s", exc)
        return "".join(chunks)

    def entry_node(self, state: AgentState) -> dict:
        try:
            user_query = InputValidator.validate_user_query(state["user_query"])
        except InputValidationError as exc:
            logger.warning("Input validation failed: %s", exc)
            return {
                "web_search_agent_response": f"Error: {exc}",
                "should_recommend_hotels": False,
                "should_recommend_flights": False,
            }

        llm = self._llm(streaming=False).with_structured_output(FlightExtraction)
        prompt = (
            "Extract flight intent and details from the user's travel query. "
            "Set should_recommend_flights/hotels based on whether the user is asking for them. "
            "Leave fields as null if not mentioned.\n\n"
            f"Query: {user_query}"
        )

        try:
            extraction: FlightExtraction = llm.invoke([HumanMessage(content=prompt)])
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Structured extraction failed, falling back to defaults: %s", exc
            )
            extraction = FlightExtraction()

        return {
            "user_query": user_query,
            "flight_origin": extraction.flight_origin,
            "flight_destination": extraction.flight_destination,
            "flight_max_price": extraction.flight_max_price,
            "flight_departure_date": extraction.flight_departure_date,
            "flight_arrival_date": extraction.flight_arrival_date,
            "should_recommend_flights": extraction.should_recommend_flights,
            "should_recommend_hotels": extraction.should_recommend_hotels,
        }

    def web_search_node(self, state: AgentState, config: RunnableConfig) -> dict:
        try:
            user_query = InputValidator.validate_user_query(state["user_query"])
        except InputValidationError as exc:
            return {
                "web_search_agent_response": f"Error: {exc}",
                "messages": [AIMessage(content=f"Error: {exc}")],
            }

        search_results = web_search(user_query)
        history = _format_history(state.get("messages", []))
        prompt = (
            f"Based on the following search results, provide hotel recommendations "
            f"for the user's query: {user_query}{history}\n\n"
            f"Search Results:\n{search_results or '(no search results available)'}\n\n"
            "Please provide a helpful response with specific hotel recommendations."
        )

        full_response = self._stream(
            self._llm(streaming=True),
            prompt,
            "hotel",
            _streaming_callback_from_config(config),
        )

        # The flight node will combine messages if flights are also requested.
        messages_to_add: list = []
        if not state.get("should_recommend_flights"):
            messages_to_add = [AIMessage(content=full_response)]

        return {
            "web_search_agent_response": full_response,
            "messages": messages_to_add,
        }

    def flight_search_node(self, state: AgentState, config: RunnableConfig) -> dict:
        try:
            user_query = (
                InputValidator.validate_user_query(state["user_query"])
                if state.get("user_query")
                else None
            )
            origin = InputValidator.validate_location(state.get("flight_origin"))
            destination = InputValidator.validate_location(
                state.get("flight_destination")
            )
            max_price = InputValidator.validate_price(state.get("flight_max_price"))
        except InputValidationError as exc:
            return {
                "flight_search_agent_response": f"Error: {exc}",
                "messages": [AIMessage(content=f"Error: {exc}")],
            }

        history = _format_history(state.get("messages", []))
        prompt = (
            f"Provide flight recommendations for the user's query: {user_query}{history}\n\n"
            f"Origin: {origin or 'Not specified'}\n"
            f"Destination: {destination or 'Not specified'}\n"
            f"Max Price: {max_price if max_price is not None else 'Not specified'}\n\n"
            "Since specific flight data is not available, provide general flight booking advice including:\n"
            "- Major airlines that serve the destination\n"
            "- Typical flight routes and connections\n"
            "- Best booking practices and timing\n"
            "- Airport recommendations"
        )

        full_response = self._stream(
            self._llm(streaming=True),
            prompt,
            "flight",
            _streaming_callback_from_config(config),
        )

        web_search_response = state.get("web_search_agent_response")
        combined = (
            f"\U0001f3e8 **Hotel Recommendations:**\n{web_search_response}\n\n"
            f"✈️ **Flight Information:**\n{full_response}"
            if web_search_response
            else full_response
        )

        return {
            "flight_search_agent_response": full_response,
            "messages": [AIMessage(content=combined)],
        }

    def conversational_node(self, state: AgentState, config: RunnableConfig) -> dict:
        try:
            user_query = InputValidator.validate_user_query(state["user_query"])
        except InputValidationError as exc:
            return {
                "web_search_agent_response": f"Error: {exc}",
                "messages": [AIMessage(content=f"Error: {exc}")],
            }

        history = _format_history(state.get("messages", []))
        prompt = (
            f"You are a helpful travel agent. Answer the user's query: {user_query}{history}\n\n"
            "Provide a helpful and friendly response."
        )

        full_response = self._stream(
            self._llm(streaming=True),
            prompt,
            "conversational",
            _streaming_callback_from_config(config),
        )

        return {
            "web_search_agent_response": full_response,
            "messages": [AIMessage(content=full_response)],
        }

    def _route_after_entry(self, state: AgentState) -> str:
        if state.get("should_recommend_hotels"):
            return "web_search_agent"
        if state.get("should_recommend_flights"):
            return "flight_search_agent"
        return "conversational_node"

    def _route_after_hotels(self, state: AgentState):
        if state.get("should_recommend_flights"):
            return "flight_search_agent"
        return END

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("entry_node", self.entry_node)
        workflow.add_node("web_search_agent", self.web_search_node)
        workflow.add_node("flight_search_agent", self.flight_search_node)
        workflow.add_node("conversational_node", self.conversational_node)

        workflow.add_edge(START, "entry_node")
        workflow.add_conditional_edges(
            "entry_node",
            self._route_after_entry,
            {
                "web_search_agent": "web_search_agent",
                "flight_search_agent": "flight_search_agent",
                "conversational_node": "conversational_node",
            },
        )
        workflow.add_conditional_edges(
            "web_search_agent",
            self._route_after_hotels,
            {"flight_search_agent": "flight_search_agent", END: END},
        )
        workflow.add_edge("flight_search_agent", END)
        workflow.add_edge("conversational_node", END)
        return workflow.compile(checkpointer=self.memory)

    def run(self, state: AgentState, thread_id: str = "default") -> dict:
        return self.workflow.invoke(state, {"configurable": {"thread_id": thread_id}})

    def run_streaming(
        self,
        state: AgentState,
        thread_id: str = "default",
        streaming_callback=None,
    ):
        """Stream workflow execution; yields intermediate states.

        ``streaming_callback`` is plumbed through the LangGraph RunnableConfig
        so each invocation gets its own callback — no instance-level state to
        leak between concurrent requests.
        """
        config = {
            "configurable": {
                "thread_id": thread_id,
                "streaming_callback": streaming_callback,
            }
        }
        yield from self.workflow.stream(state, config, stream_mode="values")


def build_workflow_from_env(model: str = "grok-4-fast") -> AgentWorkflow:
    """Build a workflow using AWS-stored secrets. Used by the CLI/dev entrypoint."""
    import os

    from dotenv import load_dotenv

    from credentials import CredentialsManager

    load_dotenv()
    role_arn = os.environ.get("AWS_ROLE_ARN")
    secret_name = os.environ.get("SECRET_NAME")
    external_id = os.environ.get("EXTERNAL_ID")
    if not (role_arn and secret_name and external_id):
        raise RuntimeError(
            "AWS_ROLE_ARN, SECRET_NAME, and EXTERNAL_ID must be set in the environment"
        )

    creds = CredentialsManager(role_arn=role_arn, external_id=external_id).get_secret(
        secret_name
    )
    amadeus = AmadeusClient(creds.amadeus_api_key, creds.amadeus_api_secret)
    return AgentWorkflow(model=model, xai_api_key=creds.xai_api_key, amadeus=amadeus)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    workflow = build_workflow_from_env()
    for event in workflow.run_streaming(
        {"user_query": "Provide hotel and flight recommendations in Donegal, Ireland."}
    ):
        logger.info("event: %s", list(event.keys()))
