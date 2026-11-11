from mcp.server.fastmcp import FastMCP
import requests
import os
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("###########weather MCP Server##########")

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")


@mcp.tool()
def get_current_weather(city: str) -> dict:
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric"
    response = requests.get(url)
    data = response.json()
    if response.status_code != 200:
        return {"error": "Could not fetch weather data."}
    else:
        return {
            "city": data["name"],
            "temperature": data["main"]["temp"],
            "feels_like_c": data["main"]["feels_like"],
            "description": data["weather"][0]["description"],
            "condition": data["weather"][0]["main"],
            "humidity": data["main"]["humidity"],
            "wind_speed": data["wind"]["speed"],
        }

@mcp.tool()
def get_forecast(city: str):
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={OPENWEATHER_API_KEY}&units=metric"
    response = requests.get(url)
    data = response.json()
    if response.status_code != 200:
        return {"error": "Could not fetch weather data."}
    else:
        forecast_list = []
        for item in data["list"][:5]:
            forecast_list.append(
                {
                    "datetime": item["dt_txt"],
                    "temperature": item["main"]["temp"],
                    "weather": item["weather"][0]["description"],
                    # "feels_like_c": item["main"]["feels_like"],
                    # "description": item["weather"][0]["description"],
                    # "condition": item["weather"][0]["main"],
                    # "humidity": item["main"]["humidity"],
                    # "wind_speed": item["wind"]["speed"],
                }
            )
        return {"city": data["city"]["name"], "forecast": forecast_list}


if __name__ == "__main__":
    mcp.run()