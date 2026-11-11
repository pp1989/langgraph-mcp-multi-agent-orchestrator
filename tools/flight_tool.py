import os
import re
import certifi
import requests
import airportsdata
import pycountry
from dotenv import load_dotenv

load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

API_KEY = os.getenv("AVIATIONSTACK_API_KEY")

DEFAULT_ORIGIN_IATA = os.getenv(
    "DEFAULT_ORIGIN_IATA", "DEL"
)  # Default origin airport IATA code

BASE_URL = "http://api.aviationstack.com/v1/flights"
AIRTPORT_DATA = airportsdata.load()
# Filter to include only airports where the country code is 'IN'
# india_airports = {key: value for key, value in airportsdata.load().items() if value.get('country') == 'IN'}

# # Print the first 5 Indian airports to verify
# for key, value in list(india_airports.items())[:10]:
#     print(f"keyssssssssssssssssss===========>{key}: {value['name']} ({value['city']})")


COUNTRY_ALIASES = {
    "United States": "US",
    "United Kingdom": "GB",
    "South Korea": "KR",
    "North Korea": "KP",
    "Russia": "RU",
    "Iran": "IR",
    "Vietnam": "VN",
    "Syria": "SY",
    "Venezuela": "VE",
    "Iraq": "IQ",
    "India": "IN",
    "Bangladesh": "BD",
    "japan": "JP",
    "Nepal": "NP"
}

COUNTRY_MAIN_AIRPORTS = {
    "US": "JFK",
    "GB": "LHR",
    "KR": "ICN",
    "KP": "FNJ",
    "RU": "SVO",
    "IR": "IKA",
    "VN": "SGN",
    "SY": "DAM",
    "VE": "CCS",
    "IQ": "BGW",
    "IN": "DEL",
    "BD": "DAC",
    "JP": "NRT",
    "NP": "BIR"
}

CITY_MAIN_AIRPORTS = {
    "New York": "JFK",
    "London": "LHR",
    "Seoul": "ICN",
    "Pyongyang": "FNJ",
    "Moscow": "SVO",
    "Tehran": "IKA",
    "Ho Chi Minh City": "SGN",
    "Damascus": "DAM",
    "Caracas": "CCS",
    "Baghdad": "BGW",
    "Delhi": "DEL",
    "Dhaka": "DAC",
    "Tokyo": "NRT",
    "Kathmandu": "BIR"
}

def clean_text(text: str) -> str:
    """Clean the text by removing unwanted characters and formatting."""
    text = text.lower().strip()
    text = re.sub(r"[^a-zA-Z0-9\s]", "", text)  # Remove special characters
    # Replace multiple spaces with a single space
    text = re.sub(r"\s+", " ", text)

    stop_words = [
        "flight",
        "flights",
        "airline",
        "including"
        "airport",
        "airports",
        "departures",
        "arrivals",
        "departure",
        "arrival",
        "plane",
        "planes",
        "aircraft",
        "airplanes",
        "airplane",
        "complete",
        "day",
        "days",
        "include",
        "hotel",
        "hotels",
        "sightseen",
        "sightseeing",
        "tour",
        "tours",
        "trip",
        "trips",
        "travel",
        "travels",
        "journey",
        "journeys",
        "vacation",
        "vacations",
        "holiday",
        "holidays",
        "budgets",
        "info",
        "information",
    ]
    words = [w for w in text.split() if w not in stop_words]
    return " ".join(words).strip()

def country_name_to_code(text: str) -> str:
    text = clean_text(text)

    if text in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[text]

    try:
        country = pycountry.countries.lookup(text)
        return country.alpha_2
    except LookupError:
        pass  # If not found, continue to check the alias dictionary

    # Detext the country name inside the longer text
    for country in pycountry.countries:
        if country.name.lower() in text:
            return country.alpha_2

    for aliases, code in COUNTRY_ALIASES.items():
        if aliases.lower() in text:
            return code

    return None  # Return None if no match is found

def airport_country_match(airport: dict, country_code: str) -> bool:
    airport_country = str(airport.get("country","")).upper().strip()
    if airport_country == country_code:
        return True
    
    try:
        country = pycountry.countries.lookup(airport_country)
        return country.alpha_2 == country_code

    except Exception:
        pass
    return False

def get_best_airport_for_country(country_code: str) -> str:
    """Get the best airport IATA code for a given country code."""
    preferred_airports = COUNTRY_MAIN_AIRPORTS.get(country_code)
    if preferred_airports and preferred_airports in AIRTPORT_DATA:
        return preferred_airports
    
    candidate_airports = []
    for iata, airport in AIRTPORT_DATA.items():
        if not iata or not airport.get("country"):
            continue  # Skip if IATA code is missing
    
        if airport_country_match(airport, country_code):
           name=str(airport.get("name", "")).lower()
           city=str(airport.get("city", "")).lower()
        
           score = 0
           if name and "international" in name:
                score += 50
           if "intl" in name or "intl" in city:
                score += 40
           if "capital" in name or "capital" in city:
                score += 20
            
           if "main" in name or "main" in city:
                score += 5
           candidate_airports.append((score, iata))
    
    if not candidate_airports:
        return None  # No airports found for the country 
    
    candidate_airports.sort(reverse=True)
    return candidate_airports[0][1]  # Return the IATA code of the best airport
            
def resolve_location_to_iata(location: str) -> str:
    """Resolve a location (country or city) to its best airport IATA code."""
    if not location:
        return None  # Return None if the location is empty or None
    raw_location = location.strip()
    # direct iata code check
    if re.fullmatch(r"[A-Za-z]{1,30}", raw_location):
        code = raw_location.upper()
        if code in AIRTPORT_DATA:
            return code
        
    location_clean = clean_text(raw_location)
    if not location_clean:
        return None  # Return None if the cleaned location is empty
    # City preference airport check
    if location_clean in CITY_MAIN_AIRPORTS:
        return CITY_MAIN_AIRPORTS[location_clean]
    
    
    # Check if the location is a country
    country_code = country_name_to_code(location_clean)
    if country_code:
        airport_code = get_best_airport_for_country(country_code)
        if airport_code:
            return airport_code

   
    # If not a country, check if it's a city
    # Exact city match in the airport data
    city_match=[]

    for iata, airport in AIRTPORT_DATA.items():
        if not iata or not airport.get("city"):
            city = str(airport.get("city", "")).lower()
            name = str(airport.get("name", "")).lower()
            
            score = 0
        
            if city == location_clean:
                score += 100
            
            elif name == location_clean:
                score += 50
        
            elif "international" in name:
                score += 10
        
            if score > 0:
               city_match.append((score, iata))
        
    if city_match:
        city_match.sort(reverse=True)
        return city_match[0][1]  # Return the IATA code of the best matching city            

    return None  # Return None if no match is found

def find_location_mention(query: str) -> str:
    # This function can be implemented to find location mentions in the query
    q= query.lower()
    mentions = []
    # check country aliases
    for aliases in COUNTRY_ALIASES:
        if re.search(rf"\b{re.escape(aliases.lower())}\b", q):
            mentions.append(aliases)

    
    # Country name check using pycountry
    for country in pycountry.countries:
        name = country.name.lower()
        if len(name) > 4 and re.search(rf"\b{re.escape(name)}\b", q):
            mentions.append(country.name)
            
    #City name check from our prefered city map
    for city in CITY_MAIN_AIRPORTS:
        if re.search(rf"\b{re.escape(city.lower())}\b", q):
            mentions.append(city) 
     
    # REmove duplicates while preserving order
    unique_mentions = []
    for item in mentions:
        if item not in unique_mentions:
            unique_mentions.append(item)
    return unique_mentions[0] if unique_mentions else None        

def parse_route(query: str):
    print(f"Parsing route from query: '{query}'")
    """Parse the route from the query and return departure and arrival IATA codes."""
    q= query.strip()
    q_lower = q.lower()
    # Global all country mentions in the query
    global_keywords=[
       "all country", "global","global flight","global flights", "worldwide flight", "worldwide flights", "international flight", "international flights", "international travel", "international travel info", "international travel information"
     ]
    # global_keywords=[
    #     "flight", "flights", "airline", "airport", "airports","all country", "global", "worldwide flight", "worldwide flights", "international flight", "international flights", "international travel", "international travel info", "international travel information", "trip", "trips", "travel", "travels", "journey", "journeys", "vacation", "vacations", "holiday", "holidays", "info", "information", "plan", "plans"
    #  ]
    
    if any(keyword in q_lower for keyword in global_keywords):
        return None, None  # Return None for both if the query is about global or international flights
    
    # Direct IATA code check
    codes = re.findall(r"\b[A-Z]{3}\b", q)
    if len(codes) >= 2:
        deps_code = codes[0].upper()
        arrs_code = codes[1].upper()
        
        # if deps_code in AIRTPORT_DATA and arrs_code in AIRTPORT_DATA:
        #    return deps_code, arrs_code  # Return the first two IATA codes found in the query
    
    # Pattern matching for "from <location> to <location>" or "<location> to <location>"
    match = re.search(r"from\s+(.+?)\s+to\s+(.+)", q_lower)
    if match:
        orign_text = match.group(1).strip()
        dest_text = match.group(2).strip()
        dep_iata = resolve_location_to_iata(orign_text)
        arr_iata = resolve_location_to_iata(dest_text)
        return dep_iata, arr_iata
    
    #pattern flight from location(X)
    match = re.search(r"flight\s+from\s+(.+)", q_lower)
    if match:
        orign_text = match.group(1).strip()
        dep_iata = resolve_location_to_iata(orign_text)
        return dep_iata, None
    
    # pattern flight to location(Y)
    match = re.search(r"flight\s+to\s+(.+)", q_lower)
    if match:
        dest_text = match.group(1).strip()
        arr_iata = resolve_location_to_iata(dest_text)
        return None, arr_iata
    
    # Fallback to finding country or city mentions in the query
    mentions = find_location_mention(q)
    
    if mentions and len(mentions) >= 2:
        dep_iata = resolve_location_to_iata(mentions[0])
        arr_iata = resolve_location_to_iata(mentions[1])
        return dep_iata, arr_iata
    
    if len(mentions) == 1:
        dep_iata = resolve_location_to_iata(mentions[0])
        return DEFAULT_ORIGIN_IATA, arr_iata  # Use default origin if only one location is mentioned
    
    return None, None  # Return None for both if no valid route is found

def formate_flight_info(flight: dict) -> str:
    """Format flight information into a readable string."""
    airline = flight.get("airline", {}).get("name", "Unknown Airline")
    flight_number = flight.get("flight", {}).get("number", "Unknown Flight Number")
    status = flight.get("flight_status", "Unknown Status")
    dep = flight.get("departure", {}).get("iata", "Unknown IATA")
    arr = flight.get("arrival", {}).get("iata", "Unknown IATA")
    departure_airport = flight.get("departure", {}).get("airport", "Unknown Departure Airport")
    departure_time = flight.get("departure", {}).get("estimated", "Unknown Departure Time")
    departure_terminal = flight.get("departure", {}).get("terminal", "Unknown Departure Terminal")
    departure_gate = flight.get("departure", {}).get("gate", "Unknown Departure Gate")
    departure_scheduled_time = flight.get("departure", {}).get("scheduled", "Unknown Departure Scheduled Time")
    departure_airport_code = flight.get("departure", {}).get("iata", "Unknown Departure Airport Code")
    departure_delay = flight.get("departure", {}).get("delay", "Unknown Departure Delay")
    departure_delay_text = flight.get("departure", {}).get("delay_text", "Unknown Departure Delay Text")
    
    arrival_airport = flight.get("arrival", {}).get("airport", "Unknown Arrival Airport")
    arrival_time = flight.get("arrival", {}).get("estimated", "Unknown Arrival Time")
    arrival_terminal = flight.get("arrival", {}).get("terminal", "Unknown Arrival Terminal")
    arrival_iata = flight.get("arrival", {}).get("iata", "Unknown Arrival IATA")
    arrival_gate = flight.get("arrival", {}).get("gate", "Unknown Arrival Gate")
    arrival_scheduled_time = flight.get("arrival", {}).get("scheduled", "Unknown Arrival Scheduled Time")
    arrival_delay = flight.get("arrival", {}).get("delay", "Unknown Arrival Delay")
    arrival_delay_text = flight.get("arrival", {}).get("delay_text", "Unknown Arrival Delay Text")
    
    return f"""**{airline} 
Flight {flight_number}** 
status: {status}
Departure: {departure_airport} ({dep}) at {departure_time} (Terminal: {departure_terminal}, Gate: {departure_gate}, Scheduled: {departure_scheduled_time}, Delay: {departure_delay} mins, Delay Info: {departure_delay_text})
Arrival: {arrival_airport} ({arr}) at {arrival_time} (Terminal: {arrival_terminal}, Gate: {arrival_gate} arrival_iata:{arrival_iata}, Scheduled: {arrival_scheduled_time}, Delay: {arrival_delay} mins, Delay Info: {arrival_delay_text})
\n""".strip()
        
def search_flights(query: str, limit: int =10) -> str:
    """Search for flights based on the provided location."""
    if not API_KEY:
        return "API key is not set. Please set the AVIATIONSTACK_API_KEY environment variable."
    dep_iata, arr_iata = parse_route(query)
    params = {
        "access_key": API_KEY, 
        "limit": min(limit,100),  # Limit the number of results to a maximum of 100
    }
    if dep_iata:
        params["dep_iata"] = dep_iata
    
    if arr_iata:
        params["arr_iata"] = arr_iata   
        print(f"arrival and departure--->{arr_iata,dep_iata}")
        return 
    try:
        response = requests.get(url=BASE_URL, params=params, timeout=30)
        response.raise_for_status()  # Raise an error for bad responses
        data = response.json()   
    except requests.exceptions.RequestException as e:
        return f"Error fetching flight data: {e}"
    except ValueError:
        return "Error parsing flight data. The response was not valid JSON."
    
    if "error" in data:
        error = data["error"]
        return ("flight data API returned an error:\n"
                f"Code: {error.get('code', 'N/A')}\n"
            f"Error fetching flight data: {data['error']}")
    
    flight_data = data.get("data", [])
    
    if not flight_data:
        route_text = "No flights found for the specified route."
        
        if dep_iata and arr_iata:
             route_text = f"Flights from {dep_iata or 'Unknown'} to {arr_iata or 'Unknown'}:\n"
        elif dep_iata:
            route_text = f"Flights departing from {dep_iata or 'Unknown'}:\n"
        elif arr_iata:
            route_text = f"Flights arriving at {arr_iata or 'Unknown'}:\n"
            
        return f"o flights found {route_text}\n\n Note:Aviationstack API provides live/ status of flights, but it may not provide data for all routes. for actual flight schedules, please check with the airlines or official sources."        
    
    
    route_info = "GLobal live flight data:\n"
    
    if dep_iata and arr_iata:
        route_info = f"Flights from {dep_iata or 'Unknown'} to {arr_iata or 'Unknown'}:\n"
    elif dep_iata:
        route_info = f"Flights departing from {dep_iata or 'Unknown'}:\n"
    elif arr_iata:
        route_info = f"Flights arriving at {arr_iata or 'Unknown'}:\n"
    
    formatted_flights = [formate_flight_info(flight) for flight in flight_data[:limit]]
    return f"{route_info}\n" + "\n\n".join(formatted_flights)
            
if __name__ == "__main__":
    query = input("plan a complete 7 days trip from india to bangladesh, including flights, hotels and sight seeing under 2 lakhs")
    # query = input("7 days plan from india to japan:")
    # query = input("Plan a 7 days Japan trip from Bangladesh:")
    # query = input("Enter your flight query (e.g., 'from India to Japan'): ")
    response = search_flights(query)
    print(response)
    # print(f"Searching for flights based on your query: '{query}'")
    print("\n" + "=" * 80 + "\n")
    print(search_flights("All country flights info"))
    
        

