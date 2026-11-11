import os

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()


def create_llm(provider: str = "openai"):
    """Create a chat model from the supported providers."""
    print(f"Creating LLM with provider: {provider}")
    provider = provider.lower()

    if provider == "openai":
        return ChatOpenAI(
            model="gpt-4o", api_key=os.getenv("OPENAI_API_KEY"), temperature=0.7
        )
    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            model="gemini-3.5-flash-lite",
            # model="gemini-3.8-flash",
            api_key=os.getenv("GEMINI_API_KEY"),
            # temperature=0.7,
        )
    if provider == "groq":
        return ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=os.getenv("GROQ_API_KEY"),
            temperature=0.7,
        )

    raise ValueError(
        f"Unsupported LLM provider: {provider}. Choose 'openai', 'gemini', or 'groq'."
    )


# Set LLM_PROVIDER to: openai, gemini, or groq.
# llm = create_llm(os.getenv("LLM_PROVIDER", "openai"))
