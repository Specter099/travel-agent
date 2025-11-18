import gradio as gr
import os
import time
from agents import AgentWorkflow, load_credentials, get_credentials, get_flight_search_credentials
from langchain_core.messages import HumanMessage, AIMessage

# Initialize credentials
def setup_credentials():
    credentials = load_credentials()
    if credentials:
        os.environ["AWS_ROLE_ARN"] = credentials[0]
    
    role_arn = os.environ.get("AWS_ROLE_ARN")
    api_keys = get_credentials(role_arn, "api_keys")
    os.environ["XAI_API_KEY"] = api_keys[0]
    os.environ["AMADEUS_API_KEY"] = api_keys[1]
    os.environ["AMADEUS_API_SECRET"] = api_keys[2]
    os.environ["LANGSMITH_API_KEY"] = api_keys[3]
    access_token = get_flight_search_credentials(api_keys[1], api_keys[2])
    os.environ["AMADEUS_ACCESS_TOKEN"] = access_token

# Initialize workflow
setup_credentials()
workflow = AgentWorkflow("grok-4-fast")

def travel_agent_chat(message, history, origin, destination, max_price):
    if not message.strip():
        yield history, ""
        return
    
    # Add user message to history
    history.append({"role": "user", "content": message})
    #history.append({"role": "assistant", "content": ""})
    
    # Build state from inputs
    # Note: messages uses the 'add' operator, so we only pass the new message
    # LangGraph will automatically append it to the existing messages in the checkpoint
    state = {
        "user_query": message,
        "messages": [HumanMessage(content=message)],
        "flight_origin": origin.strip() if origin else None,
        "flight_destination": destination.strip() if destination else None,
        "flight_max_price": float(max_price) if max_price else 1000,
        "flight_recommendations": bool(origin or destination or "flight" in message.lower()),
        "flight_departure_date": None,
        "flight_arrival_date": None,
        "web_search_agent_response": None,
        "flight_search_agent_response": None
    }
    
    # Debug: Show what flight details were captured
    if origin or destination:
        print(f"Flight details captured - Origin: {origin}, Destination: {destination}, Max Price: {max_price}")
    
    # Show initial loading message
    history[-1]["content"] = "🔍 Searching for recommendations..."
    yield history, ""
    
    # Run workflow with consistent thread_id
    result = workflow.run_streaming(state, thread_id="gradio_session")
    
    # Format response
    response = ""
    if result.get('web_search_agent_response'):
        response += f"🏨 **Hotel Recommendations:**\n{result['web_search_agent_response']}\n\n"
        history[-1]["content"] = response
        yield history, ""
        time.sleep(0.1)  # Small delay for visual effect
    
    if result.get('flight_search_agent_response'):
        response += f"✈️ **Flight Information:**\n{result['flight_search_agent_response']}"
        history[-1]["content"] = response
        yield history, ""
    
    yield history, ""

# Create Gradio interface
with gr.Blocks(title="Travel Agent Assistant") as demo:
    gr.Markdown("# 🌍 Travel Agent Assistant")
    gr.Markdown("Get personalized hotel and flight recommendations for your next trip!")
    
    with gr.Row():
        with gr.Column(scale=2):
            chatbot = gr.Chatbot(
                height=500,
                placeholder="Ask me about hotels and flights for your destination...",
                type="messages"
            )
            with gr.Row():
                msg = gr.Textbox(
                    placeholder="Where would you like to travel?",
                    label="Your Message",
                    lines=1,
                    scale=4,
                    container=False,
                    interactive=True
                )
                submit_btn = gr.Button("Send", scale=1)
            
        with gr.Column(scale=1):
            gr.Markdown("### Flight Details (Optional)")
            origin = gr.Textbox(
                label="Departure City/Airport",
                placeholder="e.g., NYC, LHR, San Francisco"
            )
            destination = gr.Textbox(
                label="Destination City/Airport", 
                placeholder="e.g., Paris, DUB, Tokyo"
            )
            max_price = gr.Number(
                label="Max Flight Budget ($)",
                value=1000,
                minimum=0
            )
            
            gr.Markdown("### Examples")
            gr.Examples(
                examples=[
                    ["Find hotels in Paris for a romantic getaway"],
                    ["I need accommodation and flights to Tokyo"],
                    ["Best hotels in Bali under $200 per night"],
                    ["Plan a trip to Iceland with flight options"]
                ],
                inputs=msg
            )
    
    # Handle message submission (both Enter key and button click)
    msg.submit(
        travel_agent_chat,
        inputs=[msg, chatbot, origin, destination, max_price],
        outputs=[chatbot, msg]
    )
    
    submit_btn.click(
        travel_agent_chat,
        inputs=[msg, chatbot, origin, destination, max_price],
        outputs=[chatbot, msg]
    )

if __name__ == "__main__":
    demo.launch(share=True)