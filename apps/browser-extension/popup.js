document.addEventListener("DOMContentLoaded", async () => {
  const statusBadge = document.getElementById("status-badge");
  const extVersion = document.getElementById("ext-version");
  const activeTabSpan = document.getElementById("active-tab");
  const btnReconnect = document.getElementById("btn-reconnect");

  extVersion.textContent = `v${chrome.runtime.getManifest().version}`;

  // Check active tab
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      activeTabSpan.textContent = tab.title || tab.url || "Untitled";
    }
  } catch (e) {
    activeTabSpan.textContent = "Unavailable";
  }

  // Check badge text to reflect connection status
  chrome.action.getBadgeText({}, (text) => {
    if (text === "ON") {
      statusBadge.textContent = "Connected";
      statusBadge.className = "badge badge-online";
    } else {
      statusBadge.textContent = "Offline";
      statusBadge.className = "badge badge-offline";
    }
  });

  btnReconnect.addEventListener("click", () => {
    btnReconnect.textContent = "Connecting...";
    chrome.runtime.reload();
  });

  // Teach a Task Logic
  const teachStatus = document.getElementById("teach-status");
  const teachGoalInput = document.getElementById("teach-goal-input");
  const btnTeach = document.getElementById("btn-teach");

  // Query background recording state
  chrome.runtime.sendMessage({ type: "GET_RECORDING_STATUS" }, (res) => {
    if (res && res.active) {
      setRecordingUI(true, res.eventsCount);
      if (res.goal) teachGoalInput.value = res.goal;
    }
  });

  function setRecordingUI(isRecording, eventCount = 0) {
    if (isRecording) {
      teachStatus.textContent = `REC (${eventCount})`;
      teachStatus.className = "teach-badge recording";
      btnTeach.textContent = "Stop & Synthesize Skill";
      btnTeach.className = "btn btn-teach recording";
      teachGoalInput.disabled = true;
    } else {
      teachStatus.textContent = "Idle";
      teachStatus.className = "teach-badge";
      btnTeach.textContent = "Record Demonstration";
      btnTeach.className = "btn btn-teach";
      teachGoalInput.disabled = false;
    }
  }

  btnTeach.addEventListener("click", async () => {
    chrome.runtime.sendMessage({ type: "GET_RECORDING_STATUS" }, async (statusRes) => {
      const isCurrentlyRecording = statusRes && statusRes.active;

      if (!isCurrentlyRecording) {
        // Start recording
        const goal = teachGoalInput.value.trim() || "Demonstrated User Workflow";
        chrome.runtime.sendMessage({
          type: "POPUP_START_RECORDING",
          params: { goal: goal }
        }, (res) => {
          setRecordingUI(true, 0);
        });
      } else {
        // Stop recording
        btnTeach.textContent = "Synthesizing...";
        chrome.runtime.sendMessage({
          type: "POPUP_STOP_RECORDING",
          params: {}
        }, async (res) => {
          setRecordingUI(false, 0);
          if (res && res.events) {
            // Send to Emiliano daemon synthesizer endpoint if available
            try {
              const resp = await fetch("http://127.0.0.1:8766/teach/stop", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  session_id: "default_recording",
                  goal: res.goal,
                  events: res.events,
                  title: res.goal || "Synthesized Skill"
                })
              });
              if (resp.ok) {
                const data = await resp.json();
                alert(`✓ Skill Synthesized!\nSaved: ${data.skill.title}\nID: ${data.skill.id}`);
              } else {
                alert(`Captured ${res.events.length} events! Daemon offline, stored in session.`);
              }
            } catch (err) {
              alert(`Recorded ${res.events.length} demonstration events! (Start 'emiliano daemon' to compile automatically)`);
            }
          }
        });
      }
    });
  });
});
