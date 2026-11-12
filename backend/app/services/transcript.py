
from youtube_transcript_api import YouTubeTranscriptApi


def extract_transcript(video_id: str):
    """
    Extract YouTube transcript while preserving timestamps.

    Returns a list of dictionaries containing:
    - text
    - start
    - duration
    """

    api = YouTubeTranscriptApi()

    try:
        transcript = api.fetch(
            video_id,
            languages=["en", "hi"]
        )

    except Exception as error:
        raise ValueError(
            f"Unable to extract transcript for video {video_id}: {error}"
        )

    transcript_segments = []

    for snippet in transcript.snippets:
        text = snippet.text.strip()

        if not text:
            continue

        transcript_segments.append({
            "text": text,
            "start": float(snippet.start),
            "duration": float(snippet.duration)
        })

    if not transcript_segments:
        raise ValueError("Transcript is empty.")

    print("\n========== TRANSCRIPT EXTRACTION ==========")
    print("Video ID:", video_id)
    print("Total transcript segments:", len(transcript_segments))
    print("First segment:", transcript_segments[0])
    print("===========================================\n")

    return transcript_segments
