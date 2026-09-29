(function () {
  const J = window.J;
  let smoothed = 0;
  let clickTimer = null;
  let captionTimer = null;

  function caption(text) {
    const node = document.getElementById("hud-caption");
    node.textContent = text;
  }

  J.on("AssistantStateChanged", (data) => {
    document.body.dataset.state = data.state;
    if (data.state !== "speaking") caption(J.STATE_LABELS[data.state] || data.state);
  });

  J.on("WakeWordDetected", () => {
    document.body.dataset.state = "listening";
    caption("Слухаю, сер");
  });

  J.on("MicLevelChanged", (data) => {
    smoothed = Math.max(data.level || 0, smoothed * 0.7);
    document.body.style.setProperty("--level", Math.min(1, smoothed * 1.5).toFixed(3));
  });

  J.on("SpeechStarted", (data) => caption(data.text));

  J.on("CommandHandled", (data) => {
    clearTimeout(captionTimer);
    caption(data.reply);
    captionTimer = setTimeout(() => caption(J.STATE_LABELS[document.body.dataset.state] || ""), 6000);
  });

  document.addEventListener("DOMContentLoaded", () => {
    window.JReactor.mount(document);
    window.JReactor.start();
    const stage = document.getElementById("hud-stage");
    stage.addEventListener("click", () => {
      clearTimeout(clickTimer);
      clickTimer = setTimeout(() => J.call("listen"), 240);
    });
    stage.addEventListener("dblclick", () => {
      clearTimeout(clickTimer);
      J.call("show_main");
    });
    setInterval(() => {
      smoothed *= 0.7;
      document.body.style.setProperty("--level", Math.min(1, smoothed * 1.5).toFixed(3));
    }, 120);
  });
})();
