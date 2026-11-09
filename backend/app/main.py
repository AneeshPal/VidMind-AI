
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Load environment variables from backend/.env
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

from app.services.rag import process_video, ask_question


app = FastAPI(
    title="VidMind API",
    description="AI-powered YouTube Video Assistant",
    version="1.0.0"
)


# Allow requests from the local React app and
# the Chrome extension during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request models
class ProcessVideoRequest(BaseModel):
    video_id: str


class AskRequest(BaseModel):
    video_id: str
    question: str


@app.get("/")
def home():
    return {
        "message": "Welcome to VidMind API!",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


# Process YouTube video
@app.post("/process-video")
def process_video_endpoint(request: ProcessVideoRequest):

    try:
        result = process_video(request.video_id)

        return {
            "message": "Video processing completed",
            "video_id": request.video_id,
            **result
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# Ask questions about a video
@app.post("/ask")
def ask_endpoint(request: AskRequest):

    if not request.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )

    try:
        answer = ask_question(
            request.video_id,
            request.question
        )

        return {
            "video_id": request.video_id,
            "question": request.question,
            "answer": answer
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )
