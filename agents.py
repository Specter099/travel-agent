from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from ddgs import DDGS
from dotenv import load_dotenv
import os
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from credentials import CredentialsManager
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Optional
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
    web_search_agent_response: Optional[str]
    flight_recommendations: bool
    flight_search_agent_response: Optional[str]
    flight_origin: Optional[str]
    flight_destination: Optional[str]
    flight_max_price: Optional[float]
    flight_departure_date: Optional[str]
    flight_arrival_date: Optional[str]

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

    def __init__(self, model: str):
        self.workflow = self.create_workflow()
        self.model = model

    def _create_agent(self, model: str, tools, response_format):
        return create_agent(
            model=model,
            tools=tools if tools is not None else None,
            response_format=response_format
        )

    def _create_grok_llm(self, streaming=None):
        return ChatOpenAI(
            model=self.model,
            api_key=os.environ["XAI_API_KEY"],
            base_url="https://api.x.ai/v1",
            streaming=streaming
        )
    
    def _stream_response(self, llm: ChatOpenAI, prompt: str) -> str:
        # Stream the response
        response_chunks = []
        for chunk in llm.stream(prompt):
            if chunk.content:
                print(chunk.content, end="", flush=True)
                response_chunks.append(chunk.content)
        
        full_response = "".join(response_chunks)
        return full_response

    def flight_recommendations_node(self, state: AgentState):
        user_query = state["user_query"]
        llm = self._create_grok_llm(streaming=False)
        
        # Create prompt to determine if flight info is needed
        prompt = f"""Determine if the user is asking for flight recommendations based on the query. Respond only with True or False.
        Query: {user_query}"""

        # Get structured response from LLM
        response = llm.invoke([HumanMessage(content=prompt)])
        needs_flights = response.content.strip().lower() == "true"
        return {"flight_recommendations": needs_flights}

    def first_node(self, state: AgentState):
        user_query = state["user_query"]
        llm = self._create_grok_llm(streaming=False)
        
        # Create prompt to extract flight details
        prompt = f"""Extract flight details from the following query. If any detail is not present, return None.
        Query: {user_query}
        
        Required format:
        Origin: <origin airport code or None>
        Destination: <destination airport code or None> 
        Max Price: <maximum price as float or None>
        Departure Date: <YYYY-MM-DD or None>
        Arrival Date: <YYYY-MM-DD or None>"""

        # Get structured response from LLM
        response = llm.invoke([HumanMessage(content=prompt)])
        
        # Parse response and update state
        lines = response.content.strip().split('\n')
        extracted = {}
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                value = value.strip()
                extracted[key.strip().lower().replace(' ', '_')] = None if value == 'None' else value

        return {
            "flight_origin": extracted.get('origin'),
            "flight_destination": extracted.get('destination'),
            "flight_max_price": float(extracted['max_price']) if extracted.get('max_price') else None,
            "flight_departure_date": extracted.get('departure_date'),
            "flight_arrival_date": extracted.get('arrival_date')
        }
        

    def web_search_node(self, state: AgentState):
        # Perform web search first
        search_results = web_search(state["user_query"])
        
        # Create streaming LLM
        llm = self._create_grok_llm(streaming=True)
        
        # Create prompt with search results
        prompt = f"""Based on the following search results, provide hotel recommendations for the user's query: {state["user_query"]}
    
        
Search Results:
{search_results}
        
Please provide a helpful response with specific hotel recommendations."""
        
        # Stream the response
        full_response = self._stream_response(llm, prompt)
        return {"web_search_agent_response": full_response}

    def flight_search_node(self, state: AgentState):
        flight_origin = state.get('flight_origin')
        flight_destination = state.get('flight_destination')
        flight_max_price = state.get('flight_max_price', 1000)

        # Create streaming LLM
        llm = self._create_grok_llm(streaming=True)

        # Provide general flight advice without API calls to avoid 404 errors
        prompt = f"""Provide flight recommendations for the user's query: {state["user_query"]}
        
Origin: {flight_origin if flight_origin else 'Not specified'}
Destination: {flight_destination if flight_destination else 'Not specified'} 
Max Price: {flight_max_price}

Since specific flight data is not available, provide general flight booking advice including:
- Major airlines that serve the destination
- Typical flight routes and connections
- Best booking practices and timing
- Airport recommendations"""

        # Stream the response
        full_response = self._stream_response(llm, prompt)
        return {"flight_search_agent_response": full_response}  
      
    def should_search_flights(self, state: AgentState):
        """Conditional function to determine next node"""
        if state.get("flight_recommendations"):
            return "flight_search_agent"
        else:
            return END
    
    def create_workflow(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("flight_recommendations_node", self.flight_recommendations_node)
        workflow.add_node("web_search_agent", self.web_search_node)
        workflow.add_node("flight_search_agent", self.flight_search_node)
        
        workflow.add_edge(START, "flight_recommendations_node")
        workflow.add_edge("flight_recommendations_node", "web_search_agent")
        workflow.add_conditional_edges(
            "web_search_agent",
            self.should_search_flights,
            {
                "flight_search_agent": "flight_search_agent",
                END: END
            }
        )
        workflow.add_edge("flight_search_agent", END)
        return workflow.compile()
    
    def run(self, state: AgentState):
        result = self.workflow.invoke(state)
        return result
    
    def run_streaming(self, state: AgentState):
        result = self.workflow.invoke(state)
        return result
    
if __name__=='__main__':

    user_query = "Provide hotel and flight recommendations in Donegal, Ireland."
    role_arn, secret_name = load_credentials()
    os.environ["AWS_ROLE_ARN"] = role_arn
    os.environ["XAI_SECRET_NAME"] = secret_name
    x_api_key = get_credentials(role_arn, secret_name) 
    amadeus_credentials = get_amadeus_credentials(role_arn, "amadeus_api")
    os.environ["XAI_API_KEY"] = x_api_key[0]
    access_token = get_flight_search_credentials(amadeus_credentials[0], amadeus_credentials[1])
    os.environ["AMADEUS_ACCESS_TOKEN"] = access_token
    
    workflow = AgentWorkflow("grok-4-fast")
    
    result = workflow.run_streaming({"user_query": user_query})
    print(f"\n\nWeb Search Response: {result.get('web_search_agent_response', 'N/A')}")
    if result.get('flight_search_agent_response', 'N/A') != 'N/A':
        print(f"\n\nFlight Search Response: {result.get('flight_search_agent_response', 'N/A')}")
    else:
        print("\n\nFlight recommendations were not requested")