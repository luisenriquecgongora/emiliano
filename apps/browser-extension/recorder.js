/**
 * Emiliano Teach-a-Task DOM Recorder (Content Script)
 * Captures user demonstration events (clicks, inputs, navigations)
 * and transmits telemetry to synthesize production SKILL.md packages.
 */

(function () {
  if (window.__emilianoRecorderActive) return;
  window.__emilianoRecorderActive = true;

  console.log("[Emiliano Recorder] Active on page:", window.location.href);

  // Notify navigation
  chrome.runtime.sendMessage({
    type: "RECORDED_EVENT",
    event: {
      type: "navigate",
      url: window.location.href,
      title: document.title,
      timestamp: Date.now()
    }
  });

  function getResilientSelector(el) {
    if (!el || el === document.body) return "body";

    // 1. data-testid
    if (el.getAttribute("data-testid")) {
      return `[data-testid="${el.getAttribute("data-testid")}"]`;
    }

    // 2. aria-label
    if (el.getAttribute("aria-label")) {
      return `[aria-label="${el.getAttribute("aria-label")}"]`;
    }

    // 3. name attribute for form inputs
    if (el.getAttribute("name")) {
      return `${el.tagName.toLowerCase()}[name="${el.getAttribute("name")}"]`;
    }

    // 4. Clean ID (not random/numeric)
    if (el.id && !/\d{4,}/.test(el.id)) {
      return `#${el.id}`;
    }

    // 5. Semantic tag and class
    const tag = el.tagName.toLowerCase();
    const classes = Array.from(el.classList || [])
      .filter(c => !c.includes("hover") && !c.includes("active") && !/\d{3,}/.test(c))
      .slice(0, 2);

    if (classes.length > 0) {
      return `${tag}.${classes.join(".")}`;
    }

    return tag;
  }

  // Click listener
  document.addEventListener("click", (e) => {
    const target = e.target;
    if (!target) return;

    const selector = getResilientSelector(target);
    const text = (target.innerText || target.textContent || "").trim().slice(0, 50);

    chrome.runtime.sendMessage({
      type: "RECORDED_EVENT",
      event: {
        type: "click",
        tag: target.tagName.toLowerCase(),
        selector: selector,
        text: text,
        url: window.location.href,
        timestamp: Date.now()
      }
    });
  }, true);

  // Input / Change listener
  document.addEventListener("change", (e) => {
    const target = e.target;
    if (!target || !("value" in target)) return;

    const isPassword = target.type === "password";
    const value = isPassword ? "[REDACTED_PASSWORD]" : target.value;
    const selector = getResilientSelector(target);

    chrome.runtime.sendMessage({
      type: "RECORDED_EVENT",
      event: {
        type: "input",
        tag: target.tagName.toLowerCase(),
        selector: selector,
        value: value,
        isSensitive: isPassword,
        url: window.location.href,
        timestamp: Date.now()
      }
    });
  }, true);

})();
