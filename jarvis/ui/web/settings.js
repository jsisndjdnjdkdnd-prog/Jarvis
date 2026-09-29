(function () {
  const J = window.J;
  const VOICES = [
    ["uk-UA-OstapNeural", "Остап (укр., чоловічий)"],
    ["uk-UA-PolinaNeural", "Поліна (укр., жіночий)"],
    ["en-GB-RyanNeural", "Ryan (англ., британський — як у фільмі)"],
    ["en-US-GuyNeural", "Guy (англ., американський)"],
    ["ru-RU-DmitryNeural", "Дмитро (рос.)"],
  ];
  const SECTIONS = [
    {
      title: "Мовлення",
      icon: "mic",
      items: [
        { path: "speech.wake.enabled", type: "switch", label: "Wake word «Джарвіс»", hint: "Вимкніть, щоб слухати лише за гарячою клавішею" },
        { path: "speech.command_timeout_seconds", type: "number", label: "Таймаут команди", hint: "Скільки секунд чекати команду після «Джарвіс»", step: 1, min: 2, max: 20 },
        { path: "speech.grammar_enabled", type: "switch", label: "Grammar-режим Vosk", hint: "Фрази з бази підвищують точність розпізнавання" },
        { path: "speech.min_word_confidence", type: "range", label: "Мінімальна впевненість слова", min: 0.2, max: 0.95, step: 0.05 },
      ],
    },
    {
      title: "Голос асистента",
      icon: "wave",
      items: [
        { path: "tts.enabled", type: "switch", label: "Озвучувати відповіді", hint: "edge-tts з кешем, офлайн — pyttsx3" },
        { path: "tts.voice", type: "select", label: "Голос", options: VOICES },
        { path: "tts.offline_fallback", type: "switch", label: "Офлайн-голос без інтернету", hint: "pyttsx3 як резерв" },
      ],
    },
    {
      title: "Розуміння",
      icon: "brain",
      items: [
        { path: "nlu.binding_threshold", type: "range", label: "Поріг нечіткого збігу біндів", min: 60, max: 100, step: 1 },
        { path: "nlu.program_threshold", type: "range", label: "Поріг пошуку програм", min: 60, max: 100, step: 1 },
        { path: "nlu.vocabulary_decision_threshold", type: "range", label: "Поріг навчених слів", min: 0.4, max: 0.95, step: 0.01 },
        { path: "deepseek.enabled", type: "switch", label: "DeepSeek як останній крок", hint: "Ключ береться лише з DEEPSEEK_API_KEY" },
      ],
    },
    {
      title: "Музика і скріншоти",
      icon: "music",
      items: [
        { path: "music.backend", type: "segmented", label: "Відтворення", options: [["vlc", "VLC"], ["browser", "Браузер"]] },
        { path: "music.soundcloud_client_id", type: "text", label: "SoundCloud client_id", hint: "Необов'язково — інакше yt-dlp" },
        { path: "screenshots.directory", type: "folder", label: "Папка скріншотів" },
        { path: "screenshots.copy_to_clipboard", type: "switch", label: "Копіювати в буфер обміну" },
      ],
    },
    {
      title: "Інтерфейс",
      icon: "eye",
      items: [
        { path: "ui.hud_enabled", type: "switch", label: "HUD-оверлей", hint: "Кільце поверх усіх вікон" },
        { path: "ui.push_to_talk_hotkey", type: "text", label: "Push-to-talk", hint: "Наприклад: ctrl+alt+j" },
        { path: "ui.tray_enabled", type: "switch", label: "Згортати у трей" },
        { path: "ui.start_minimized", type: "switch", label: "Запускати згорнутим" },
      ],
    },
  ];
  let draft = {};

  function read(path) {
    return path.split(".").reduce((node, key) => (node == null ? undefined : node[key]), J.state.settings || {});
  }

  function assign(target, path, value) {
    const keys = path.split(".");
    let node = target;
    keys.slice(0, -1).forEach((key) => {
      node[key] = node[key] || {};
      node = node[key];
    });
    node[keys[keys.length - 1]] = value;
  }

  function current(path) {
    return Object.prototype.hasOwnProperty.call(draft, path) ? draft[path] : read(path);
  }

  function control(item) {
    const value = current(item.path);
    const id = `set-${item.path.replace(/\./g, "-")}`;
    if (item.type === "switch") {
      return `<label class="switch"><input type="checkbox" id="${id}" data-path="${item.path}" ${value ? "checked" : ""}><span></span></label>`;
    }
    if (item.type === "range") {
      const fill = ((Number(value) - item.min) / (item.max - item.min)) * 100;
      return `<input class="range" type="range" id="${id}" data-path="${item.path}" min="${item.min}" max="${item.max}" step="${item.step}" value="${J.esc(value)}" style="--fill:${fill}%"><span class="mono" style="min-width:38px;text-align:right" data-out="${item.path}">${J.esc(value)}</span>`;
    }
    if (item.type === "select") {
      return `<select class="select" data-path="${item.path}">${item.options.map(([key, label]) => `<option value="${key}" ${key === value ? "selected" : ""}>${J.esc(label)}</option>`).join("")}</select>`;
    }
    if (item.type === "segmented") {
      return `<div class="segmented">${item.options.map(([key, label]) => `<button data-seg-path="${item.path}" data-seg-value="${key}" class="${key === value ? "active" : ""}">${J.esc(label)}</button>`).join("")}</div>`;
    }
    if (item.type === "folder") {
      return `<input class="input" data-path="${item.path}" value="${J.esc(value || "")}"><button class="btn icon" data-browse="${item.path}">${J.icon("folder")}</button>`;
    }
    return `<input class="input" ${item.type === "number" ? `type="number" min="${item.min}" max="${item.max}" step="${item.step}"` : ""} data-path="${item.path}" value="${J.esc(value == null ? "" : value)}">`;
  }

  function render() {
    const root = document.getElementById("view-settings");
    if (!J.state.settings) {
      root.innerHTML = `<div class="empty"><span class="spinner"></span><span>Завантажую налаштування…</span></div>`;
      return;
    }
    const dirty = Object.keys(draft).length;
    root.innerHTML = `
      <div class="toolbar">
        <span class="muted">Зміни записуються у config.yaml. Частина застосується після перезапуску.</span>
        <div class="grow"></div>
        <button class="btn ghost" data-reset ${dirty ? "" : "disabled"}>Скинути</button>
        <button class="btn primary" data-save ${dirty ? "" : "disabled"}>${J.icon("check")}Зберегти${dirty ? ` (${dirty})` : ""}</button>
      </div>
      <div class="scroll" style="flex:1"><div class="settings-grid">
        ${SECTIONS.map((section) => `
          <div class="card">
            <div class="card-header">${J.icon(section.icon, 'width="18" height="18" style="color:var(--accent)"')}<h3>${J.esc(section.title)}</h3></div>
            <div class="card-body" style="padding-top:4px;padding-bottom:4px">
              ${section.items.map((item) => `
                <div class="setting">
                  <div class="text"><b>${J.esc(item.label)}</b>${item.hint ? `<span>${J.esc(item.hint)}</span>` : ""}</div>
                  <div class="control" style="${["text", "folder", "select"].includes(item.type) ? "width:230px" : ""}">${control(item)}</div>
                </div>`).join("")}
            </div>
          </div>`).join("")}
      </div></div>`;
    root.querySelectorAll("[data-path]").forEach((input) => {
      const path = input.dataset.path;
      const handler = () => {
        let value = input.value;
        if (input.type === "checkbox") value = input.checked;
        else if (input.type === "range" || input.type === "number") value = Number(value);
        draft[path] = value;
        if (input.type === "range") {
          const item = SECTIONS.flatMap((section) => section.items).find((entry) => entry.path === path);
          input.style.setProperty("--fill", `${((value - item.min) / (item.max - item.min)) * 100}%`);
          const out = root.querySelector(`[data-out="${path}"]`);
          if (out) out.textContent = value;
          refreshButtons(root);
          return;
        }
        refreshButtons(root);
      };
      input.addEventListener(input.type === "checkbox" || input.tagName === "SELECT" ? "change" : "input", handler);
    });
    root.querySelectorAll("[data-seg-path]").forEach((button) => {
      button.onclick = () => {
        draft[button.dataset.segPath] = button.dataset.segValue;
        render();
      };
    });
    root.querySelectorAll("[data-browse]").forEach((button) => {
      button.onclick = async () => {
        const result = await J.call("browse_folder");
        if (result && result.path) {
          draft[button.dataset.browse] = result.path;
          render();
        }
      };
    });
    root.querySelector("[data-reset]").onclick = () => {
      draft = {};
      render();
    };
    root.querySelector("[data-save]").onclick = () => {
      const changes = {};
      Object.entries(draft).forEach(([path, value]) => assign(changes, path, value === "" ? null : value));
      J.call("save_settings", changes);
    };
  }

  function refreshButtons(root) {
    const dirty = Object.keys(draft).length;
    const save = root.querySelector("[data-save]");
    save.disabled = !dirty;
    save.innerHTML = `${J.icon("check")}Зберегти${dirty ? ` (${dirty})` : ""}`;
    root.querySelector("[data-reset]").disabled = !dirty;
  }

  J.on("SettingsSnapshot", (data) => {
    J.state.settings = data.values || {};
    draft = {};
    J.changed("settings");
    if (J.state.view === "settings") render();
  });

  J.on("SettingsSaved", (data) => J.toast("Налаштування збережено", data.message, "success"));

  J.views.settings = { title: "Налаштування", subtitle: "config.yaml + .env (DEEPSEEK_API_KEY)", icon: "sliders", render };
})();
