from http import client
import os
import asyncio
import certifi
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# 1. Configure the Tavily MCP Server Map
mcp_client = MultiServerMCPClient(
    {
        "tavily": {
            "transport": "streamable_http",
            "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}",
            "headers": {"Authorization": f"Bearer {TAVILY_API_KEY}"},
        }
    }
)


async def get_all_tools():
    tools = await mcp_client.get_tools()
    for tool in tools:
        print(f"✅ Successfully loaded tool: {tool.name}")
        # return tools


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
                tool for tool in tools 
                if tool.name == "tavily_search"
            )


# this function is used to call the tavily search tool with a query in the backend.py
async def tavily_mcp_search(query: str):
    await get_tavily_search_tool()
    print(f"✅ Successfully called tavily-search tool with query:=====> {query}")
    result = await tavily_search_tool.ainvoke({"query": query})
    print(f"✅ result:=====> {result}")
    return result
