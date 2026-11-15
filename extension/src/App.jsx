
import {
  useState,
  useEffect,
  useRef,
  useCallback
} from "react";

import "./App.css";

const API_BASE_URL = "https://vidmind-api.onrender.com";

// Convert MM:SS or HH:MM:SS into seconds.
function timestampToSeconds(timestamp) {
  const parts = timestamp.split(":").map(Number);

  if (parts.some((part) => !Number.isFinite(part))) {
    return null;
  }

  if (parts.length === 2) {
    return parts[0] * 60 + parts[1];
  }

  if (parts.length === 3) {
    return (
      parts[0] * 3600 +
      parts[1] * 60 +
      parts[2]
    );
  }

  return null;
}

// Render timestamps as clickable buttons.
function renderMessageContent(content, onTimestampClick) {
  const timestampRegex = /\b(?:\d{1,2}:)?\d{1,2}:\d{2}\b/g;

  const parts = [];
  let lastIndex = 0;
  let match;
  let key = 0;

  while ((match = timestampRegex.exec(content)) !== null) {
    const timestamp = match[0];

    if (match.index > lastIndex) {
      parts.push(
        <span key={key++}>
          {content.slice(lastIndex, match.index)}
        </span>
      );
    }

    const seconds = timestampToSeconds(timestamp);

    if (seconds !== null) {
      parts.push(
        <button
          key={key++}
          type="button"
          className="timestamp-button"
          onClick={() => onTimestampClick(seconds)}
          title={`Jump to ${timestamp}`}
        >
          {timestamp}
        </button>
      );
    }

    lastIndex = timestampRegex.lastIndex;
  }

  if (lastIndex < content.length) {
    parts.push(
      <span key={key++}>
        {content.slice(lastIndex)}
      </span>
    );
  }

  return parts;
}

function App() {
  // ----------------------------------------------
  // VIDEO STATE
  // ----------------------------------------------

  const [video, setVideo] = useState(null);

  const [processingStatus, setProcessingStatus] = useState("idle");
  const [processingError, setProcessingError] = useState("");

  // ----------------------------------------------
  // CONVERSATION STATE
  // ----------------------------------------------

  // Each video gets its own conversation.
  const [conversations, setConversations] = useState({});

  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);

  // Get messages for the currently active video.
  const messages = video
    ? conversations[video.videoId] || []
    : [];

  const lastRequestedVideoId = useRef(null);
  const activeVideoId = useRef(null);

  // Stores the currently running stream controller.
  const streamControllerRef = useRef(null);

  // ----------------------------------------------
  // PROCESS VIDEO
  // ----------------------------------------------

  const processVideo = useCallback(async (videoInfo) => {
    if (!videoInfo?.videoId) return;

    const videoId = videoInfo.videoId;

    if (lastRequestedVideoId.current === videoId) {
      return;
    }

    lastRequestedVideoId.current = videoId;
    activeVideoId.current = videoId;

    setVideo(videoInfo);
    setQuestion("");
    setProcessingError("");
    setProcessingStatus("processing");

    try {
      const response = await fetch(
        `${API_BASE_URL}/process-video`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            video_id: videoId,
            title: videoInfo.title || "",
            channel_name: videoInfo.channelName || ""
          })
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Video processing failed."
        );
      }

      if (activeVideoId.current !== videoId) return;

      setProcessingStatus("ready");

      console.log("VidMind video processed:", data);

      console.log("Video metadata sent:", {
        videoId,
        title: videoInfo.title,
        channelName: videoInfo.channelName
      });

    } catch (error) {
      if (activeVideoId.current !== videoId) return;

      console.error("Processing error:", error);

      lastRequestedVideoId.current = null;

      setProcessingStatus("error");
      setProcessingError(error.message);
    }
  }, []);

  // ----------------------------------------------
  // HANDLE VIDEO CHANGES
  // ----------------------------------------------

  const handleVideoUpdate = useCallback((videoInfo) => {
    if (!videoInfo) {
      streamControllerRef.current?.abort();
      streamControllerRef.current = null;

      setVideo(null);
      setProcessingStatus("idle");
      setProcessingError("");
      setAsking(false);

      activeVideoId.current = null;
      lastRequestedVideoId.current = null;

      return;
    }

    setVideo(videoInfo);

    if (activeVideoId.current !== videoInfo.videoId) {
      // Abort the previous video's active stream.
      streamControllerRef.current?.abort();
      streamControllerRef.current = null;

      activeVideoId.current = videoInfo.videoId;
      lastRequestedVideoId.current = null;

      setAsking(false);
      setQuestion("");
      setProcessingError("");
      setProcessingStatus("idle");

      // Preserve previous conversations.
      processVideo(videoInfo);
    }
  }, [processVideo]);

  // ----------------------------------------------
  // DETECT CURRENT YOUTUBE VIDEO
  // ----------------------------------------------

  useEffect(() => {
    const chromeApi = globalThis.chrome;

    if (!chromeApi?.runtime?.onMessage) {
      setProcessingError(
        "Please open VidMind through the Chrome extension."
      );

      return;
    }

    const handleMessage = (message) => {
      if (message.type === "YOUTUBE_VIDEO_CHANGED") {
        handleVideoUpdate(message.payload);
      }
    };

    chromeApi.runtime.onMessage.addListener(handleMessage);

    async function detectCurrentVideo() {
      try {
        const [tab] = await chromeApi.tabs.query({
          active: true,
          currentWindow: true
        });

        if (
          !tab?.id ||
          !tab.url?.startsWith("https://www.youtube.com/")
        ) {
          handleVideoUpdate(null);
          return;
        }

        const response = await chromeApi.tabs.sendMessage(
          tab.id,
          {
            type: "GET_VIDEO_INFO"
          }
        );

        const videoInfo = response?.videoInfo ?? response;

        if (!videoInfo?.videoId) {
          throw new Error("Video information was not returned.");
        }

        handleVideoUpdate(videoInfo);

      } catch (error) {
        console.error("Video detection failed:", error);

        setVideo(null);
        setProcessingStatus("error");

        setProcessingError(
          "Unable to detect the video. Refresh the YouTube page and reopen VidMind."
        );
      }
    }

    detectCurrentVideo();

    return () => {
      chromeApi.runtime.onMessage.removeListener(handleMessage);
      streamControllerRef.current?.abort();
    };
  }, [handleVideoUpdate]);

  // ----------------------------------------------
  // RETRY VIDEO PROCESSING
  // ----------------------------------------------

  const retryProcessing = () => {
    if (!video) return;

    lastRequestedVideoId.current = null;

    processVideo(video);
  };

  // ----------------------------------------------
  // FIND YOUTUBE TAB
  // ----------------------------------------------

  const findYouTubeTab = async (videoId) => {
    if (!videoId) {
      console.error("VidMind: Video ID is missing.");
      return null;
    }

    const chromeApi = globalThis.chrome;

    const tabs = await chromeApi.tabs.query({});

    const youtubeTabs = tabs.filter((tab) => {
      if (!tab.url) return false;

      try {
        const url = new URL(tab.url);

        return (
          url.hostname === "youtube.com" ||
          url.hostname.endsWith(".youtube.com")
        );

      } catch {
        return false;
      }
    });

    const matchingTab = youtubeTabs.find((tab) => {
      const url = new URL(tab.url);

      let currentVideoId = null;

      if (url.pathname === "/watch") {
        currentVideoId = url.searchParams.get("v");
      } else if (url.pathname.startsWith("/shorts/")) {
        currentVideoId = url.pathname.split("/")[2];
      }

      return currentVideoId === videoId;
    });

    if (matchingTab) {
      console.log(
        "VidMind: Matching YouTube tab found:",
        matchingTab.url
      );

      return matchingTab;
    }

    console.error("VidMind: No matching YouTube tab found.", {
      requestedVideoId: videoId,
      availableTabs: youtubeTabs.map((tab) => tab.url)
    });

    return null;
  };

  // ----------------------------------------------
  // TIMESTAMP NAVIGATION
  // ----------------------------------------------

  const handleTimestampClick = async (seconds) => {
    console.log("VidMind timestamp clicked:", seconds);

    try {
      const chromeApi = globalThis.chrome;

      const videoId = activeVideoId.current;

      const youtubeTab = await findYouTubeTab(videoId);

      if (!youtubeTab?.id) {
        console.error("Matching YouTube tab not found.");
        return;
      }

      // First attempt: seek using content script.
      try {
        const result = await chromeApi.tabs.sendMessage(
          youtubeTab.id,
          {
            type: "SEEK_TO_TIMESTAMP",
            seconds
          }
        );

        console.log("Timestamp seek result:", result);

        if (result?.success === true) {
          console.log("Timestamp navigation successful.");
          return;
        }

        console.warn(
          "Content script did not confirm seek. Using URL fallback."
        );

      } catch (messageError) {
        console.warn(
          "Content script communication failed:",
          messageError
        );
      }

      // Fallback: navigate to the same video at the requested time.
      const url = new URL(youtubeTab.url);

      if (
        url.pathname === "/watch" ||
        url.pathname.startsWith("/shorts/")
      ) {
        url.searchParams.set(
          "t",
          `${Math.floor(seconds)}s`
        );
      }

      await chromeApi.tabs.update(youtubeTab.id, {
        url: url.toString()
      });

      console.log("VidMind URL fallback:", url.toString());

    } catch (error) {
      console.error("Timestamp navigation failed:", error);
    }
  };

  // ----------------------------------------------
  // SEND QUESTION USING SSE STREAMING
  // ----------------------------------------------

  const handleSubmit = async (event) => {
    event.preventDefault();

    const userQuestion = question.trim();

    if (
      !userQuestion ||
      !video ||
      processingStatus !== "ready" ||
      asking
    ) {
      return;
    }

    const requestedVideoId = video.videoId;

    // Capture previous messages BEFORE adding the new question.
    const previousMessages = conversations[requestedVideoId] || [];

    // Send only the latest 10 previous messages.
    const chatHistory = previousMessages.slice(-10).map(
      (message) => ({
        role: message.role,
        content: message.content
      })
    );

    // Unique ID for the assistant's streaming message.
    const assistantMessageId =
      `assistant-${Date.now()}-${Math.random()}`;

    // Create a controller for this request.
    const controller = new AbortController();

    streamControllerRef.current = controller;

    // Add user question and empty assistant message.
    setConversations((previous) => ({
      ...previous,
      [requestedVideoId]: [
        ...(previous[requestedVideoId] || []),
        {
          role: "user",
          content: userQuestion
        },
        {
          id: assistantMessageId,
          role: "assistant",
          content: ""
        }
      ]
    }));

    setQuestion("");
    setAsking(true);

    let streamedAnswer = "";

    try {
      const response = await fetch(
        `${API_BASE_URL}/ask/stream`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "text/event-stream"
          },
          body: JSON.stringify({
            video_id: requestedVideoId,
            question: userQuestion,
            chat_history: chatHistory
          }),
          signal: controller.signal
        }
      );

      if (!response.ok) {
        let errorMessage = "Unable to generate an answer.";

        try {
          const errorData = await response.json();
          errorMessage = errorData.detail || errorMessage;
        } catch {
          // Keep the default error message.
        }

        throw new Error(errorMessage);
      }

      if (!response.body) {
        throw new Error("Streaming response is not supported.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      let buffer = "";
      let streamCompleted = false;

      // Update only this video's assistant message.
      const updateAssistantMessage = (content) => {
        if (activeVideoId.current !== requestedVideoId) {
          return;
        }

        setConversations((previous) => ({
          ...previous,
          [requestedVideoId]: (
            previous[requestedVideoId] || []
          ).map((message) =>
            message.id === assistantMessageId
              ? { ...message, content }
              : message
          )
        }));
      };

      // Process one complete SSE event.
      const processEvent = (eventText) => {
        const dataLines = eventText
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim());

        if (dataLines.length === 0) return false;

        const data = dataLines.join("\n");

        if (data === "[DONE]") {
          streamCompleted = true;
          return true;
        }

        let payload;

        try {
          payload = JSON.parse(data);
        } catch {
          console.warn("Invalid streaming event:", data);
          return false;
        }

        if (payload.error) {
          throw new Error(payload.error);
        }

        if (typeof payload.token === "string") {
          streamedAnswer += payload.token;
          updateAssistantMessage(streamedAnswer);
        }

        return false;
      };

      // Read the response as it arrives.
      while (!streamCompleted) {
        const { value, done } = await reader.read();

        if (done) {
          buffer += decoder.decode();
          break;
        }

        buffer += decoder.decode(value, {
          stream: true
        });

        // SSE events are separated by a blank line.
        const events = buffer.split(/\r?\n\r?\n/);

        buffer = events.pop() || "";

        for (const eventText of events) {
          processEvent(eventText);

          if (streamCompleted) break;
        }
      }

      // Process any remaining event in the buffer.
      if (!streamCompleted && buffer.trim()) {
        processEvent(buffer);
      }

      if (!streamedAnswer.trim()) {
        throw new Error(
          "The server returned an empty response."
        );
      }

      console.log("VidMind streaming response completed.");

    } catch (error) {
      if (error.name === "AbortError") {
        console.log("VidMind stream aborted.");
        return;
      }

      console.error("Streaming question error:", error);

      if (activeVideoId.current !== requestedVideoId) {
        return;
      }

      const errorContent = streamedAnswer
        ? `${streamedAnswer}\n\n(Response interrupted: ${error.message})`
        : `Sorry, something went wrong: ${error.message}`;

      setConversations((previous) => ({
        ...previous,
        [requestedVideoId]: (
          previous[requestedVideoId] || []
        ).map((message) =>
          message.id === assistantMessageId
            ? { ...message, content: errorContent }
            : message
        )
      }));

    } finally {
      // Do not let an older request reset a newer request's state.
      if (streamControllerRef.current === controller) {
        streamControllerRef.current = null;

        if (activeVideoId.current === requestedVideoId) {
          setAsking(false);
        }
      }
    }
  };

  // ----------------------------------------------
  // CLEAR CURRENT VIDEO CONVERSATION
  // ----------------------------------------------

  const clearConversation = () => {
    if (!video) return;

    streamControllerRef.current?.abort();
    streamControllerRef.current = null;

    setAsking(false);

    setConversations((previous) => ({
      ...previous,
      [video.videoId]: []
    }));

    console.log(
      "VidMind conversation cleared:",
      video.videoId
    );
  };

  // ----------------------------------------------
  // UI
  // ----------------------------------------------

  return (
    <div className="app">

      {/* Header */}
      <header className="header">

        <div className="logo">V</div>

        <div className="brand">
          <h2>VidMind</h2>
          <p>Your AI video assistant</p>
        </div>

        <div className="header-badge">AI</div>

      </header>

      {/* Video information */}
      <section className="video-section">

        {video ? (
          <>

            <div className="video-title">
              {video.title}
            </div>

            <div className="video-metadata">

              {video.channelName && (
                <span>{video.channelName}</span>
              )}

              {video.durationFormatted && (
                <span>
                  Duration: {video.durationFormatted}
                </span>
              )}

              {video.viewCount && (
                <span>{video.viewCount}</span>
              )}

            </div>

            <div className={`status ${processingStatus}`}>

              <span className="status-dot"></span>

              {processingStatus === "processing" &&
                "Understanding video..."}

              {processingStatus === "ready" &&
                "Video ready for questions"}

              {processingStatus === "error" &&
                "Processing failed"}

            </div>

            {processingStatus === "error" && (

              <div className="error-message">

                <p>{processingError}</p>

                <button onClick={retryProcessing}>
                  Retry processing
                </button>

              </div>

            )}

            {processingStatus === "processing" && (

              <p className="processing-text">
                Extracting transcript and generating embeddings...
              </p>

            )}

          </>

        ) : (

          <div className="empty-video">

            <h3>No video detected</h3>

            <p>Open a YouTube video to start chatting.</p>

          </div>

        )}

      </section>

      {/* Chat area */}
      <main className="chat-area">

        {messages.length === 0 && (

          <div className="welcome">

            <div className="welcome-icon">✦</div>

            <h3>Ask anything about this video</h3>

            <p>
              I can summarize the video, explain concepts,
              and answer questions using its transcript.
              Click timestamps to jump to relevant moments.
              I can also understand follow-up questions.
            </p>

            {processingStatus === "ready" && (

              <button
                type="button"
                className="suggestion"
                onClick={() =>
                  setQuestion("Can you summarize this video?")
                }
              >
                Try asking: "Can you summarize this video?"
              </button>

            )}

          </div>

        )}

        {messages.map((message, index) => (

          <div
            key={message.id || index}
            className={`message ${message.role}`}
          >

            <div className="message-label">
              {message.role === "user" ? "You" : "VidMind"}
            </div>

            <div className="message-content">

              {message.role === "assistant"
                ? renderMessageContent(
                    message.content,
                    handleTimestampClick
                  )
                : message.content}

              {/* Blinking cursor while this answer streams. */}
              {asking &&
                message.id &&
                message.id === messages[messages.length - 1]?.id && (
                  <span className="streaming-cursor"></span>
                )}

            </div>

          </div>

        ))}

        {/* Show thinking only before the first token arrives. */}
        {asking &&
          !messages.some(
            (message) =>
              message.role === "assistant" &&
              message.id &&
              message.content.length > 0
          ) && (

            <div className="message assistant">

              <div className="message-label">
                VidMind
              </div>

              <div className="message-content typing">
                Thinking...
              </div>

            </div>

          )}

      </main>

      {/* Question input */}
      <form
        className="chat-input"
        onSubmit={handleSubmit}
      >

        <input
          type="text"
          placeholder={
            processingStatus === "ready"
              ? "Ask a question about this video..."
              : "Waiting for video processing..."
          }
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={
            processingStatus !== "ready" || asking
          }
        />

        <button
          type="submit"
          disabled={
            !question.trim() ||
            processingStatus !== "ready" ||
            asking
          }
        >
          ↑
        </button>

      </form>

      {/* Clear conversation */}
      {messages.length > 0 && (

        <div className="conversation-actions">

          <button
            type="button"
            onClick={clearConversation}
            disabled={asking}
          >
            Clear conversation
          </button>

        </div>

      )}

      <footer className="footer">
        VidMind AI · Answers based on video transcripts
      </footer>

    </div>
  );
}

export default App;
