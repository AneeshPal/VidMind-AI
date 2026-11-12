
console.log("VidMind content script loaded!");

// Format duration into MM:SS or HH:MM:SS.
function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return null;
  }

  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainingSeconds = total % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(
      remainingSeconds
    ).padStart(2, "0")}`;
  }

  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

// Extract current YouTube video information.
function getVideoInfo() {
  const url = new URL(window.location.href);

  let videoId = null;

  if (url.pathname === "/watch") {
    videoId = url.searchParams.get("v");
  } else if (url.pathname.startsWith("/shorts/")) {
    videoId = url.pathname.split("/")[2];
  }

  if (!videoId) return null;

  const title =
    document.querySelector("h1 yt-formatted-string")
      ?.textContent?.trim() ||
    document.title.replace(" - YouTube", "").trim();

  const videoElement = document.querySelector("video");

  const durationSeconds =
    videoElement && Number.isFinite(videoElement.duration)
      ? Math.floor(videoElement.duration)
      : null;

  const channelName =
    document.querySelector("ytd-channel-name a")
      ?.textContent?.trim() ||
    document.querySelector("#owner #channel-name")
      ?.textContent?.trim() ||
    null;

  const viewCount =
    document.querySelector("ytd-watch-info-text #info")
      ?.textContent?.trim() ||
    document.querySelector("#info-container #info")
      ?.textContent?.trim() ||
    null;

  return {
    videoId,
    title,
    url: window.location.href,
    durationSeconds,
    durationFormatted: formatDuration(durationSeconds),
    channelName,
    viewCount
  };
}

// Send video information to the extension.
function sendVideoInfo() {
  const videoInfo = getVideoInfo();

  chrome.runtime.sendMessage({
    type: "YOUTUBE_VIDEO_CHANGED",
    payload: videoInfo
  }).catch((error) => {
    console.log("Could not send video information:", error);
  });
}

// Seek YouTube video to a specific timestamp.
function seekToTimestamp(seconds) {
  const player = document.getElementById("movie_player");
  const videoElement = document.querySelector("video");

  if (!Number.isFinite(seconds) || seconds < 0) {
    return {
      success: false,
      error: "Invalid timestamp"
    };
  }

  try {
    // Preferred: YouTube native player API.
    if (player && typeof player.seekTo === "function") {
      player.seekTo(seconds, true);

      if (
        typeof player.getPlayerState === "function" &&
        typeof player.playVideo === "function"
      ) {
        player.playVideo();
      }

      console.log("VidMind seeking:", seconds);

      return {
        success: true,
        seconds,
        method: "youtube-player-api"
      };
    }

    // Fallback: HTML video element.
    if (videoElement) {
      videoElement.currentTime = seconds;

      videoElement.play().catch((error) => {
        console.log("Playback could not start:", error);
      });

      return {
        success: true,
        seconds,
        method: "video-element"
      };
    }

    return {
      success: false,
      error: "YouTube player not found"
    };

  } catch (error) {
    console.error("Seeking error:", error);

    return {
      success: false,
      error: error.message
    };
  }
}

// Listen for messages from React side panel.
chrome.runtime.onMessage.addListener(
  (message, sender, sendResponse) => {

    if (message.type === "GET_VIDEO_INFO") {
      sendResponse({
        success: true,
        videoInfo: getVideoInfo()
      });

      return;
    }

    if (message.type === "SEEK_TO_TIMESTAMP") {
      const result = seekToTimestamp(
        Number(message.seconds)
      );

      sendResponse(result);
      return;
    }
  }
);

// Initial video detection.
sendVideoInfo();

// Update metadata when video loads.
function attachVideoMetadataListener() {
  const videoElement = document.querySelector("video");

  if (videoElement) {
    videoElement.addEventListener("loadedmetadata", sendVideoInfo, {
      once: true
    });
  }
}

attachVideoMetadataListener();

// Handle YouTube SPA navigation.
window.addEventListener("yt-navigate-finish", () => {
  setTimeout(() => {
    sendVideoInfo();
    attachVideoMetadataListener();
  }, 1000);
});

window.addEventListener("popstate", () => {
  setTimeout(() => {
    sendVideoInfo();
    attachVideoMetadataListener();
  }, 1000);
});
