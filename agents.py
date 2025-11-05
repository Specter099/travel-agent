from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from ddgs import DDGS
from dotenv import load_dotenv
import os
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage
from credentials import CredentialsManager
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from typing import TypedDict, Optional, Annotated
from operator import add
import requests

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
    should_recommend_hotels: bool
    web_search_agent_response: Optional[str]
    should_recommend_flights: bool
    flight_search_agent_response: Optional[str]
    flight_origin: Optional[str]
    flight_destination: Optional[str]
    flight_max_price: Optional[float]
    flight_departure_date: Optional[str]
    flight_arrival_date: Optional[str]
    messages: Annotated[list, add]

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
        self.model = model
        self.memory = MemorySaver()
        self.workflow = self.create_workflow()

    def create_grok_llm(self, streaming=None):
        return ChatOpenAI(
            model=self.model,
            api_key=os.environ["XAI_API_KEY"],
            base_url="https://api.x.ai/v1",
            streaming=streaming
        )
    
    def stream_response(self, llm: ChatOpenAI, prompt: str) -> str:
        # Stream the response
        response_chunks = []
        for chunk in llm.stream(prompt):
            if chunk.content:
                print(chunk.content, end="", flush=True)
                response_chunks.append(chunk.content)
        
        full_response = "".join(response_chunks)
        return full_response

    def entry_node(self, state: AgentState):
        user_query = state["user_query"]
        llm = self.create_grok_llm(streaming=False)
        
        # Create prompt to extract flight details
        prompt = f"""Extract flight details from the following query. If any detail is not present, return None.
        Query: {user_query}
        
        Required format:
        Origin: <origin airport code or None>
        Destination: <destination airport code or None> 
        Max Price: <maximum price as float or None>
        Departure Date: <YYYY-MM-DD or None>
        Arrival Date: <YYYY-MM-DD or None>
        Should recommend flights: <True or False>
        Should recommend hotels: <True or False>"""

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

        # Safely convert max_price to float with error handling
        max_price = None
        if extracted.get('max_price'):
            try:
                max_price = float(extracted['max_price'])
            except (ValueError, TypeError):
                max_price = None

        return {
            "flight_origin": extracted.get('origin'),
            "flight_destination": extracted.get('destination'),
            "flight_max_price": max_price,
            "flight_departure_date": extracted.get('departure_date'),
            "flight_arrival_date": extracted.get('arrival_date'),
            "should_recommend_flights": extracted.get('should_recommend_flights') == 'True',
            "should_recommend_hotels": extracted.get('should_recommend_hotels') == 'True'
        }

    def print_state_node(self, state: AgentState):
        print(state.get("flight_origin"))
        print(state.get("flight_destination"))
        print(state.get("flight_max_price"))
        print(state.get("flight_departure_date"))
        print(state.get("flight_arrival_date"))
        print(state.get("should_recommend_hotels"))
        print(state.get("should_recommend_flights"))

    def flight_recommendations_node(self, state: AgentState):
        user_query = state["user_query"]
        
        # Check if flight details are provided in the state or if query mentions flights
        has_flight_details = bool(state.get("flight_origin") or state.get("flight_destination"))
        query_mentions_flights = "flight" in user_query.lower() or "fly" in user_query.lower()
        
        needs_flights = has_flight_details or query_mentions_flights
        return {"flight_recommendations": needs_flights}

    def should_recommend_hotels_node(self, state: AgentState):
        user_query = state.get("user_query")
        llm = self.create_grok_llm(streaming=False)
        prompt = f"""You are a helpful travel agent.  Determine if the user is asking for hotel recommendations.  ***Respond with only True or False***.

user_query: {user_query}
"""
        should_recommend_hotels_response = llm.invoke([HumanMessage(content=prompt)]).content.lower()
        if should_recommend_hotels_response == "true":
            response = True
        if should_recommend_hotels_response == "false":
            response = False
        return {"should_recommend_hotels": response}

    def web_search_node(self, state: AgentState):
        # Perform web search first
        search_results = web_search(state["user_query"])
        
        # Create streaming LLM
        llm = self.create_grok_llm(streaming=True)
        
        # Build context from messages
        history_context = ""
        messages = state.get("messages", [])
        if len(messages) > 1:
            history_context = "\n\nPrevious conversation:\n"
            for msg in messages[-4:]:
                role = "User" if isinstance(msg, HumanMessage) else "Assistant"
                history_context += f"{role}: {msg.content}\n"
        
        # Create prompt with search results
        prompt = f"""Based on the following search results, provide hotel recommendations for the user's query: {state["user_query"]}
{history_context}
        
Search Results:
{search_results}
        
Please provide a helpful response with specific hotel recommendations."""
        
        # Stream the response
        full_response = self.stream_response(llm, prompt)
        
        # Append AI response to messages
        new_messages = messages + [AIMessage(content=full_response)]
        
        return {
            "web_search_agent_response": full_response,
            "messages": new_messages
        }

    def flight_search_node(self, state: AgentState):
        flight_origin = state.get('flight_origin')
        flight_destination = state.get('flight_destination')
        flight_max_price = state.get('flight_max_price', 1000)

        # Create streaming LLM
        llm = self.create_grok_llm(streaming=True)

        # Build context from messages
        history_context = ""
        messages = state.get("messages", [])
        if len(messages) > 1:
            history_context = "\n\nPrevious conversation:\n"
            for msg in messages[-4:]:
                role = "User" if isinstance(msg, HumanMessage) else "Assistant"
                history_context += f"{role}: {msg.content}\n"

        # Provide general flight advice
        prompt = f"""Provide flight recommendations for the user's query: {state["user_query"]}
{history_context}
        
Origin: {flight_origin if flight_origin else 'Not specified'}
Destination: {flight_destination if flight_destination else 'Not specified'} 
Max Price: {flight_max_price}

Since specific flight data is not available, provide general flight booking advice including:
- Major airlines that serve the destination
- Typical flight routes and connections
- Best booking practices and timing
- Airport recommendations"""

        # Stream the response
        full_response = self.stream_response(llm, prompt)
        
        # Append AI response to messages
        new_messages = messages + [AIMessage(content=full_response)]
        
        return {
            "flight_search_agent_response": full_response,
            "messages": new_messages
        }  
      
    def conversational_node(self, state: AgentState):
        llm = self.create_grok_llm(streaming=True)
        messages = state.get("messages", [])
        
        history_context = ""
        if len(messages) > 1:
            history_context = "\n\nPrevious conversation:\n"
            for msg in messages[-4:]:
                role = "User" if isinstance(msg, HumanMessage) else "Assistant"
                history_context += f"{role}: {msg.content}\n"
        
        prompt = f"""You are a helpful travel agent. Answer the user's query: {state["user_query"]}
{history_context}

Provide a helpful and friendly response."""
        
        full_response = self.stream_response(llm, prompt)
        new_messages = messages + [AIMessage(content=full_response)]
        
        return {
            "web_search_agent_response": full_response,
            "messages": new_messages
        }

    def route_after_entry(self, state: AgentState):
        if state.get("should_recommend_hotels"):
            return "web_search_agent"
        elif state.get("should_recommend_flights"):
            return "flight_search_agent"
        else:
            return "conversational_node"

    def route_after_hotels(self, state: AgentState):
        if state.get("should_recommend_flights"):
            return "flight_search_agent"
        else:
            return END

    def create_workflow(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("entry_node", self.entry_node)
        workflow.add_node("web_search_agent", self.web_search_node)
        workflow.add_node("flight_search_agent", self.flight_search_node)
        workflow.add_node("conversational_node", self.conversational_node)
    
        workflow.add_edge(START, "entry_node")
        workflow.add_conditional_edges(
            "entry_node",
            self.route_after_entry,
            {
                "web_search_agent": "web_search_agent",
                "flight_search_agent": "flight_search_agent",
                "conversational_node": "conversational_node"
            }
        )
        workflow.add_conditional_edges(
            "web_search_agent",
            self.route_after_hotels,
            {
                "flight_search_agent": "flight_search_agent",
                END: END
            }
        )
        workflow.add_edge("flight_search_agent", END)
        workflow.add_edge("conversational_node", END)
        return workflow.compile(checkpointer=self.memory)
    
    def run(self, state: AgentState, thread_id: str = "default"):
        config = {"configurable": {"thread_id": thread_id}}
        result = self.workflow.invoke(state, config)
        return result
    
    def run_streaming(self, state: AgentState, thread_id: str = "default"):
        config = {"configurable": {"thread_id": thread_id}}
        result = self.workflow.invoke(state, config)
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