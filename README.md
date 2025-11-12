# 🌍 Travel Agent Assistant

An AI-powered travel agent that provides personalized hotel and flight recommendations using LangGraph workflows and a Gradio web interface.

## Features

- **Hotel Recommendations** - Web search-powered hotel suggestions using DuckDuckGo
- **Flight Information** - General flight booking advice and recommendations
- **Interactive Web UI** - Clean Gradio interface with streaming responses
- **Conversational AI** - Natural language understanding with context awareness
- **Conditional Workflows** - Smart routing based on user needs
- **Real-time Streaming** - Progressive response updates
- **Conversation Memory** - Maintains context across multiple interactions

## Architecture

- **LangGraph** - Multi-agent workflow orchestration with state management
- **LangChain** - LLM integration with streaming support
- **Gradio** - Web interface for user interaction
- **DuckDuckGo** - Web search for hotel information
- **X.AI Grok** - Language model (grok-4-fast) for responses
- **AWS Secrets Manager** - Secure credential management
- **Amadeus API** - Flight data integration (optional)

## Prerequisites

- Python 3.8+
- AWS account with configured credentials
- IAM role with Secrets Manager access
- X.AI API key
- Amadeus API credentials (optional, for flight data)

## Installation

1. **Clone the repository:**
```bash
git clone <repository-url>
cd travel-agent
```

2. **Create virtual environment:**
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Configure environment variables:**

Create a `.env` file in the project root:
```env
AWS_ROLE_ARN=arn:aws:iam::YOUR_ACCOUNT:role/YOUR_ROLE
AWS_REGION=us-east-1
XAI_SECRET_NAME=xai_api_key
```

5. **Store API keys in AWS Secrets Manager:**

Store your X.AI API key:
```bash
aws secretsmanager create-secret \
    --name xai_api_key \
    --secret-string "your-xai-api-key"
```

Store Amadeus credentials (optional):
```bash
aws secretsmanager create-secret \
    --name amadeus_api \
    --secret-string '["client_id","client_secret"]'
```

## Usage

### Web Interface (Recommended)

Launch the Gradio web application:
```bash
python gradio_app.py
```

Access at `http://localhost:7860`

**Interface Features:**
- Chat interface for natural language queries
- Optional flight details form (origin, destination, budget)
- Real-time streaming responses
- Example prompts to get started
- Conversation history maintained across interactions

**Example Queries:**
- "Find hotels in Paris for a romantic getaway"
- "I need accommodation and flights to Tokyo"
- "Best hotels in Bali under $200 per night"
- "Plan a trip to Iceland with flight options"

### Command Line Interface

Run the terminal-based chatbot:
```bash
python chatbot.py
```

### Programmatic Usage

```python
from agents import AgentWorkflow, load_credentials, get_credentials
import os

# Setup credentials
role_arn, secret_name = load_credentials()
os.environ["AWS_ROLE_ARN"] = role_arn
os.environ["XAI_SECRET_NAME"] = secret_name
api_key = get_credentials(role_arn, secret_name)
os.environ["XAI_API_KEY"] = api_key[0]

# Initialize workflow
workflow = AgentWorkflow("grok-4-fast")

# Run query
state = {
    "user_query": "Find hotels in Paris",
    "flight_origin": "NYC",
    "flight_destination": "CDG",
    "flight_max_price": 800,
    "messages": []
}
result = workflow.run_streaming(state, thread_id="session_1")

# Access results
print(result.get("web_search_agent_response"))
print(result.get("flight_search_agent_response"))
```

## Project Structure

```
travel-agent/
├── agents.py          # Core LangGraph workflow and agent logic
├── gradio_app.py      # Web interface using Gradio
├── chatbot.py         # Terminal-based chatbot
├── credentials.py     # AWS credential and secrets management
├── requirements.txt   # Python dependencies
├── .env              # Environment variables (not in git)
├── .gitignore        # Git ignore rules
└── README.md         # This file
```

## Workflow Architecture

The application uses a LangGraph state machine with the following nodes:

1. **Entry Node** - Extracts flight details and determines user intent
2. **Web Search Agent** - Searches DuckDuckGo for hotel recommendations
3. **Flight Search Agent** - Provides flight booking advice
4. **Conversational Node** - Handles general travel queries
5. **Conditional Routing** - Intelligently routes between agents based on user needs

**State Flow:**
```
START → Entry Node → [Hotels/Flights/Conversation] → END
                  ↓
            Hotels → Flights (if needed) → END
```

## Configuration

### Model Selection
Change the LLM model in `AgentWorkflow` initialization:
```python
workflow = AgentWorkflow("grok-4-fast")  # or other X.AI models
```

### Search Parameters
Modify in `agents.py`:
```python
def web_search(query: str, max_results: int = 5):  # Adjust max_results
```

### Default Flight Budget
Set in state initialization:
```python
"flight_max_price": 1000  # Default budget in USD
```

## State Management

The workflow maintains conversation state using LangGraph's `MemorySaver`:
- Conversation history preserved across turns
- Thread-based session management
- Context-aware responses

**State Schema:**
```python
{
    "user_query": str,
    "should_recommend_hotels": bool,
    "should_recommend_flights": bool,
    "web_search_agent_response": Optional[str],
    "flight_search_agent_response": Optional[str],
    "flight_origin": Optional[str],
    "flight_destination": Optional[str],
    "flight_max_price": Optional[float],
    "flight_departure_date": Optional[str],
    "flight_arrival_date": Optional[str],
    "messages": list  # Conversation history
}
```

## Dependencies

```
boto3              # AWS SDK
langchain          # LLM framework
langchain-aws      # AWS integrations
langchain-openai   # OpenAI-compatible API
langgraph          # Workflow orchestration
pydantic           # Data validation
ddgs               # DuckDuckGo search
requests           # HTTP client
gradio             # Web interface
python-dotenv      # Environment variables
```

## Security Best Practices

- API keys stored in AWS Secrets Manager (never in code)
- IAM role-based authentication
- Environment variables for configuration
- `.env` file excluded from version control
- Secure credential rotation supported

## Troubleshooting

**Issue: Credentials not loading**
- Verify AWS credentials are configured (`aws configure`)
- Check IAM role has Secrets Manager permissions
- Ensure `.env` file exists with correct values

**Issue: Web search failing**
- DuckDuckGo may rate-limit requests
- Check internet connectivity
- Reduce `max_results` parameter

**Issue: Gradio not launching**
- Check port 7860 is available
- Try `demo.launch(server_port=7861)`
- Verify all dependencies installed

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Test thoroughly
5. Commit changes (`git commit -m 'Add amazing feature'`)
6. Push to branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## License

MIT License - see LICENSE file for details

## Support

For issues and questions:
- Open a GitHub issue
- Contact the development team
- Check existing issues for solutions

## Roadmap

- [ ] Add real-time flight pricing via Amadeus API
- [ ] Implement hotel booking integration
- [ ] Add multi-language support
- [ ] Enhanced conversation memory
- [ ] User preference learning
- [ ] Export itinerary feature