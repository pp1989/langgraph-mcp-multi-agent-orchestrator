from http import client
import os
import asyncio
from pathlib import Path
import sys
import certifi
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from uvicorn import logging
from langchain_google_genai import ChatGoogleGenerativeAI

from switch_model import create_llm

# from mcp_client import mcp_client

PROJECT_ROOT = Path(__file__).resolve().parent
SERVER_FILE = PROJECT_ROOT / "custom_weather_mcp_server.py"
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
print(f"PROJECT_ROOT: {PROJECT_ROOT}")
print(f"SERVER_FILE: {SERVER_FILE}")
print(f"VENV_PYTHON: {VENV_PYTHON}")
print("Path:", Path)
print("Path module:", Path.__module__)
print("Resolve:", Path.resolve)
print("Resolve type:", type(Path.resolve))
print("Current Python:", sys.executable)

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
AVIATIONSTACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
print(f"TAVILY_API_KEY: {TAVILY_API_KEY}")
print(f"AVIATIONSTACK_API_KEY: {AVIATIONSTACK_API_KEY}")
print(f"OPENWEATHER_API_KEY: {OPENWEATHER_API_KEY}")


llm = create_llm(os.getenv("LLM_PROVIDER"))
print(f"LLM provider: {os.getenv('LLM_PROVIDER')}, LLM instance: {llm}")

# 1. Configure the Tavily MCP Server Map
mcp_client = MultiServerMCPClient(
    {
        "tavily": {
            "transport": "streamable_http",
            "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}",
            # "headers": {"Authorization": f"Bearer {TAVILY_API_KEY}"},
        },
        "aviationstack": {
            "transport": "stdio",
            "command": "uvx",
            "args": ["aviationstack-mcp"],
            "env": {"AVIATIONSTACK_API_KEY": AVIATIONSTACK_API_KEY},
        },
        "weather_mcp": {
            "transport": "stdio",
            "command": sys.executable,
            # "command": r"D:\Praveen\Projects\interview_prep\AI_Agents\Tripmate-AI--A-multi-agent-travel-planner\venv\Scripts\python.exe",
            # "command": str(VENV_PYTHON),
            "args": [str(SERVER_FILE)],
            "cwd": str(PROJECT_ROOT),
            # "args": [
            #     r"D:\Praveen\Projects\interview_prep\AI_Agents\Tripmate-AI--A-multi-agent-travel-planner\custom_weather_mcp_server.py"
            # ],
            "env": {"OPENWEATHER_API_KEY": OPENWEATHER_API_KEY},
        },
    }
)


# Check if the client connected with all the servers:
async def get_all_tools():
    tools = await mcp_client.get_tools()
    for tool in tools:
        print(f"✅ Successfully loaded tool: {tool.name}")
    return tools


async def avation_mcp_call(tool_name: str, tool_args: dict = None):
    # # Step 1: Get all available MCP tools
    tools = await mcp_client.get_tools()
    # Step 2: Find the requested tool
    tool = next((t for t in tools if t.name == tool_name), None)
    # Step 3: Execute the selected tool
    result = await tool.ainvoke(tool_args or {}) if tool else None
    return result
    # return "✅ Successfully loaded tool: {tool.name}" if tool else f"❌ Tool not found: {tool_name}"


# tavily search agent
tavily_search_tool = None


async def get_tavily_search_tool():
    global tavily_search_tool
    if tavily_search_tool is None:

        tools = await mcp_client.get_tools()
        print(f"available MCP tools: {tools}")
        for tool in tools:
            print(f"✅ Successfully loaded tool====>+++: {tool.name}")
            tavily_search_tool = next(
                tool for tool in tools if tool.name == "tavily_search"
            )


# this function is used to call the tavily search tool with a query in the backend.py
async def tavily_mcp_search(query: str):
    await get_tavily_search_tool()
    print(f"✅ Successfully called tavily-search tool with query:=====> {query}")
    result = await tavily_search_tool.ainvoke({"query": query})
    # print(f"✅ result:=====> {result}")
    return result

    ##################################
    # Weather MCP Server
    ##################################


weather_tool = None
forecast_tool = None


async def initialize_weather_tool():
    global weather_tool, forecast_tool
    if weather_tool is not None and forecast_tool is not None:
        return
    tools = await mcp_client.get_tools()
    print(f"available MCP tools: {tools}")
    weather_tool = next(
        (tool for tool in tools if tool.name == "get_current_weather"), None
    )
    forecast_tool = next((tool for tool in tools if tool.name == "get_forecast"), None)


async def weather_mcp_search(city: str):
    await initialize_weather_tool()
    if weather_tool is None:
        raise ValueError("Weather tool not found.")
    result = await weather_tool.ainvoke({"city": city})
    return result


async def forecast_mcp_search(city: str):
    await initialize_weather_tool()
    if forecast_tool is None:
        raise ValueError("Forecast tool not found.")
    result = await forecast_tool.ainvoke({"city": city})
    return result


################################
# destination extraction tool
################################


def extract_destination(query: str) -> str:
    # Simple extraction logic (you can improve this with NLP libraries)
    prompt = f"""Extract the destination from the following query:
    Query = {query}
    return only distination name from the query
     """
    response = llm.invoke(prompt)
    print(
        f"Extracted destination from query############################## '{query}': {response}"
    )
    destination_text = get_text_content(response.content)
    destination = destination_text.strip().strip('"').strip("`")
    if not destination:
        raise ValueError("Could not extract destination")

    return destination

    # return response.content.strip() if response else "Unknown"
    # words = query.split()
    # for i, word in enumerate(words):
    #     if word.lower() in ["to", "in", "at"]:
    #         if i + 1 < len(words):
    #             return words[i + 1]
    # return "Unknown"


########################
# Helper function
########################
def get_text_content(content) -> str:
    """Extract text safely from an LLM response."""

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        text_parts = []

        for item in content:

            if isinstance(item, str):
                text_parts.append(item)

            elif isinstance(item, dict):
                text = item.get("text")

                if isinstance(text, str):
                    text_parts.append(text)

            else:
                text = getattr(item, "text", None)

                if isinstance(text, str):
                    text_parts.append(text)

        return "\n".join(text_parts).strip()

    if isinstance(content, dict):
        text = content.get("text")

        if isinstance(text, str):
            return text.strip()

    raise TypeError(f"Expected text content, received: {type(content).__name__}")
