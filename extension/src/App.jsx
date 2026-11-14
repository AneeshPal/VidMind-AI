
import {
  useState,
  useEffect,
  useRef,
  useCallback,
  isValidElement,
  cloneElement
} from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

import "highlight.js/styles/github-dark.css";
import "./App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

const SUGGESTED_QUESTIONS = [
  "Summarize this video",
  "What are the key takeaways?",
  "Explain the main topic",
  "Who are the people in this video?"
];


// --------------------------------------------------
// TIMESTAMP HELPERS
// --------------------------------------------------

function timestampToSeconds(timestamp) {
  const parts = timestamp.split(":").map(Number);

  if (parts.some((part) => !Number.isFinite(part))) {
    return null;
  }

  if (parts.length === 2) {
    return parts[0] * 60 + parts[1];
  }

  if (parts.length === 3) {
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  }

  return null;
}


function renderTimestampNodes(nodes, onTimestampClick) {
  return nodes.map((node, index) => {
    if (typeof node === "string") {
      const regex = /\b(?:\d{1,2}:)?\d{1,2}:\d{2}\b/g;
      const parts = [];
      let lastIndex = 0;
      let match;

      while ((match = regex.exec(node)) !== null) {
        if (match.index > lastIndex) {
          parts.push(node.slice(lastIndex, match.index));
        }

        const timestamp = match[0];
        const seconds = timestampToSeconds(timestamp);

        if (seconds !== null) {
          parts.push(
            <button
              key={`${index}-${match.index}`}
              type="button"
              className="timestamp-button"
              onClick={() => onTimestampClick(seconds)}
              title={`Jump to ${timestamp}`}
            >
              {timestamp}
            </button>
          );
        }

        lastIndex = regex.lastIndex;
      }

      if (lastIndex < node.length) {
        parts.push(node.slice(lastIndex));
      }

      return <span key={index}>{parts}</span>;
    }

    if (isValidElement(node) && node.props.children) {
      return cloneElement(
        node,
        {},
        renderTimestampNodes(
          Array.isArray(node.props.children)
            ? node.props.children
            : [node.props.children],
          onTimestampClick
        )
      );
    }

    return node;
  });
}


// --------------------------------------------------
// MARKDOWN MESSAGE
// --------------------------------------------------

function MarkdownMessage({ content, onTimestampClick }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        p: ({ children, ...props }) => (
          <p {...props}>
            {renderTimestampNodes(
              Array.isArray(children) ? children : [children],
              onTimestampClick
            )}
          </p>
        ),

        li: ({ children, ...props }) => (
          <li {...props}>
            {renderTimestampNodes(
              Array.isArray(children) ? children : [children],
              onTimestampClick
            )}
          </li>
        ),

        a: ({ children, href, ...props }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            {...props}
          >
            {children}
          </a>
        )
      }}
    >
      {content || ""}
    </ReactMarkdown>
  );
}


// --------------------------------------------------
// MAIN APP
// --------------------------------------------------

function App() {
  const [video, setVideo] = useState(null);

  const [processingStatus, setProcessingStatus] = useState("idle");
  const [processingError, setProcessingError] = useState("");

  // Separate conversation for each video.
  const [conversations, setConversations] = useState({});

  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);

  const lastRequestedVideoId = useRef(null);
  const activeVideoId = useRef(null);
  const chatEndRef = useRef(null);

  const messages = video
    ? conversations[video.videoId] || []
    : [];


  // --------------------------------------------------
  // AUTO SCROLL
  // --------------------------------------------------

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end"
    });
  }, [messages, asking]);


  // --------------------------------------------------
  // PROCESS VIDEO
  // --------------------------------------------------

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

    } catch (error) {
      if (activeVideoId.current !== videoId) return;

      console.error("Processing error:", error);

      lastRequestedVideoId.current = null;
      setProcessingStatus("error");
      setProcessingError(error.message);
    }
  }, []);


  // --------------------------------------------------
  // HANDLE VIDEO CHANGES
  // --------------------------------------------------

  const handleVideoUpdate = useCallback((videoInfo) => {
    if (!videoInfo) {
      setVideo(null);
      setProcessingStatus("idle");
      setProcessingError("");

      activeVideoId.current = null;
      lastRequestedVideoId.current = null;

      return;
    }

    setVideo(videoInfo);

    if (activeVideoId.current !== videoInfo.videoId) {
      activeVideoId.current = videoInfo.videoId;
      lastRequestedVideoId.current = null;

      setQuestion("");
      setProcessingError("");
      setProcessingStatus("idle");

      // Keep previous video conversations in state.
      processVideo(videoInfo);
    }
  }, [processVideo]);


  // --------------------------------------------------
  // DETECT CURRENT YOUTUBE VIDEO
  // --------------------------------------------------

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
          { type: "GET_VIDEO_INFO" }
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
          "Unable to detect the video. Refresh YouTube and reopen VidMind."
        );
      }
    }

    detectCurrentVideo();

    return () => {
      chromeApi.runtime.onMessage.removeListener(handleMessage);
    };
  }, [handleVideoUpdate]);


  // --------------------------------------------------
  // RETRY VIDEO PROCESSING
  // --------------------------------------------------

  const retryProcessing = () => {
    if (!video) return;

    lastRequestedVideoId.current = null;
    processVideo(video);
  };


  // --------------------------------------------------
  // FIND MATCHING YOUTUBE TAB
  // --------------------------------------------------

  const findYouTubeTab = async (videoId) => {
    if (!videoId) return null;

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

    return youtubeTabs.find((tab) => {
      const url = new URL(tab.url);
      let currentVideoId = null;

      if (url.pathname === "/watch") {
        currentVideoId = url.searchParams.get("v");
      } else if (url.pathname.startsWith("/shorts/")) {
        currentVideoId = url.pathname.split("/")[2];
      }

      return currentVideoId === videoId;
    }) || null;
  };


  // --------------------------------------------------
  // TIMESTAMP NAVIGATION
  // --------------------------------------------------

  const handleTimestampClick = async (seconds) => {
    try {
      const chromeApi = globalThis.chrome;
      const videoId = activeVideoId.current;

      const youtubeTab = await findYouTubeTab(videoId);

      if (!youtubeTab?.id) {
        console.error("Matching YouTube tab not found.");
        return;
      }

      try {
        const result = await chromeApi.tabs.sendMessage(
          youtubeTab.id,
          {
            type: "SEEK_TO_TIMESTAMP",
            seconds
          }
        );

        if (result?.success === true) {
          return;
        }

      } catch (error) {
        console.warn("Content script seek failed:", error);
      }

      // URL fallback.
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

    } catch (error) {
      console.error("Timestamp navigation failed:", error);
    }
  };


  // --------------------------------------------------
  // ASK QUESTION
  // --------------------------------------------------

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

    // Capture history before adding the new question.
    const previousMessages =
      conversations[requestedVideoId] || [];

    const chatHistory = previousMessages.slice(-10).map(
      (message) => ({
        role: message.role,
        content: message.content
      })
    );

    setConversations((previous) => ({
      ...previous,
      [requestedVideoId]: [
        ...(previous[requestedVideoId] || []),
        {
          role: "user",
          content: userQuestion
        }
      ]
    }));

    setQuestion("");
    setAsking(true);

    try {
      const response = await fetch(
        `${API_BASE_URL}/ask`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            video_id: requestedVideoId,
            question: userQuestion,
            chat_history: chatHistory
          })
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Unable to generate an answer."
        );
      }

      if (activeVideoId.current !== requestedVideoId) {
        return;
      }

      setConversations((previous) => ({
        ...previous,
        [requestedVideoId]: [
          ...(previous[requestedVideoId] || []),
          {
            role: "assistant",
            content: data.answer
          }
        ]
      }));

    } catch (error) {
      console.error("Question error:", error);

      if (activeVideoId.current !== requestedVideoId) {
        return;
      }

      setConversations((previous) => ({
        ...previous,
        [requestedVideoId]: [
          ...(previous[requestedVideoId] || []),
          {
            role: "assistant",
            content: `Sorry, something went wrong: ${error.message}`
          }
        ]
      }));

    } finally {
      setAsking(false);
    }
  };


  // --------------------------------------------------
  // SUGGESTED QUESTIONS
  // --------------------------------------------------

  const askSuggestedQuestion = (suggestion) => {
    if (asking || processingStatus !== "ready") return;

    setQuestion(suggestion);
  };


  // --------------------------------------------------
  // CLEAR CONVERSATION
  // --------------------------------------------------

  const clearConversation = () => {
    if (!video || asking) return;

    setConversations((previous) => ({
      ...previous,
      [video.videoId]: []
    }));
  };


  // --------------------------------------------------
  // UI
  // --------------------------------------------------

  return (
    <div className="app">

      {/* HEADER */}
      <header className="header">
        <div className="logo">V</div>

        <div className="brand">
          <h2>VidMind</h2>
          <p>Your AI video assistant</p>
        </div>

        <div className="header-badge">
          <span className="online-dot"></span>
          AI POWERED
        </div>
      </header>


      {/* VIDEO INFORMATION */}
      <section className="video-section">

        {video ? (
          <>
            <div className="video-label">
              NOW WATCHING
            </div>

            <div className="video-title">
              {video.title || "YouTube video"}
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

            {processingStatus === "processing" && (
              <div className="processing-details">
                <span className="loading-bar"></span>
                Extracting transcript and preparing video context...
              </div>
            )}

            {processingStatus === "error" && (
              <div className="error-message">
                <p>{processingError}</p>

                <button onClick={retryProcessing}>
                  Retry processing
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="empty-video">
            <div className="empty-video-icon">▶</div>
            <h3>No video detected</h3>
            <p>Open a YouTube video to start chatting.</p>
          </div>
        )}

      </section>


      {/* CHAT AREA */}
      <main className="chat-area">

        {messages.length === 0 && (
          <div className="welcome">
            <div className="welcome-icon">✦</div>

            <h3>What would you like to know?</h3>

            <p>
              Ask questions, explore key ideas, and get
              answers grounded in the video's transcript.
              Click timestamps to jump to those moments.
            </p>

            {processingStatus === "ready" && (
              <div className="suggestions">
                <div className="suggestions-heading">
                  TRY ASKING
                </div>

                {SUGGESTED_QUESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    className="suggestion"
                    onClick={() => askSuggestedQuestion(suggestion)}
                  >
                    <span>{suggestion}</span>
                    <span className="suggestion-arrow">↗</span>
                  </button>
                ))}
              </div>
            )}

            {processingStatus === "processing" && (
              <div className="welcome-loading">
                <span className="loader"></span>
                Preparing your video...
              </div>
            )}
          </div>
        )}


        {/* CHAT MESSAGES */}
        {messages.map((message, index) => (
          <div
            key={`${video?.videoId}-${index}`}
            className={`message ${message.role}`}
          >
            <div className="message-avatar">
              {message.role === "user" ? "Y" : "V"}
            </div>

            <div className="message-body">
              <div className="message-label">
                {message.role === "user" ? "You" : "VidMind"}
              </div>

              <div className="message-content">
                {message.role === "assistant" ? (
                  <MarkdownMessage
                    content={message.content}
                    onTimestampClick={handleTimestampClick}
                  />
                ) : (
                  message.content
                )}
              </div>
            </div>
          </div>
        ))}


        {/* THINKING ANIMATION */}
        {asking && (
          <div className="message assistant">
            <div className="message-avatar">V</div>

            <div className="message-body">
              <div className="message-label">VidMind</div>

              <div className="message-content thinking-content">
                <span className="thinking-text">Thinking</span>

                <span className="thinking-dots">
                  <i></i>
                  <i></i>
                  <i></i>
                </span>
              </div>
            </div>
          </div>
        )}

        <div ref={chatEndRef}></div>

      </main>


      {/* CLEAR CONVERSATION */}
      {messages.length > 0 && (
        <div className="conversation-actions">
          <button
            type="button"
            onClick={clearConversation}
            disabled={asking}
          >
            <span>↺</span> Clear conversation
          </button>
        </div>
      )}


      {/* CHAT INPUT */}
      <form
        className="chat-input"
        onSubmit={handleSubmit}
      >
        <input
          type="text"
          placeholder={
            processingStatus === "ready"
              ? "Ask anything about this video..."
              : "Waiting for video processing..."
          }
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={processingStatus !== "ready" || asking}
        />

        <button
          type="submit"
          disabled={
            !question.trim() ||
            processingStatus !== "ready" ||
            asking
          }
          title="Send message"
        >
          ↑
        </button>
      </form>


      {/* FOOTER */}
      <footer className="footer">
        <span>✦</span> VidMind AI · Powered by video context
      </footer>

    </div>
  );
}

export default App;
