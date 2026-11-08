
chrome.runtime.onInstalled.addListener(() => {
    console.log("VidMind extension installed!");
  
    chrome.sidePanel.setPanelBehavior({
      openPanelOnActionClick: true
    });
  });
  