# 🌍 Travel Agent Assistant

An AI-powered travel agent that provides personalized hotel and flight recommendations using LangGraph workflows and a Gradio web interface.

## Features

- **Hotel Recommendations** - Web search-powered hotel suggestions
- **Flight Information** - General flight booking advice and recommendations
- **Interactive Web UI** - Clean Gradio interface with streaming responses
- **Conditional Workflows** - Smart routing based on user needs
- **Real-time Streaming** - Progressive response updates

## Architecture

- **LangGraph** - Multi-agent workflow orchestration
- **LangChain** - LLM integration with streaming support
- **Gradio** - Web interface for user interaction
- **DuckDuckGo** - Web search for hotel information
- **X.AI Grok** - Language model for responses
- **AWS Secrets Manager** - Secure credential management

## Setup

### Prerequisites

- Python 3.8+
- AWS account with configured credentials
- X.AI API key
- Amadeus API credentials (optional)

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd travel-agent
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables in `.env`:
```
AWS_ROLE_ARN=your-aws-role-arn
XAI_SECRET_NAME=your-xai-secret-name
```

4. Store your API keys in AWS Secrets Manager:
   - X.AI API key in the secret specified by `XAI_SECRET_NAME`
   - Amadeus API credentials in secret named `amadeus_api`

## Usage

### Web Interface (Recommended)

Run the Gradio web application:
```bash
python gradio_app.py
```

Access the interface at `http://localhost:7860`

**Features:**
- Chat interface for natural language queries
- Flight details form (origin, destination, budget)
- Real-time streaming responses
- Example prompts to get started

### Command Line Interface

Run the terminal-based chatbot:
```bash
python chatbot.py
```

### Direct API Usage

```python
from agents import AgentWorkflow

workflow = AgentWorkflow("grok-4-fast")
state = {
    "user_query": "Find hotels in Paris",
    "flight_origin": "NYC",
    "flight_destination": "CDG",
    "flight_max_price": 800
}
result = workflow.run_streaming(state)
```

## File Structure

```
travel-agent/
├── agents.py          # Core LangGraph workflow and agents
├── gradio_app.py      # Web interface using Gradio
├── chatbot.py         # Terminal-based chatbot
├── credentials.py     # AWS credential management
├── requirements.txt   # Python dependencies
└── README.md         # This file
```

## Workflow Architecture

1. **Flight Recommendations Node** - Determines if flight info is needed
2. **Web Search Agent** - Searches for hotel recommendations
3. **Conditional Edge** - Routes to flight search if needed
4. **Flight Search Agent** - Provides flight booking advice

## Configuration

### Models
- Default: `grok-4-fast`
- Configurable in `AgentWorkflow` initialization

### Search Parameters
- Web search results: 5 (configurable)
- Default flight budget: $1000
- Streaming enabled by default

## Dependencies

```
gradio>=4.0.0
langchain-openai
langgraph
ddgs
python-dotenv
pydantic
boto3
requests
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues and questions, please open a GitHub issue or contact the development team.