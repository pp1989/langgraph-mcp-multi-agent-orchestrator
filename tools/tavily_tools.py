from tavily import TavilyClient
import os
from dotenv import load_dotenv

load_dotenv()
client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


def tavily_search(query):
    responses = client.search(query=query, max_results=5)
    results = []
    for i, r in enumerate(responses["results"], start=1):
        title = r.get("title", "unknown")
        url = r.get("url", "")
        snippet = r.get("content", "").strip()
        # keep only the 300 chars to avoid cluttering the output
        if len(snippet) > 300:
            snippet = snippet[:300].rsplit(" ", 1)[0] + "..."
        results.append({f"{i}. **{title}**\n   {url}\n   {snippet}"})
        print(results)
        return "\n\n".join(str(item) for item in results)
