from pydoc import text
from typing import Any, Annotated, TypedDict, Literal
import operator
import uuid
import json
import asyncio
import os

import certifi
from langchain_core import messages
import psycopg
from psycopg.rows import dict_row

from dotenv import load_dotenv

from langgraph.graph import StateGraph, END, START
from langgraph.types import Command, interrupt
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel, Field

from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)

from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from switch_model import create_llm

from mcp_client import (
    tavily_mcp_search,
    avation_mcp_call,
    extract_destination,
    forecast_mcp_search,
    weather_mcp_search,
)

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
load_dotenv()

# *********************************
# Structured Output Schemas
# *********************************


class GuardrailOutput(BaseModel):
    allowed: bool
    reason: str = ""


class TripConstraints(BaseModel):
    destination: str = ""
    origin: str = ""
    duration: str = ""
    budget: str = ""
    travel_style: str = ""

    special_preferences: list[str] = Field(default_factory=list)


class SupervisorOutput(BaseModel):
    selected_agents: list[
        Literal[
            "flight_agent",
            "hotel_agent",
            "weather_agent",
            "budget_agent",
            "itinerary_agent",
        ]
    ] = Field(default_factory=list)

    trip_constraints: TripConstraints = Field(default_factory=TripConstraints)

    reasoning: str = ""


def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "Database url is missing, Please add your external database url in env file"
        )
    if "sslmode=" not in database_url:
        seperator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{seperator}sslmode=require"

    return database_url


DATABASE_URL = get_database_url()
print("Database URL configured:", bool(DATABASE_URL))


# *********************************
# LLM
# *********************************

llm = create_llm(os.getenv("LLM_PROVIDER", "openai"))

# *********************************
# Supervisor System Prompts
# *********************************

GUARDRAIL_SYSTEM_PROMPT = """
You are the Guardrail Agent of TripMate AI,
a multi-agent travel planning assistant.

Your responsibility is to determine whether the
user's request is appropriate for travel planning.

ALLOW requests related to:
- Flights and airlines
- Hotels and accommodation
- Weather and climate
- Travel budgets
- Travel itineraries
- Visa and transportation
- Sightseeing and tourism
- Travel packages and travel preferences

BLOCK requests that are clearly unrelated to travel
planning or are inappropriate or unsafe.

Do not reject valid travel requests merely because
some details are missing.

Evaluate the user's request carefully.
"""


SUPERVISOR_SYSTEM_PROMPT = """
You are the Supervisor Agent of TripMate AI,
a multi-agent travel planning system.

Your responsibility is to analyze the user's travel
request and select all relevant specialist agents.

AVAILABLE AGENTS:

1. flight_agent:
   Flights, airports, airlines and flight information.

2. hotel_agent:
   Hotels, accommodation and neighbourhoods.

3. weather_agent:
   Current weather, forecasts and climate.

4. budget_agent:
   Budget estimates, cost breakdown and feasibility.

5. itinerary_agent:
   Creates the integrated travel itinerary.

RULES:

- Select every relevant specialist agent.
- Always include itinerary_agent.
- Do not select agents unnecessarily.
- Extract available travel constraints.
- Do not invent missing information.
"""


# *********************************
# Structured LLM Configuration
# *********************************

guardrail_llm = llm.with_structured_output(GuardrailOutput, method="json_schema")

supervisor_llm = llm.with_structured_output(SupervisorOutput, method="json_schema")


# *********************************
# State
# *********************************


class TravelState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], operator.add]

    user_query: str
    # supervisor guardrail state
    guardrail_allowed: bool
    guardrail_reason: str
    selected_agents: list[str]
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str
    # Original specilist results
    flight_results: dict[str, Any]
    hotel_results: dict[str, Any]
    weather_results: dict[str, Any]
    itinerary: str

    # New Budget and HITL state
    budget_results: str
    approval_request: str
    approval: str
    human_feedback: str
    final_response: str

    llm_calls: int


# **********************************
# Shared helpers
# **********************************
KNOWN_AGENTS = {
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
}
AGENT_ORDER = [
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
]


def _llm_text(system_prompt: str, user_prompt: str) -> str:
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    return str(response.content)


def _json_from_llm(text: str) -> dict[str, Any]:
    """
    Extract and parse the first valid JSON object
    from an LLM response.
    """

    if not isinstance(text, str):
        raise TypeError(f"Expected string, received {type(text).__name__}")

    text = text.strip()

    decoder = json.JSONDecoder()

    # Find the starting position of a JSON object.
    for start, char in enumerate(text):

        if char != "{":
            continue

        try:
            # raw_decode handles nested JSON objects.
            parsed, end = decoder.raw_decode(text[start:])

            if isinstance(parsed, dict):
                print("JSON successfully parsed")
                return parsed

        except json.JSONDecodeError:
            continue

    raise ValueError(f"No valid JSON object found in LLM response: {text}")


def _empty_constraint() -> dict[str, Any]:
    return {
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "special_preferences": [],
    }


# ************************************
# Supervisor Agent + Input Guardrails
# ************************************
def supervisor_agent(state: TravelState) -> TravelState:
    query = state["user_query"]
    llm_calls = state.get("llm_calls", 0)
    # Initialize defaults before try/except
    selected_agents = []
    trip_constraints = _empty_constraint()
    reasoning = ""

    guardrail_prompt = f"""
    Determine that weather the user query is appropriate for a travel planning assistant. validate request can includes destination, flight, hotel, weather, visa, transpotation, sightseeing, food package, itinerary, budget, and travel style. Block clearly inappropriate or unsafe, provide a reason and do not select an agent. If the request is appropriate. Don't block the valid request mearly because some details are missing.
    
    Return ONLY a valid JSON object.
    Do not include Markdown, explanations, or code fences.
    Follow this exact structure:
    {{
    "allowed": true,
    "reason": ""
     }}
     user_request: {query}
       
    """
    # fail open on parser/model errors; so, a temporary JSON-format does not break the orignal travel planning behaviour.
    try:
        # guardrail_raw = _llm_text(
        #     "You are a supervisor agent of a multi-agent travel planning system. Your task is to analyze the user's travel request and determine if it is appropriate for a travel planning assistant. Return only strict JSON format.",
        #     guardrail_prompt,
        # )
        # guardrail_result = _json_from_llm(guardrail_raw)

        guardrail_result = guardrail_llm.invoke(
            [
                SystemMessage(content=GUARDRAIL_SYSTEM_PROMPT),
                HumanMessage(content=f"""
        Evaluate this travel request.

        USER REQUEST:
        {query}
        """),
            ]
        )

        allowed = guardrail_result.allowed
        guardrail_reason = guardrail_result.reason
        llm_calls += 1
        print("Guardrail result:", guardrail_result.model_dump())

    except Exception as e:
        print(f"Supervisor agent error: {e}")
        allowed = True
        guardrail_reason = f"Supervisor agent error: {e}"
        # state["selected_agents"] = ""
        # state["trip_constraints"] = _empty_constraint()
        # state["supervisor_reasoning"] = f"Supervisor agent error: {e}"
        # state["llm_calls"] = llm_calls + 1

    if not allowed:
        reason = guardrail_reason or (
            "tripMate AI can only help with travel planning requests. Your request was blocked because it was deemed inappropriate or unsafe. Please ask about travel-related topics such as flights, hotels, weather, visas, transportation, sightseeing, food packages, itineraries, budgets, and travel styles."
        )

        return {
            "guardrail_allowed": False,
            "guardrail_reason": reason,
            "selected_agents": [],
            "trip_constraints": _empty_constraint(),
            "supervisor_reasoning": reason,
            "final_response": f"Your request was blocked by the supervisor agent. Reason: {reason}",
            "messages": state.get("messages", [])
            + [
                AIMessage(
                    content=f"Supervisor agent blocked the request. Reason: {reason}"
                )
            ],
            "llm_calls": llm_calls,
        }

    supervisor_prompt = f"""  
    You are a supervisor agent of a multi-agent travel planning system. Your task is to analyze the user's travel request and determine which specialized agent should handle it. The available agents are: 
    -flight_agent:flights, airports, arilines, air fare and booking advice.
    -hotel_agent:hotels,accomodation,neightborhoods,or place to stay. 
    -weather_agent:weather, climate, forecast, and travel conditions.
    -budget_agent:budgets, cost estimates, and financial planning.
    -itinerary_agent:create the interated travelplan and must always be included.
    
    return strictly in JSON format only :
    {{
        selected_agents: "flight_agent" | "hotel_agent" | "weather_agent" | "budget_agent" | "itinerary_agent",
        trip_constraints: {{
            destination: str,
            origin: str,
            duration: str,
            budget: str,
            travel_style: str,
            special_preferences: []
        }},
        reasoning: str
    }}
    
    user_request: {query}
    
    """

    try:
        # supervisor_raw = _llm_text(
        #     "Your route work to travel specilist agent, retur only strict JSON only",
        #     supervisor_prompt,
        # )
        supervisor_raw = supervisor_llm.invoke(
            [
                SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
                HumanMessage(content=f"""
                Analyze the following travel request.

                USER REQUEST:
                {query}

                Extract:
                - Relevant specialist agents
                - Destination
                - Origin
                - Duration
                - Budget
                - Travel style
                - Special preferences
                """),
            ]
        )
        selected_agents = supervisor_raw.selected_agents
        trip_constraints = supervisor_raw.trip_constraints.model_dump()
        reasoning = supervisor_raw.reasoning
        llm_calls += 1

        print("Selected agents:", selected_agents)
        print("Trip constraints:", trip_constraints)
        print("Reasoning:", reasoning)

    except Exception as exc:
        supervisor_error = str(exc)
        print(f"Supervisor agent error: {supervisor_error}")
        selected_agents = AGENT_ORDER.copy()
        trip_constraints = _empty_constraint()
        reasoning = (
            f"Supervisor parsing failed. "
            f"Using fallback workflow. Error: {supervisor_error}"
        )

    return {
        "guardrail_allowed": True,
        "guardrail_reason": guardrail_reason,
        "selected_agents": selected_agents,
        "trip_constraints": trip_constraints,
        "supervisor_reasoning": reasoning,
        "messages": [
            AIMessage(
                content=(
                    f"Supervisor selected: {', '.join(selected_agents)}. "
                    f"{reasoning}"
                )
            )
        ],
        "llm_calls": llm_calls,
    }


# **********************************
# Flight Agent
# **********************************

# flight tool prompt template:
FLIGHT_AGENT_PROMPT = """
you are a travel flight expert
USER QUERY: {query}
AIRPORTS: {airports}
AIRLINES: {airlines}
 
GENERATE A DETAILED FLIGHT PLAN FOR THE USER QUERY:
1. Linkely departure
2. Linkely arrival
3. Airlines serving the route
4. Typical flight duration
5. Estimated flight cost range 
6. peak season price warning
7. Booking advice

return consicde and practical flight information for the user query.
"""

# new Function with MCP call for flight agent:


# *********************************
# Flight Agent
# **********************************
def flight_agent(state: TravelState):

    query = state["user_query"]

    try:
        airports = asyncio.run(avation_mcp_call("list_airports"))

        airlines = asyncio.run(avation_mcp_call("list_airlines"))

        prompt = FLIGHT_AGENT_PROMPT.format(
            query=query,
            airports=str(airports)[:3000],
            airlines=str(airlines)[:3000],
        )

        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a travel research assistant. "
                        "Never invent live flight availability or ticket prices. "
                        "Clearly label estimates and unavailable data."
                    )
                ),
                HumanMessage(content=prompt),
            ]
        )

        flight_data = response.content

        return {
            "flight_results": {
                "status": "success",
                "source": "AviationStack reference data + AI analysis",
                "content": flight_data,
            },
            "messages": [response],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    except Exception as e:

        print(f"Error in flight_agent: {e}")

        return {
            "flight_results": {
                "status": "error",
                "source": "AviationStack",
                "content": None,
                "error": str(e),
            },
            "messages": [AIMessage(content="Flight research could not be completed.")],
            "llm_calls": state.get("llm_calls", 0),
        }


# *********************************
# Hotel Agent
# **********************************
def hotel_agent(state: TravelState):

    query = f"Recommend best hotels for: {state['user_query']}"

    try:

        raw_results = asyncio.run(tavily_mcp_search(query))

        hotel_data = normalize_data(raw_results)

        return {
            "hotel_results": {
                "status": "success",
                "source": "Tavily web search",
                "verified_booking_inventory": False,
                "results": hotel_data,
            },
            "messages": [AIMessage(content="Hotel research completed.")],
            "llm_calls": state.get("llm_calls", 0),
        }

    except Exception as e:

        print(f"Hotel agent error: {e}")

        return {
            "hotel_results": {
                "status": "error",
                "source": "Tavily",
                "results": [],
                "error": str(e),
            },
            "messages": [AIMessage(content="Hotel research failed.")],
            "llm_calls": state.get("llm_calls", 0),
        }


# *********************************
# Weather Agent
# *********************************
def weather_agent(state: TravelState):

    query = state["user_query"]
    city = extract_destination(query)

    try:
        if not isinstance(city, str) or not city.strip():
            raise ValueError("Could not identify a destination city.")

        city = city.strip()

        weather_data = asyncio.run(weather_mcp_search(city))
        forecast_data = asyncio.run(forecast_mcp_search(city))

        return {
            "weather_results": {
                "status": "success",
                "city": city,
                "current": normalize_data(weather_data),
                "forecast": normalize_data(forecast_data),
            },
            "messages": [AIMessage(content=f"Weather research completed for {city}.")],
            "llm_calls": state.get("llm_calls", 0),
        }

    except Exception as exc:

        print(f"Weather agent error: {exc}")

        return {
            "weather_results": {
                "status": "error",
                "city": str(city),
                "error": str(exc),
            },
            "messages": [AIMessage(content="Weather research could not be completed.")],
            "llm_calls": state.get("llm_calls", 0),
        }


# *********************************
# Budget Agent
# *********************************
def budget_agent(state: TravelState):
    query = state["user_query"]

    prompt = f"""
    You are a travel budget expert. Analyze the user's travel request and provide a detailed budget breakdown.

    USER QUERY:
    {query}
    
    TRIP CONSTRAINTS:
    {state.get("trip_constraints", {})}
    
    FLIGHT RESULTS:
    {state.get("flight_results", {})}
    
    HOTEL RESULTS:
    {state.get("hotel_results", {})}
    
    WEATHER RESULTS:
    {state.get("weather_results", {})}
    

    RETURN THE FOLLOWING INFORMATION:
    1. Estimated cost categories.
    2. Budget risk area.
    3. Money-saving suggestions.
    4. Overall feasibility
    5. Cost breakdown (flights, hotels, food, activities)
    6. Budgeting tips and recommendations
    
    if exact live prices are unavailable clealy label estimited as aproximate and Return the output in a clear and concise format.
    """

    response = llm.invoke(
        [
            SystemMessage(content="You are a travel budget planning assistant."),
            HumanMessage(content=prompt),
        ]
    )

    return {
        "budget_results": response.content,
        "messages": [AIMessage(content="Budget assesment generated.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# *********************************
# Itinerary Agent
# *********************************
def itinerary_agent(state: TravelState):

    prompt = f"""
    Create a practical travel itinerary.

     USER QUERY:
    {state['user_query']}
        
    TRIP CONSTRAINTS:
    {state.get("trip_constraints", {})}
    
    FLIGHT RESULTS:
    {state.get("flight_results", {})}
    
    HOTEL RESULTS:
    {state.get("hotel_results", {})}
    
    WEATHER RESULTS:
    {state.get("weather_results", {})}
    
    BUDGET RESULTS:
    {state.get("budget_results", {})}
        

    RULES:
    1. Follow the user's travel duration and budget.
    2. Group sightseeing locations geographically.
    3. Consider travel time between locations.
    4. Consider weather when planning outdoor activities.
    5. Do not invent flight bookings or hotel reservations.
    6. Clearly identify estimates and missing information.
    7. Do not exceed the user's stated budget without explaining why.
    """

    response = llm.invoke(
        [
            SystemMessage(content="You are an expert travel itinerary planner."),
            HumanMessage(content=prompt),
        ]
    )

    approval_request = (
        "please review the generated draft itinerary. approve it to create the"
        "final polished plan or provide feedback for revision"
    )

    return {
        "itinerary": response.content,
        "approval_request": approval_request,
        "messages": [AIMessage(content="Draft itirnerary created for human reviews")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# *********************************
# Human in the loop Approval
# *********************************
def human_approval_agent(state: TravelState):

    print("\n========== HITL NODE ENTERED ==========")

    print("Draft itinerary available:", bool(state.get("itinerary")))

    print("Approval request:", state.get("approval_request"))

    review = interrupt(
        {
            "question": "Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get("approval_request", ""),
            "selected_agents": state.get("selected_agents", []),
            "supervisor_reasoning": state.get("supervisor_reasoning", ""),
            "expected_response": {
                "approved": True,
                "feedback": "Optional revision feedback",
            },
        }
    )

    print("Human review received:", review)

    approved = bool(review.get("approved", False))
    human_feedback = str(review.get("feedback","")).strip()

    return {
        "approved": approved,
        "human_feedback": human_feedback,
        "messages": [AIMessage(content="Human approval step completed.")],
    }


# *********************************
# Final Agent
# *********************************
def final_agent(state: TravelState):
    if state.get("approved", False):
        review_instruction = (
            "The user approved the draft. preserve the decision while polishing it."
        )
    else:
        review_instruction = f""" 
            The user requested a revision apply this feedback carefully:
            {state.get('human_feedback','')
            or 'improve the draft before the finalizing it.'}
        """

    final_prompt = f"""
    Prepare the final travel plan using the information below.
    
    HUMAN REVIEW:
    {review_instruction}
    
    USER REQUEST:
    {state["user_query"]}

    SUPERVISOR CONSTRAINTS:
    {state.get("trip_constraints","")}
    
    FLIGHTS:
    {state.get("flight_results","")}

    HOTELS:
    {state.get("hotel_results","")}

    WEATHER:
    {state.get("weather_results","")}

    BUDGET ANALYSIS:
    {state.get("budget_results","")}
    
    DRAFT ITINERARY:
    {state.get("itinerary","")}

    OUTPUT SECTIONS:
    1. Trip Summary
    2. Flight Information
    3. Hotel Suggestions
    4. Weather Information
    5. Day-by-Day Itinerary
    6. Estimated Budget
    7. Final Recommendations

    IMPORTANT:
    - Never claim that a booking has been made.
    - Never invent live prices or availability.
    - Clearly label estimated costs.
    - Mention unavailable data.
    - Keep the answer practical and concise.
    -incorporate the human feedback when revision was requested
    """

    response = llm.invoke(
        [
            SystemMessage(
                content="You are a professional AI travel planning assistant."
            ),
            HumanMessage(content=final_prompt),
        ]
    )

    return {
        "answer": response.content,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# *********************************
# Dynamic Supervisor Routing
# *********************************

ROUTE_MAP = {
    "flight_agent": "flight_agent",
    "hotel_agent": "hotel_agent",
    "weather_agent": "weather_agent",
    "budget_agent": "budget_agent",
    "itinerary_agent": "itinerary_agent",
    "human_approval": "human_approval",
    "final_agent": "final_agent",
    "guardrail_blocked": "guardrail_blocked",
}


def selected_agents(state: TravelState):
    selected = state.get("selected_agents", [])
    return [agent for agent in AGENT_ORDER if agent is selected]


def route_from_supervisor(state: TravelState) -> str:
    if not state.get("guardrail_allowed", True):
        return "guardrail_blocked"
    selected = state.get("selected_agents", [])
    selected = selected if isinstance(selected, list) else [selected]
    return next(
        (agent for agent in selected if agent in KNOWN_AGENTS), "itinerary_agent"
    )


def route_after_agent(state: TravelState) -> str:

    selected = state.get("selected_agents", [])

    if isinstance(selected, str):
        selected = [selected]

    selected = set(selected)

    # Itinerary agent must always execute
    selected.add("itinerary_agent")

    completed = set()

    if state.get("flight_results"):
        completed.add("flight_agent")

    if state.get("hotel_results"):
        completed.add("hotel_agent")

    if state.get("weather_results"):
        completed.add("weather_agent")

    if state.get("budget_results"):
        completed.add("budget_agent")

    if state.get("itinerary"):
        completed.add("itinerary_agent")

    next_agent = next(
        (
            agent
            for agent in AGENT_ORDER
            if agent in selected and agent not in completed
        ),
        None,
    )

    print("\n========== ROUTING DEBUG ==========")
    print("Selected agents:", selected)
    print("Completed agents:", completed)
    print("Next agent:", next_agent)

    if next_agent:
        print("Routing to:", next_agent)
        return next_agent

    print("All agents completed.")
    print("Routing to: human_approval")
    print("===================================\n")

    return "human_approval"


def guardrail_blocked(state: TravelState) -> TravelState:
    return {
        "answer": state.get(
            "final_response", "This request is outside the travel-planning scope."
        ),
        "messages": [AIMessage(content="Request blocked by the travel supervisor.")],
    }


# *********************************
# Build Graph
# *********************************
graph = StateGraph(TravelState)

graph.add_node("supervisor_agent", supervisor_agent)
graph.add_node("guardrail_blocked", guardrail_blocked)
graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("budget_agent", budget_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("human_approval", human_approval_agent)
graph.add_node("final_agent", final_agent)

graph.add_edge(START, "supervisor_agent")
graph.add_conditional_edges("supervisor_agent", route_from_supervisor, ROUTE_MAP)
for agent_name in KNOWN_AGENTS:
    graph.add_conditional_edges(agent_name, route_after_agent, ROUTE_MAP)
graph.add_edge("guardrail_blocked", END)
graph.add_edge("human_approval", "final_agent")
graph.add_edge("final_agent", END)

# *********************************
# Postgres checkpointer
# *********************************
DATABASE_URL = get_database_url()

_conn = psycopg.connect(
    DATABASE_URL,
    autocommit=True,
    row_factory=dict_row,
    connect_timeout=10,
)

checkpointer = PostgresSaver(_conn)
checkpointer.setup()

travel_graph = graph.compile(checkpointer=checkpointer)


# *********************************
# helper Functions For fastAPI
# *********************************


def _interrupt_payload(result: dict[str, Any]):

    interrupts = result.get("__interrupt__", [])

    if not interrupts:
        return None

    first_interrupt = interrupts[0]

    payload = getattr(first_interrupt, "value", first_interrupt)

    return payload if isinstance(payload, dict) else {"value": payload}


def _serialized_result(result: dict[str, Any], thread_id: str) -> dict[str, Any]:

    messages = result.get("messages", [])
    last_message = messages[-1].content if messages else ""

    interrupt_payload = _interrupt_payload(result)

    itinerary = (
        interrupt_payload.get("draft_itinerary", "")
        if interrupt_payload
        else result.get("itinerary", "")
    )

    answer = (
        itinerary
        if interrupt_payload
        else result.get("answer") or result.get("final_response") or last_message
    )

    return {
        "thread_id": thread_id,
        "answer": answer,
        "requires_approval": interrupt_payload is not None,
        "approval_request": (
            interrupt_payload.get("approval_request", "")
            if interrupt_payload
            else result.get("approval_request", "")
        ),
        "flight_results": normalize_data(result.get("flight_results", {})),
        "hotel_results": normalize_data(result.get("hotel_results", {})),
        "weather_results": normalize_data(result.get("weather_results", {})),
        "budget_results": normalize_data(result.get("budget_results", "")),
        "itinerary": itinerary,
        "selected_agents": result.get("selected_agents", []),
        "trip_constraints": result.get("trip_constraints", {}),
        "supervisor_reasoning": result.get("supervisor_reasoning", ""),
        "guardrail_allowed": result.get("guardrail_allowed", True),
        "guardrail_reason": result.get("guardrail_reason", ""),
        "approved": result.get("approved", False),
        "human_feedback": result.get("human_feedback", ""),
        "llm_calls": result.get("llm_calls", 0),
    }


def run_travel_agent(user_input: str, thread_id: str | None = None):

    # Generate a thread ID only for a new conversation.
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "messages": [HumanMessage(content=user_input)],
        "user_query": user_input,
        "guardrail_allowed": True,
        "guardrail_reason": "",
        "selected_agents": [],
        "trip_constraints": _empty_constraint(),
        "supervisor_reasoning": "",
        "human_feedback": "",
        "flight_results": {},
        "hotel_results": {},
        "weather_results": {},
        "budget_results": "",
        "itinerary": "",
        "approval_request": "",
        "approved": False,
        "final_response": "",
        "llm_calls": 0,
    }

    # results = travel_graph.invoke(
    #     initial_state,
    #     config=config,
    # )
    # return _serialized_result(results, thread_id)

    results = travel_graph.invoke(initial_state, config=config)
    print("\n========== GRAPH RESULT DEBUG ==========")

    print("Result keys:", list(results.keys()))

    print("Interrupt:", results.get("__interrupt__"))

    snapshot = travel_graph.get_state(config)

    print("Pending nodes:", snapshot.next)

    print("Saved itinerary:", bool(snapshot.values.get("itinerary")))

    print("========================================\n")

    return _serialized_result(results, thread_id)


def resume_travel_agent(thread_id: str, approved: bool, feedback: str = ""):
    """
    Resume the paused langgrapg thread after human review.
    """
    if not thread_id:
        raise ValueError("thread id is required to resume a travel plan.")

    config = {"configurable": {"thread_id": thread_id}}
    result = travel_graph.invoke(
        Command(resume={"approved": approved, "feedback": feedback.strip()}),
        config=config,
    )
    return _serialized_result(result, thread_id)


def get_mock_travel_response():
    return {
        "success": True,
        "thread_id": "mock_thread",
        "answer": "This is a mock travel plan.",
    }


def normalize_data(data: Any) -> Any:
    """
    Convert LangChain, LangGraph and MCP results
    into JSON-serializable Python data.
    """

    if data is None:
        return None

    # LangChain message
    if isinstance(data, AIMessage):
        return normalize_data(data.content)

    # Pydantic models and MCP content objects
    if hasattr(data, "model_dump"):
        return normalize_data(data.model_dump())

    # Dictionary
    if isinstance(data, dict):

        # MCP text content block
        if data.get("type") == "text" and isinstance(data.get("text"), str):
            return normalize_data(data["text"])

        return {key: normalize_data(value) for key, value in data.items()}

    # List
    if isinstance(data, (list, tuple)):
        return [normalize_data(item) for item in data]

    # Plain text or serialized JSON
    if isinstance(data, str):

        try:
            parsed = json.loads(data)
            return normalize_data(parsed)

        except json.JSONDecodeError:
            return data

    # JSON primitive types
    if isinstance(data, (int, float, bool)):
        return data

    return str(data)

def get_saved_travel_data(thread_id: str) -> dict:

    if not thread_id:
        raise ValueError("Thread ID is required.")

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    # Retrieve the latest saved graph state
    snapshot = travel_graph.get_state(config)

    if not snapshot or not snapshot.values:
        raise ValueError(
            f"No saved travel data found for thread: {thread_id}"
        )

    return snapshot.values