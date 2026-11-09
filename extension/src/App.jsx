
import { useEffect, useState } from "react";
import "./App.css";

function App() {
  const [video, setVideo] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Listen for video changes from content scripts
    const handleMessage = (message) => {
      if (message.type === "YOUTUBE_VIDEO_CHANGED") {
        setVideo(message.payload);
        setLoading(false);
      }
    };

    chrome.runtime.onMessage.addListener(handleMessage);

    // Get information about the currently active tab
    async function detectCurrentVideo() {
      try {
        const [tab] = await chrome.tabs.query({
          active: true,
          currentWindow: true
        });

        if (!tab?.id || !tab.url?.startsWith("https://www.youtube.com/")) {
          setVideo(null);
          setLoading(false);
          return;
        }

        const response = await chrome.tabs.sendMessage(
          tab.id,
          { type: "GET_VIDEO_INFO" }
        );

        setVideo(response);
      } catch (error) {
        console.log("Video detection error:", error);
        setVideo(null);
      } finally {
        setLoading(false);
      }
    }

    detectCurrentVideo();

    return () => {
      chrome.runtime.onMessage.removeListener(handleMessage);
    };
  }, []);

  return (
    <div className="app">
      <header className="header">
        <div className="logo">V</div>

        <div>
          <h2>VidMind</h2>
          <p>Your AI video assistant</p>
        </div>
      </header>

      <main className="content">
        <h1>Understand every video.</h1>

        {loading ? (
          <p>Detecting video...</p>
        ) : video ? (
          <div className="video-card">
            <div className="status">
              <span className="status-dot"></span>
              Video detected
            </div>

            <h3>{video.title}</h3>

            <p className="video-id">
              Video ID: {video.videoId}
            </p>

            <a
              href={video.url}
              target="_blank"
              rel="noreferrer"
            >
              Open video
            </a>
          </div>
        ) : (
          <div className="empty-state">
            <p>No YouTube video detected.</p>
            <span>
              Open a YouTube video to get started.
            </span>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
