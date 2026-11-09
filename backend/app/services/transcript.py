
from youtube_transcript_api import YouTubeTranscriptApi


def extract_transcript(video_id: str) -> str:
    """
    Extracts the English transcript of a YouTube video.
    """

    api = YouTubeTranscriptApi()

    transcript = api.fetch(
        video_id,
        languages=["en"]
    )

    transcript_text = " ".join(
        snippet.text
        for snippet in transcript.snippets
    )

    if not transcript_text.strip():
        raise ValueError("Transcript is empty.")

    return transcript_text
