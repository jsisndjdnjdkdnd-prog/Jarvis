(function () {
  const J = window.J;
  const ORDER = ["home", "bindings", "words", "programs", "reminders", "settings", "stats"];
  const METER_BARS = 7;
  let smoothed = 0;

  function renderNav() {
    const nav = document.getElementById("nav");
    nav.innerHTML = ORDER.map((name) => {
      const view = J.views[name];
      const count = view.count ? view.count() : null;
      return `<button class="nav-item ${J.state.view === name ? "active" : ""}" data-view="${name}">${J.icon(view.icon)}<span>${J.esc(view.title)}</span>${count ? `<span class="count">${count}</span>` : ""}</button>`;
    }).join("");
    nav.querySelectorAll("[data-view]").forEach((button) => {
      button.onclick = () => show(button.dataset.view);
    });
  }

  function show(name) {
    const view = J.views[name] || J.views.home;
    J.state.view = J.views[name] ? name : "home";
    J.store.set("view", J.state.view);
    document.querySelectorAll(".view").forEach((node) => node.classList.toggle("active", node.id === `view-${J.state.view}`));
    document.getElementById("view-title").textContent = view.title;
    document.getElementById("view-subtitle").textContent = view.subtitle || "";
    view.render();
    renderNav();
  }

  function setState(state) {
    J.state.assistant = state;
    document.body.dataset.state = state;
    document.getElementById("status-label").textContent = J.STATE_LABELS[state] || state;
    document.getElementById("top-mic").classList.toggle("live", state === "listening");
  }

  function setLevel(level) {
    smoothed = Math.max(level, smoothed * 0.7);
    document.body.style.setProperty("--level", Math.min(1, smoothed * 1.5).toFixed(3));
    const bars = document.getElementById("top-meter").children;
    for (let index = 0; index < bars.length; index += 1) {
      const threshold = (index + 1) / (METER_BARS + 1);
      const height = smoothed * 1.6 > threshold ? 100 : 20 + (smoothed * 1.6 / threshold) * 60;
      bars[index].style.height = `${Math.min(100, height)}%`;
    }
  }

  function bindGlobalActions() {
    document.addEventListener("click", (event) => {
      const target = event.target.closest("[data-action]");
      if (!target) return;
      const action = target.dataset.action;
      if (action === "listen") J.call("listen");
      if (action === "correction") J.call("correction");
      if (action === "toggle-hud") J.call("toggle_hud");
    });
  }

  J.on("AssistantStateChanged", (data) => setState(data.state));
  J.on("MicLevelChanged", (data) => setLevel(data.level || 0));
  J.on("WakeWordDetected", () => setState("listening"));
  J.on("ErrorOccurred", (data) => J.toast("Увага", data.message, "error"));
  J.on("NowPlayingChanged", (data) => {
    J.state.nowPlaying = data.track;
    const chip = document.getElementById("now-playing");
    chip.classList.toggle("visible", Boolean(data.track));
    document.getElementById("now-playing-title").textContent = data.track ? `${data.track.artist ? data.track.artist + " — " : ""}${data.track.title}` : "";
  });

  J.onChange(() => renderNav());

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("top-meter").innerHTML = Array.from({ length: METER_BARS }, () => "<span></span>").join("");
    J.hydrate(document);
    window.JReactor.mount(document);
    window.JReactor.start();
    bindGlobalActions();
    show(J.store.get("view", "home"));
    setInterval(() => setLevel(0), 120);
    J.ready.then(() => J.call("bootstrap"));
  });
})();
