
import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
FAISS_DIR = BACKEND_DIR / "data" / "faiss"


def get_video_cache_path(video_id: str) -> Path:
    return FAISS_DIR / video_id


def save_video_metadata(video_id: str, metadata: dict):
    cache_path = get_video_cache_path(video_id)
    cache_path.mkdir(parents=True, exist_ok=True)

    metadata_path = cache_path / "metadata.json"

    with open(metadata_path, "w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=4)


def load_video_metadata(video_id: str):
    metadata_path = get_video_cache_path(video_id) / "metadata.json"

    if not metadata_path.exists():
        return {}

    with open(metadata_path, "r", encoding="utf-8") as file:
        return json.load(file)


def cache_exists(video_id: str) -> bool:
    cache_path = get_video_cache_path(video_id)

    return (
        (cache_path / "index.faiss").exists()
        and (cache_path / "index.pkl").exists()
        and (cache_path / "metadata.json").exists()
    )
