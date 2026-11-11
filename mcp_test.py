import asyncio
# from mcp_client_test import client, get_all_tools, tavily_mcp_search
from mcp_client import get_all_tools
    
if __name__ == "__main__":
    # query = "latest news about AI?"
    # asyncio.run(tavily_mcp_search(query))
    asyncio.run(get_all_tools())
    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(get_all_tools())
                    