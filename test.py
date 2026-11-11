from tools.tavily_tools import tavily_search
from tools.flight_tool import search_flights
from backend import run_travel_agent

# res = tavily_search("best Hotels in India")
# print(res)
# res = search_flights("Plan a 7 days Nepal trip from Bangladesh:")
# res = search_flights("7 days plan from new york to tokyo:")
user_input = input("Enter your travel plan: ")
response = run_travel_agent(user_input=user_input, thread_id="test_id")
# res = search_flights(user_input)

print(f"Final Response---------------------->: {response['answer']}")
# res = run_travel_agent("plan a complete 7 days trip from India to Bangladesh, including flights, hotels and sight seeing under 2 lakhs", "test_id")
# print(f"FINAL RESULT ======>{res}")

# 'plan a complete 7 days trip from India to Bangladesh, including flights, hotels and sight seeing under 1.5 lakhs'
