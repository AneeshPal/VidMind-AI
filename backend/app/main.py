
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Load environment variables from backend/.env
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

from app.services.rag import process_video, ask_question


app = FastAPI(
    title="VidMind API",
    description="AI-powered YouTube Video Assistant",
    version="1.0.0"
)


# --------------------------------------------------
# CORS CONFIGURATION
# --------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# REQUEST MODELS
# --------------------------------------------------

class ProcessVideoRequest(BaseModel):
    video_id: str
    title: str | None = None
    channel_name: str | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    video_id: str
    question: str
    chat_history: list[ChatMessage] = Field(default_factory=list)


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "Welcome to VidMind API!",
        "status": "running"
    }


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


# --------------------------------------------------
# PROCESS YOUTUBE VIDEO
# --------------------------------------------------

@app.post("/process-video")
def process_video_endpoint(request: ProcessVideoRequest):

    if not request.video_id.strip():
        raise HTTPException(
            status_code=400,
            detail="Video ID cannot be empty."
        )

    try:
        result = process_video(
            video_id=request.video_id,
            title=request.title,
            channel_name=request.channel_name
        )

        return {
            "message": "Video processing completed",
            **result
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except Exception as error:
        print("Video processing error:", error)

        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing the video."
        )


# --------------------------------------------------
# ASK QUESTIONS ABOUT A VIDEO
# --------------------------------------------------

@app.post("/ask")
def ask_endpoint(request: AskRequest):

    if not request.video_id.strip():
        raise HTTPException(
            status_code=400,
            detail="Video ID cannot be empty."
        )

    if not request.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )

    # Validate message roles and remove empty messages.
    chat_history = []

    for message in request.chat_history[-10:]:
        if message.role not in ("user", "assistant"):
            raise HTTPException(
                status_code=400,
                detail="Invalid chat history role."
            )

        if message.content.strip():
            chat_history.append({
                "role": message.role,
                "content": message.content.strip()
            })

    try:
        answer = ask_question(
            video_id=request.video_id,
            question=request.question,
            chat_history=chat_history
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
        print("Question answering error:", error)

        raise HTTPException(
            status_code=500,
            detail="An error occurred while answering the question."
        )
