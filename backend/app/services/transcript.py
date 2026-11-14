
from youtube_transcript_api import YouTubeTranscriptApi


def extract_transcript(video_id: str):
    if not video_id or video_id.strip() in ("", "string"):
        raise ValueError(
            "Invalid YouTube video ID. Please provide an actual video ID."
        )

    video_id = video_id.strip()

    print("\n========== TRANSCRIPT EXTRACTION ==========")
    print("Video ID:", video_id)

    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(
            video_id,
            languages=["en", "hi"]
        )

    except Exception as error:
        error_message = str(error)

        print("Transcript extraction failed:", error_message)

        raise ValueError(
            f"Unable to extract transcript for video {video_id}.\n"
            f"Possible causes include YouTube blocking requests, "
            f"captions being unavailable, or an invalid video ID.\n"
            f"Original error: {error_message}"
        ) from error

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

    print("Total transcript segments:", len(transcript_segments))
    print("First segment:", transcript_segments[0])
    print("===========================================\n")

    return transcript_segments
