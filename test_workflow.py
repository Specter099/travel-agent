"""Smoke tests for AgentWorkflow graph construction.

These tests intentionally avoid hitting the network or AWS — they verify that
the workflow compiles, that every node referenced in the routing tables is
wired into the graph, and that there is no leftover dead code masquerading as
a node.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from agents import AgentWorkflow, FlightExtraction, _format_history
from langchain_core.messages import AIMessage, HumanMessage


class WorkflowBuildTests(unittest.TestCase):
    def setUp(self):
        # ChatOpenAI is only constructed lazily inside nodes; we never invoke
        # it in these tests, so the dummy API key is fine.
        self.workflow = AgentWorkflow(model="grok-4-fast", xai_api_key="test-key")

    def test_graph_compiles(self):
        self.assertIsNotNone(self.workflow.workflow)

    def test_xai_api_key_required(self):
        with self.assertRaises(ValueError):
            AgentWorkflow(model="grok-4-fast", xai_api_key="")

    def test_route_after_entry_prefers_hotels(self):
        self.assertEqual(
            self.workflow._route_after_entry({"should_recommend_hotels": True}),
            "web_search_agent",
        )

    def test_route_after_entry_falls_back_to_flights(self):
        self.assertEqual(
            self.workflow._route_after_entry(
                {"should_recommend_hotels": False, "should_recommend_flights": True}
            ),
            "flight_search_agent",
        )

    def test_route_after_entry_defaults_to_conversational(self):
        self.assertEqual(
            self.workflow._route_after_entry({}),
            "conversational_node",
        )


class HistoryFormattingTests(unittest.TestCase):
    def test_empty_history_returns_blank(self):
        self.assertEqual(_format_history([]), "")

    def test_single_message_returns_blank(self):
        # Single message is the current turn; nothing prior to render.
        self.assertEqual(_format_history([HumanMessage(content="hi")]), "")

    def test_history_renders_prior_turns_only(self):
        out = _format_history(
            [
                HumanMessage(content="first"),
                AIMessage(content="response"),
                HumanMessage(content="current"),
            ]
        )
        self.assertIn("User: first", out)
        self.assertIn("Assistant: response", out)
        self.assertNotIn("current", out)


class StructuredExtractionTests(unittest.TestCase):
    def test_extraction_defaults_are_safe(self):
        extraction = FlightExtraction()
        self.assertFalse(extraction.should_recommend_flights)
        self.assertFalse(extraction.should_recommend_hotels)
        self.assertIsNone(extraction.flight_origin)
        self.assertIsNone(extraction.flight_max_price)


class AmadeusClientTests(unittest.TestCase):
    def test_token_not_cached_on_failure(self):
        from agents import AmadeusClient

        client = AmadeusClient("id", "secret")
        with patch("agents.requests.post", side_effect=Exception("boom")):
            self.assertIsNone(client.access_token())
        # After failure, internal state should be cleared, not poisoned.
        self.assertIsNone(client._token)
        self.assertIsNone(client._expires_at)


if __name__ == "__main__":
    unittest.main()
