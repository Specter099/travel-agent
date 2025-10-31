from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from duckduckgo_search import DDGS
from dotenv import load_dotenv
import os
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from credentials import CredentialsManager
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

model = "grok-4-fast"

def load_credentials():
    load_dotenv()

    # Get configuration from environment variables
    role_arn = os.getenv("AWS_ROLE_ARN")
    secret_name = os.getenv("XAI_SECRET_NAME")

    # Validate required environment variables
    if not role_arn:
        raise ValueError("AWS_ROLE_ARN environment variable is required")
    if not secret_name:
        raise ValueError("XAI_SECRET_NAME environment variable is required")
    return role_arn, secret_name

class AgentState(TypedDict):
    user_query: str
    agent_response: str

class AgentResponse(BaseModel):
    response: str

def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for information using DuckDuckGo."""
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append(f"{r['title']}: {r['body']} (URL: {r['href']})")
    return "\n".join(results)

def get_credentials(role_arn: str, secret_name: str) -> str:
    creds_manager = CredentialsManager(role_arn)
    api_key = creds_manager.get_secret(secret_name)
    return api_key

class AgentWorkflow:
    def __init__(self):
        self.workflow = self.create_workflow()

    def web_search_agent(self, model: str):
        travel_agent = create_agent(
            model=model,
            tools=[web_search],
            response_format=AgentResponse
        )
        return travel_agent
    
    def web_search_node(self, state: AgentState):
        agent = self.web_search_agent(model)
        agent_response = agent.invoke({"messages": [{"role": "user", "content": state["user_query"]}]}
        )
        return {"agent_response": agent_response}

    def create_workflow(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("web_search_agent", self.web_search_node)
        workflow.add_edge(START, "web_search_agent")
        workflow.add_edge("web_search_agent", END)
        return workflow.compile()
    
    def run(self, state: AgentState):
        result = self.workflow.invoke(state)
        return result
    
if __name__=='__main__':
    role_arn, secret_name = load_credentials()
    os.environ["AWS_ROLE_ARN"] = role_arn
    os.environ["XAI_SECRET_NAME"] = secret_name
    api_key = get_credentials(role_arn, secret_name) 
    os.environ["XAI_API_KEY"] = api_key
    workflow = AgentWorkflow()
    print(workflow.run({"user_query": "Provide hotel recommendations in Donegal, Ireland."}))