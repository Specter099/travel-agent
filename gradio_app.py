import gradio as gr
import os
import time
import threading
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
workflow_lock = threading.Lock()  # Ensure thread-safe access to workflow

def travel_agent_chat(message, history, origin, destination, max_price):
    if not message.strip():
        yield history, ""
        return

    # Add user message to history
    history.append({"role": "user", "content": message})

    # Debug: Check current state before running workflow
    config = {"configurable": {"thread_id": "gradio_session"}}
    existing_state = workflow.workflow.get_state(config)
    existing_messages = existing_state.values.get("messages", []) if existing_state.values else []
    print(f"[DEBUG] Before workflow: {len(existing_messages)} existing messages in checkpoint")
    # Show ALL messages with their actual indices
    for i in range(len(existing_messages)):
        msg = existing_messages[i]
        msg_type = type(msg).__name__
        content_preview = msg.content[:40] if len(msg.content) > 40 else msg.content
        print(f"[DEBUG]   Message[{i}]: {msg_type}: {content_preview}...")

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

    print(f"[DEBUG] Sending new user message: '{message}'")

    # Debug: Show what flight details were captured
    if origin or destination:
        print(f"Flight details captured - Origin: {origin}, Destination: {destination}, Max Price: {max_price}")

    # Track current responses
    hotel_response = {"content": ""}
    flight_response = {"content": ""}
    conversational_response = {"content": ""}
    workflow_done = {"done": False}

    # Setup streaming callback to capture LLM tokens
    def streaming_callback(partial_response, response_type):
        if response_type == "hotel":
            hotel_response["content"] = partial_response
        elif response_type == "flight":
            flight_response["content"] = partial_response
        elif response_type == "conversational":
            conversational_response["content"] = partial_response

    workflow.streaming_callback = streaming_callback

    # Show initial loading message
    history[-1]["content"] = "🔍 Searching for recommendations..."
    yield history, ""

    # Run workflow in background thread
    def run_workflow():
        try:
            with workflow_lock:
                for event in workflow.run_streaming(state, thread_id="gradio_session"):
                    # Debug: Log message count
                    msg_count = len(event.get('messages', []))
                    print(f"[DEBUG] Event has {msg_count} messages")
        finally:
            workflow_done["done"] = True
            # Debug: Check final state
            config = {"configurable": {"thread_id": "gradio_session"}}
            final_state = workflow.workflow.get_state(config)
            final_messages = final_state.values.get("messages", []) if final_state.values else []
            print(f"[DEBUG] Final state has {len(final_messages)} messages")
            # Show ALL messages with their actual indices
            for i in range(len(final_messages)):
                msg = final_messages[i]
                msg_type = type(msg).__name__
                content_preview = msg.content[:60] if len(msg.content) > 60 else msg.content
                print(f"[DEBUG]   Message[{i}]: {msg_type}: {content_preview}...")

    workflow_thread = threading.Thread(target=run_workflow)
    workflow_thread.start()

    # Stream updates to Gradio while workflow runs
    try:
        last_hotel = ""
        last_flight = ""
        last_conversational = ""

        while not workflow_done["done"] or hotel_response["content"] != last_hotel or flight_response["content"] != last_flight or conversational_response["content"] != last_conversational:
            current_hotel = hotel_response["content"]
            current_flight = flight_response["content"]
            current_conversational = conversational_response["content"]

            # Update UI if content changed
            if current_hotel != last_hotel or current_flight != last_flight or current_conversational != last_conversational:
                # Determine what type of response we have
                if current_conversational:
                    # Simple conversational response (no hotel/flight)
                    history[-1]["content"] = current_conversational
                elif current_flight:
                    if current_hotel:
                        # Both hotel and flight
                        history[-1]["content"] = f"🏨 **Hotel Recommendations:**\n{current_hotel}\n\n✈️ **Flight Information:**\n{current_flight}"
                    else:
                        # Flight only
                        history[-1]["content"] = f"✈️ **Flight Information:**\n{current_flight}"
                elif current_hotel:
                    # Hotel only
                    history[-1]["content"] = f"🏨 **Hotel Recommendations:**\n{current_hotel}"

                yield history, ""
                last_hotel = current_hotel
                last_flight = current_flight
                last_conversational = current_conversational

            time.sleep(0.1)  # Check for updates every 100ms

        workflow_thread.join()
    finally:
        workflow.streaming_callback = None

    # Final yield to ensure last state is shown
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