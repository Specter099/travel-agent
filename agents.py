from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from ddgs import DDGS
from dotenv import load_dotenv
import os
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from credentials import CredentialsManager
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
import requests
import json

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
    web_search_agent_response: str
    flight_origin: str
    flight_destination: str
    flight_max_price: float
    flight_departure_date: str
    flight_arrival_date: str

class AgentResponseFormat(BaseModel):
    response: str

def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for information using DuckDuckGo."""
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append(f"{r['title']}: {r['body']} (URL: {r['href']})")
    return "\n".join(results)

def get_amadeus_credentials(role_arn: str, secret_name: str) -> str:
    creds_manager = CredentialsManager(role_arn)
    response = creds_manager.get_secret(secret_name)
    return response

def get_flight_search_credentials(client_id: str, client_secret: str):
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }
    response = requests.post(url, headers=headers, data=data)
    
    if response.status_code == 200:
        token_data = response.json()
        return token_data["access_token"]
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None

def get_credentials(role_arn: str, secret_name: str) -> str:
    creds_manager = CredentialsManager(role_arn)
    api_key = creds_manager.get_secret(secret_name)
    return api_key

def get_flight_destinations(access_token: str, origin: str, max_price: int = 200):
    url = "https://test.api.amadeus.com/v1/shopping/flight-destinations"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"origin": origin, "maxPrice": max_price}
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None
    
class AgentWorkflow:
    model = "grok-4-fast"

    def __init__(self):
        self.workflow = self.create_workflow()

    def _create_agent(self, model: str, tools, response_format):
        return create_agent(
            model=model,
            tools=tools if tools is not None else None,
            response_format=response_format
        )

    def _create_streaming_llm(self):
        return ChatOpenAI(
            model=model,
            api_key=os.environ["XAI_API_KEY"],
            base_url="https://api.x.ai/v1",
            streaming=True
        )
    
    def web_search_node(self, state: AgentState):
        # Perform web search first
        search_results = web_search(state["user_query"])
        
        # Create streaming LLM
        llm = self._create_streaming_llm()
        
        # Create prompt with search results
        prompt = f"""Based on the following search results, provide hotel recommendations for the user's query: {state["user_query"]}
        
Search Results:
{search_results}
        
Please provide a helpful response with specific hotel recommendations."""
        
        # Stream the response
        response_chunks = []
        for chunk in llm.stream(prompt):
            if chunk.content:
                print(chunk.content, end="", flush=True)
                response_chunks.append(chunk.content)
        
        full_response = "".join(response_chunks)
        return {"web_search_agent_response": full_response}

    def create_workflow(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("web_search_agent", self.web_search_node)
        workflow.add_edge(START, "web_search_agent")
        workflow.add_edge("web_search_agent", END)
        return workflow.compile()
    
    def run(self, state: AgentState):
        result = self.workflow.invoke(state)
        return result
    
    def run_streaming(self, state: AgentState):
        print("\nStarting web search and streaming response...\n")
        result = self.workflow.invoke(state)
        return result
    
if __name__=='__main__':

    # user_query = "Provide hotel recommendations in Donegal, Ireland."
    role_arn, secret_name = load_credentials()
    os.environ["AWS_ROLE_ARN"] = role_arn
    os.environ["XAI_SECRET_NAME"] = secret_name
    x_api_key = get_credentials(role_arn, secret_name) 
    amadeus_credentials = get_amadeus_credentials(role_arn, "amadeus_api")
    os.environ["XAI_API_KEY"] = x_api_key[0]
    access_token = get_flight_search_credentials(amadeus_credentials[0], amadeus_credentials[1])
    print(f"Access token: {access_token}")
    
    # Test flight destinations API
    destinations = get_flight_destinations(access_token, "PAR", 200)
    print(f"Flight destinations: {destinations}")
    # workflow = AgentWorkflow()
    
    # result = workflow.run_streaming({"user_query": user_query})
    # print(f"\n\nFinal response: {result['web_search_agent_response']}")