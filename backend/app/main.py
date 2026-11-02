
from fastapi import FastAPI

app = FastAPI(
    title="VidMind API",
    description="AI-powered YouTube Video Assistant",
    version="1.0.0"
)


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
