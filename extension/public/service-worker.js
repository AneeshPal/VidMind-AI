
chrome.runtime.onInstalled.addListener(() => {
    console.log("VidMind installed successfully!");
  
    chrome.sidePanel.setPanelBehavior({
      openPanelOnActionClick: true
    });
  });
  
  // Listen for video information from content scripts
  chrome.runtime.onMessage.addListener((message, sender) => {
    if (message.type === "YOUTUBE_VIDEO_CHANGED") {
      console.log(
        "Video information received:",
        message.payload
      );
    }
  });
  