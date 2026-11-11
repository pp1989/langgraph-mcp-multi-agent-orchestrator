from pathlib import Path
from fastapi import FastAPI, Request, APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
import uvicorn
import nest_asyncio
# import loguru
import json
import logging 
from langchain_core.messages import AIMessage
from backend import run_travel_agent, resume_travel_agent, get_saved_travel_data, get_saved_travel_data
from download import build_travel_pdf


# Apply the patch to allow nested event loops
nest_asyncio.apply()

BASE_DIR = Path(__file__).resolve().parent
print(f"BASE_DIR: {BASE_DIR}")

app = FastAPI(
    title="TripMate AI",
    description="langgraph Multi-agent Travel Planner with FastAPI Frontend",
    version="1.0.0",
)


@app.on_event("startup")
async def startup_event():
    logger = logging.getLogger("mylogger")
    logger.info("I expect this to log")
    # loguru.logger.info("but only this logs")


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "template"))

class TravelRequest(BaseModel):
    message: str
    thread_id: str | None = None


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/api/travel")
async def travel_planer(request_data: TravelRequest):

#################### Dummy section #######################

    # with open("data.json", "r", encoding="utf-8") as file:
    #    data = json.load(file)

    # # Now 'data' holds all your JSON data, and you can use it!
    # print(f"""{data}""")
    # return data
##########################################################



    print(f"Received request test: {request_data}")
    try:
        user_message = request_data.message.strip()

        if not user_message:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "message cant't be empaty!"},
            )
            
        # result = get_mock_travel_response()
        result = run_travel_agent(
            user_input=user_message,
            thread_id="test_id"
            # thread_id=request_data.thread_id
        )
        
        if not isinstance(result, dict):
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": "Unexpected travel agent response"
                    }
                )

            # Extract answer
        answer = result.get("answer", "")
        if isinstance(answer, AIMessage):
                answer = answer.content

        # Prepare frontend response
        response_data = {
                "success": True,
                "thread_id": result.get("thread_id"),
                "answer": answer,
                "requires_approval":result.get("requires_approval"),
                "flight_results": result.get("flight_results", []),
                "hotel_results": result.get("hotel_results", []),
                "weather_results": result.get("weather_results", []),
                "itinerary": result.get("itinerary", []),
                "llm_calls": result.get("llm_calls", 0)
            }
        print("Response data to frontend:------------------------>", response_data)
        return JSONResponse(content=response_data)
    except Exception as e:
        print(f"Error: {e}")
        # flight_data = "Error fetching flight data."
        # traceback.print_exc()


@app.get("/health")
async def health_check():
    return {"status": "OK", "message": "AI Travel Planer API is running"}


@app.get("/favicon.ico")
async def favicon():
    return JSONResponse(content={})



"""Add this route to your existing FastAPI app; do not register a duplicate route."""




class ApprovalRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    approved: bool
    feedback: str = Field(default="", max_length=2000)


@app.post("/api/travel/approve")
def approve_travel(request: ApprovalRequest):
    try:
        return resume_travel_agent(
            thread_id=request.thread_id,
            approved=request.approved,
            feedback=request.feedback.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Log the exception in production; do not expose credentials or internals.
        raise HTTPException(
            status_code=500,
            detail="Unable to resume this travel-planning workflow.",
        ) from exc


class DownloadRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    
@app.post("/api/travel/download/pdf")
def download_travel_pdf(request: DownloadRequest):

    travel_data = get_saved_travel_data(request.thread_id)

    # This calls the function defined in download.py
    pdf_buffer = build_travel_pdf(travel_data)

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
            'attachment; filename="tripmate-travel-report.pdf"'
        }
    )

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True, log_level="info")
