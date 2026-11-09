
console.log("VidMind content script loaded!");

// Extract information about the current YouTube video
function getVideoInfo() {
  const url = new URL(window.location.href);

  let videoId = null;

  // Normal YouTube video
  if (url.pathname === "/watch") {
    videoId = url.searchParams.get("v");
  }

  // YouTube Shorts
  else if (url.pathname.startsWith("/shorts/")) {
    videoId = url.pathname.split("/")[2];
  }

  // No supported video found
  if (!videoId) {
    return null;
  }

  const title =
    document.querySelector("h1 yt-formatted-string")
      ?.textContent?.trim() ||
    document.title.replace(" - YouTube", "").trim();

  return {
    videoId,
    title,
    url: window.location.href
  };
}

// Send video information to the extension
function sendVideoInfo() {
  const videoInfo = getVideoInfo();

  if (!videoInfo) {
    chrome.runtime.sendMessage({
      type: "YOUTUBE_VIDEO_CHANGED",
      payload: null
    }).catch(() => {});

    return;
  }

  console.log("Detected YouTube video:", videoInfo);

  chrome.runtime.sendMessage({
    type: "YOUTUBE_VIDEO_CHANGED",
    payload: videoInfo
  }).catch((error) => {
    console.log("Could not send video information:", error);
  });
}

// Allow the side panel to request current video information
chrome.runtime.onMessage.addListener(
  (message, sender, sendResponse) => {
    if (message.type === "GET_VIDEO_INFO") {
      sendResponse(getVideoInfo());
    }
  }
);

// Initial detection
sendVideoInfo();

// YouTube uses SPA navigation, so listen for navigation events
window.addEventListener("yt-navigate-finish", () => {
  setTimeout(sendVideoInfo, 500);
});

window.addEventListener("popstate", sendVideoInfo);
