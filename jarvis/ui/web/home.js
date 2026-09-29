(function () {
  const J = window.J;
  const QUICK = [
    ["clock", "Котра година?"],
    ["music", "Увімкни щось під настрій"],
    ["bolt", "Таймер на 5 хвилин"],
    ["eye", "Зроби скрін"],
    ["bell", "Які в мене нагадування?"],
  ];
  const MAX_MESSAGES = 120;
  let typing = null;

  function render() {
    const root = document.getElementById("view-home");
    root.innerHTML = `
      <div class="home">
        <div class="card stage">
          <div class="reactor-wrap" data-action="listen" title="Натисніть, щоб говорити"><div data-reactor="stage"></div></div>
          <div class="stage-state" id="stage-state">${J.esc(J.STATE_LABELS[J.state.assistant] || "")}</div>
          <div class="stage-reply" id="stage-reply">До ваших послуг, сер.<span class="caret"></span></div>
          <div class="quick">
            ${QUICK.map(([icon, text]) => `<button class="chip" data-quick="${J.esc(text)}">${J.icon(icon, 'width="14" height="14"')}${J.esc(text)}</button>`).join("")}
          </div>
          <div class="mini-stats">
            <div class="mini-stat"><b id="ms-local">—</b><span>оброблено офлайн</span></div>
            <div class="mini-stat"><b id="ms-bindings">0</b><span>біндів і фраз</span></div>
            <div class="mini-stat"><b id="ms-words">0</b><span>навчених слів</span></div>
          </div>
        </div>
        <div class="card chat">
          <div class="card-header">
            ${J.icon("wave", 'width="18" height="18" style="color:var(--accent)"')}
            <h2>Діалог</h2>
            <span class="muted" style="font-size:12px">текстом або голосом</span>
            <div style="flex:1"></div>
            <button class="btn sm ghost" data-action="correction" title="Позначити останню дію як помилкову">${J.icon("undo")}Не те</button>
          </div>
          <div class="messages" id="messages"></div>
          <form class="composer" id="composer">
            <input class="input" id="command-input" autocomplete="off" placeholder="Напишіть команду, наприклад: відкрий хром">
            <button class="btn primary icon" type="submit" title="Надіслати" style="width:46px;height:46px;border-radius:14px">${J.icon("send")}</button>
          </form>
        </div>
      </div>`;
    window.JReactor.mount(root);
    renderMessages();
    renderMiniStats();
    root.querySelector("#composer").addEventListener("submit", (event) => {
      event.preventDefault();
      const input = root.querySelector("#command-input");
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      J.call("send_command", text);
    });
    root.querySelectorAll("[data-quick]").forEach((chip) => {
      chip.addEventListener("click", () => J.call("send_command", chip.dataset.quick));
    });
  }

  function stageBadge(stage) {
    const badge = J.STAGE_BADGES[stage];
    if (!badge) return "";
    return `<span class="badge ${badge[1]}">${J.esc(badge[0])}</span>`;
  }

  function messageHtml(message) {
    if (message.role === "user") {
      return `<div class="msg user"><div class="bubble">${J.esc(message.text)}</div></div>`;
    }
    const kind = message.role === "system" ? "system" : message.success === false ? "fail" : "jarvis";
    const meta = message.intent || message.stage
      ? `<div class="msg-meta">${stageBadge(message.stage)}${message.intent ? `<span class="mono">${J.esc(message.intent)}</span>` : ""}</div>`
      : "";
    return `<div class="msg ${kind}"><div class="avatar"><div data-reactor="avatar"></div></div><div><div class="bubble">${J.esc(message.text)}</div>${meta}</div></div>`;
  }

  function renderMessages() {
    const list = document.getElementById("messages");
    if (!list) return;
    if (!J.state.messages.length) {
      list.innerHTML = `<div class="empty">${J.icon("wave")}<strong>Тут з'явиться розмова</strong><span>Скажіть «Джарвіс, відкрий хром» або напишіть команду нижче</span></div>`;
      return;
    }
    list.innerHTML = J.state.messages.map(messageHtml).join("");
    window.JReactor.mount(list);
    list.scrollTop = list.scrollHeight;
  }

  function renderMiniStats() {
    const stats = J.state.stats;
    const local = document.getElementById("ms-local");
    if (local && stats) {
      const counts = stats.stage_counts || {};
      const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
      const remote = counts.deepseek || 0;
      local.textContent = total ? `${J.percent(total - remote, total)}%` : "100%";
    }
    const bindings = document.getElementById("ms-bindings");
    if (bindings) bindings.textContent = J.state.bindings.length;
    const words = document.getElementById("ms-words");
    if (words) words.textContent = J.state.words.filter((word) => word.is_trained).length;
  }

  function typeReply(text) {
    const node = document.getElementById("stage-reply");
    if (!node) return;
    clearInterval(typing);
    let index = 0;
    typing = setInterval(() => {
      index += 2;
      node.innerHTML = `${J.esc(text.slice(0, index))}<span class="caret"></span>`;
      if (index >= text.length) clearInterval(typing);
    }, 18);
  }

  function push(message) {
    J.state.messages.push(message);
    if (J.state.messages.length > MAX_MESSAGES) J.state.messages.splice(0, J.state.messages.length - MAX_MESSAGES);
    renderMessages();
  }

  J.on("CommandHandled", (data) => {
    push({ role: "user", text: data.text });
    push({ role: "jarvis", text: data.reply, success: data.success, intent: data.intent_name, stage: data.stage });
    typeReply(data.reply);
  });

  J.on("SpeechStarted", (data) => {
    if (data.text) typeReply(data.text);
  });

  J.on("TimerFinished", (data) => push({ role: "system", text: `⏰ Таймер на ${data.label} завершено` }));
  J.on("ReminderDue", (data) => push({ role: "system", text: `🔔 ${data.reminder.message}` }));

  J.on("AssistantStateChanged", (data) => {
    const label = document.getElementById("stage-state");
    if (label) label.textContent = J.STATE_LABELS[data.state] || data.state;
  });

  J.onChange((section) => {
    if (["stats", "bindings", "words"].includes(section)) renderMiniStats();
  });

  J.views.home = { title: "Головна", subtitle: "Голосовий асистент J.A.R.V.I.S.", icon: "home", render };
})();
