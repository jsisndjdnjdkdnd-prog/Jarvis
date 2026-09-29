(function () {
  const J = window.J;
  const WORD_ACTIONS = [
    ["", "Без дії — лише розпізнавання"],
    ["open_app", "Відкрити програму"],
    ["launch", "Запустити файл / URL"],
    ["close_process", "Закрити процес"],
    ["open_folder", "Відкрити папку"],
    ["play_track", "Увімкнути трек"],
  ];
  const WAVE_BARS = 28;
  let session = null;

  function training() {
    const values = (J.state.settings && J.state.settings.training) || {};
    return { min: values.min_samples || 3, recommended: values.recommended_samples || 5 };
  }

  function render() {
    const root = document.getElementById("view-words");
    const words = J.state.words;
    root.innerHTML = `
      <div class="toolbar">
        <span class="muted">Навчіть Джарвіса словам, які Vosk не знає: Malwarebytes, Dota, імена, назви ігор.</span>
        <div class="grow"></div>
        <button class="btn primary" data-word-add>${J.icon("plus")}Додати слово</button>
      </div>
      <div class="scroll" style="flex:1;padding-bottom:6px">
        <div class="grid-cards">
          ${words.map(card).join("")}
          <div class="card add-card" data-word-add>${J.icon("mic")}<b>Нове слово</b><span class="muted">3–5 зразків вимови</span></div>
        </div>
      </div>`;
    root.querySelectorAll("[data-word-add]").forEach((node) => (node.onclick = () => openWizard(null)));
    root.querySelectorAll("[data-word-train]").forEach((node) => {
      node.onclick = () => openWizard(Number(node.dataset.wordTrain));
    });
    root.querySelectorAll("[data-word-delete]").forEach((node) => {
      node.onclick = async () => {
        const word = words.find((item) => String(item.id) === node.dataset.wordDelete);
        if (word && (await J.confirm("Видалити слово?", `«${word.text}» разом з усіма зразками вимови буде видалено.`, "Видалити", true))) {
          J.call("delete_word", word.id);
        }
      };
    });
  }

  function card(word) {
    const aliases = (word.aliases || []).slice(0, 10);
    return `
      <div class="card word-card">
        <div class="row">
          <h3 class="grow ellipsis">${J.esc(word.text)}</h3>
          ${word.is_trained ? `<span class="badge green">${J.icon("check", 'width="12" height="12"')}Навчено</span>` : `<span class="badge amber">Чернетка</span>`}
        </div>
        <div class="row muted" style="font-size:12.5px;gap:14px">
          <span>${J.icon("mic", 'width="14" height="14" style="vertical-align:-2px"')} ${word.sample_count || 0} зразків</span>
          ${word.acoustic_threshold ? `<span>DTW ${Number(word.acoustic_threshold).toFixed(2)}</span>` : ""}
          ${word.action ? `<span class="badge cyan">${J.esc(word.action.type)}: ${J.esc(word.action.target)}</span>` : ""}
        </div>
        <div class="aliases">
          ${aliases.length ? aliases.map((alias) => `<span class="alias" style="opacity:${0.45 + 0.55 * (alias.weight || 1)}" title="вага ${Number(alias.weight).toFixed(2)}, влучань ${alias.hits}">${J.esc(alias.alias)}</span>`).join("") : '<span class="muted" style="font-size:12px">Vosk ще не чув цього слова</span>'}
        </div>
        <div class="row" style="margin-top:auto">
          <button class="btn sm primary" data-word-train="${word.id}">${J.icon("mic")}Навчити</button>
          <div class="grow"></div>
          <button class="btn icon sm danger" data-word-delete="${word.id}" title="Видалити">${J.icon("trash")}</button>
        </div>
      </div>`;
  }

  function stepper(active) {
    const steps = ["Слово", "Зразки вимови", "Тест"];
    return `<div class="stepper">${steps.map((label, index) => {
      const number = index + 1;
      const state = number === active ? "active" : number < active ? "done" : "";
      return `<div class="step ${state}"><i>${number < active ? "✓" : number}</i>${label}</div>`;
    }).join("")}</div>`;
  }

  function openWizard(wordId) {
    session = {
      wordId,
      word: null,
      step: wordId == null ? 1 : 2,
      samples: [],
      busy: false,
      recording: false,
      status: "",
      error: false,
      model: null,
      result: null,
      pendingText: null,
    };
    session.dialog = J.modal({
      title: "Навчити слово",
      wide: true,
      header: stepper(session.step),
      body: "",
      footer: "",
      onClose: () => {
        if (session && session.word) J.call("close_training", session.word.id);
        session = null;
      },
    });
    if (wordId != null) {
      session.status = "Завантажую зразки…";
      J.call("start_training", wordId);
    }
    draw();
  }

  function draw() {
    if (!session) return;
    const views = { 1: stepWord, 2: stepSamples, 3: stepTest };
    const [body, footer] = views[session.step]();
    session.dialog.set(body, footer, stepper(session.step));
    bind();
  }

  function stepWord() {
    return [
      `
      <div class="field"><label>Слово так, як воно пишеться</label><input class="input" id="tw-text" placeholder="Malwarebytes" value="${J.esc(session.pendingText || "")}"></div>
      <div class="row" style="align-items:flex-start">
        <div class="field grow"><label>Прив'язка до дії (необов'язково)</label><select class="select" id="tw-action">${WORD_ACTIONS.map(([value, label]) => `<option value="${value}">${J.esc(label)}</option>`).join("")}</select></div>
        <div class="field grow"><label>Ціль дії</label><input class="input" id="tw-target" placeholder="Malwarebytes"></div>
      </div>
      <p class="muted" style="line-height:1.6;margin:4px 0 0">Далі ви кілька разів вимовите слово. Джарвіс запам'ятає, як його «чує» Vosk (аліаси), та зніме акустичний відбиток голосу (MFCC + DTW).</p>`,
      `<button class="btn ghost" data-close-modal>Скасувати</button><button class="btn primary" data-tw-create>Далі ${J.icon("send")}</button>`,
    ];
  }

  function stepSamples() {
    const { min, recommended } = training();
    const count = session.samples.length;
    const dots = Array.from({ length: Math.max(recommended, count) }, (_, index) => `<i class="${index < count ? "on" : ""} ${index === min - 1 ? "min" : ""}"></i>`).join("");
    return [
      `
      <div class="recorder">
        <div style="font-size:22px;font-weight:700">${J.esc(session.word ? session.word.text : "…")}</div>
        <button class="rec-btn ${session.recording ? "recording" : ""}" data-tw-record ${session.busy ? "disabled" : ""}>${J.icon("mic")}</button>
        <div class="wave" id="tw-wave">${Array.from({ length: WAVE_BARS }, () => "<span></span>").join("")}</div>
        <div class="dots">${dots}</div>
        <div class="status-line ${session.error ? "error" : ""}">${J.esc(session.status || `Натисніть і скажіть слово. Потрібно щонайменше ${min}, рекомендовано ${recommended}.`)}</div>
        <div class="samples">
          ${session.samples.map((sample, index) => `
            <div class="sample">
              <span class="idx">${index + 1}</span>
              <span class="heard">${sample.transcripts && sample.transcripts.length ? sample.transcripts.slice(0, 3).map(J.esc).join(" · ") : '<span class="muted">Vosk не розпізнав — акустика все одно збережена</span>'}</span>
              <span class="muted mono">${Number(sample.duration_seconds).toFixed(1)} с</span>
              <button class="btn icon sm danger" data-tw-drop="${sample.id}" title="Видалити зразок">${J.icon("x")}</button>
            </div>`).join("")}
        </div>
      </div>`,
      `<button class="btn ghost" data-close-modal>Закрити</button><button class="btn primary" data-tw-finish ${count < min || session.busy ? "disabled" : ""}>${J.icon("brain")}Завершити й побудувати модель</button>`,
    ];
  }

  function gauge(label, value, color) {
    const radius = 40;
    const length = 2 * Math.PI * radius;
    const shown = value == null ? 0 : Math.max(0, Math.min(1, value));
    return `
      <div class="gauge" style="--gauge:${color}">
        <svg viewBox="0 0 96 96"><circle class="track" cx="48" cy="48" r="${radius}"/><circle class="value" cx="48" cy="48" r="${radius}" stroke-dasharray="${length}" stroke-dashoffset="${length * (1 - shown)}"/></svg>
        <div class="num">${value == null ? "—" : Math.round(shown * 100) + "%"}</div>
        <div class="cap">${J.esc(label)}</div>
      </div>`;
  }

  function stepTest() {
    const model = session.model;
    const result = session.result;
    const aliases = model && model.aliases ? model.aliases.slice(0, 14) : [];
    return [
      `
      <div class="row" style="align-items:flex-start;gap:18px">
        <div class="recorder" style="width:190px;flex:none">
          <button class="rec-btn ${session.recording ? "recording" : ""}" data-tw-test ${session.busy ? "disabled" : ""}>${J.icon("mic")}</button>
          <div class="wave" id="tw-wave" style="height:34px">${Array.from({ length: 16 }, () => "<span></span>").join("")}</div>
          <div class="status-line ${session.error ? "error" : ""}" style="font-size:12.5px">${J.esc(session.status || "Скажіть слово для перевірки")}</div>
        </div>
        <div class="grow">
          <div class="field"><label>Vosk чує це слово як</label><div class="aliases" style="display:flex;flex-wrap:wrap;gap:6px">${aliases.map((alias) => `<span class="alias">${J.esc(alias.alias)}</span>`).join("") || '<span class="muted">немає аліасів</span>'}</div></div>
          <div class="muted" style="font-size:12px;margin-bottom:12px">Поріг DTW (з розкиду між зразками): <b class="mono" style="color:var(--text)">${model ? Number(model.threshold).toFixed(3) : "—"}</b></div>
          <div class="gauge-row">
            ${gauge("Аліаси", result ? result.alias_score : null, "var(--accent)")}
            ${gauge("Акустика", result ? result.acoustic_score : null, "var(--violet)")}
            ${gauge("Разом", result ? result.combined_score : null, result && result.matched ? "var(--green)" : "var(--amber)")}
          </div>
          ${result ? `<div class="verdict ${result.matched ? "ok" : "bad"}">${result.matched ? "✓ Збіглося" : "✕ Не збіглося"} — розпізнано «${J.esc(result.transcript)}»</div>` : ""}
        </div>
      </div>`,
      `<button class="btn" data-tw-more>${J.icon("plus")}Додати ще зразків</button><button class="btn success" data-tw-save ${session.busy ? "disabled" : ""}>${J.icon("check")}Ок, зберегти</button>`,
    ];
  }

  function bind() {
    const element = session.dialog.element;
    const on = (selector, handler) => element.querySelectorAll(selector).forEach((node) => (node.onclick = handler));
    on("[data-close-modal]", () => session.dialog.close());
    on("[data-tw-create]", () => {
      const text = element.querySelector("#tw-text").value.trim();
      const type = element.querySelector("#tw-action").value;
      const target = element.querySelector("#tw-target").value.trim();
      if (!text) {
        J.toast("Введіть слово", "Наприклад: Malwarebytes", "warn");
        return;
      }
      session.pendingText = text;
      session.busy = true;
      J.call("add_word", text, type && target ? { type, target } : null);
    });
    on("[data-tw-record]", () => {
      if (!session.word) return;
      session.busy = true;
      session.recording = true;
      session.error = false;
      session.status = "Говоріть…";
      draw();
      J.call("record_sample", session.word.id);
    });
    element.querySelectorAll("[data-tw-drop]").forEach((node) => {
      node.onclick = () => J.call("delete_sample", session.word.id, Number(node.dataset.twDrop));
    });
    on("[data-tw-finish]", () => {
      session.busy = true;
      session.status = "Будую акустичну модель…";
      draw();
      J.call("finish_training", session.word.id);
    });
    on("[data-tw-test]", () => {
      session.busy = true;
      session.recording = true;
      session.error = false;
      session.status = "Слухаю…";
      draw();
      J.call("test_word", session.word.id);
    });
    on("[data-tw-more]", () => {
      session.step = 2;
      session.status = "";
      draw();
    });
    on("[data-tw-save]", () => {
      session.busy = true;
      J.call("save_word", session.word.id);
    });
  }

  function belongs(wordId) {
    return session && session.word && session.word.id === wordId;
  }

  J.on("TrainingSessionStarted", (data) => {
    if (!session) return;
    const expected = session.wordId != null ? session.word == null && data.word.id === session.wordId : session.word == null;
    if (!expected && !belongs(data.word.id)) return;
    session.word = data.word;
    session.samples = data.samples || [];
    session.step = 2;
    session.busy = false;
    session.status = "";
    draw();
  });

  J.on("TrainingRecordingStarted", (data) => {
    if (!belongs(data.word_id)) return;
    session.status = "Говоріть зараз…";
    const line = session.dialog.element.querySelector(".status-line");
    if (line) line.textContent = session.status;
  });

  J.on("TrainingSamplesChanged", (data) => {
    if (!belongs(data.word_id)) return;
    const added = (data.samples || []).length > session.samples.length;
    session.samples = data.samples || [];
    session.busy = false;
    session.recording = false;
    session.error = false;
    const { min, recommended } = training();
    const count = session.samples.length;
    session.status = added
      ? count >= recommended
        ? "Чудово! Зразків достатньо — можна завершувати."
        : count >= min
          ? `Зразок ${count} записано. Ще ${recommended - count} для кращої точності.`
          : `Зразок ${count} записано. Ще ${min - count}.`
      : "Зразок видалено.";
    draw();
  });

  J.on("TrainingModelBuilt", (data) => {
    if (!belongs(data.word_id)) return;
    session.model = data;
    session.step = 3;
    session.busy = false;
    session.result = null;
    session.status = "Модель готова. Перевірте, чи я вас розумію.";
    draw();
  });

  J.on("TrainingTestResult", (data) => {
    if (!belongs(data.word_id)) return;
    session.result = data;
    session.busy = false;
    session.recording = false;
    session.status = data.matched ? "Я вас зрозумів." : "Спробуйте ще раз або додайте зразків.";
    draw();
  });

  J.on("TrainingSaved", (data) => {
    if (!belongs(data.word_id)) return;
    J.toast("Слово збережено", `Тепер я впізнаю «${session.word.text}»`, "success");
    session.dialog.close();
  });

  J.on("TrainingFailed", (data) => {
    if (!session) return;
    if (data.word_id != null && session.word && data.word_id !== session.word.id) return;
    session.busy = false;
    session.recording = false;
    session.error = true;
    session.status = data.reason;
    if (session.step === 1) J.toast("Навчання", data.reason, "error");
    draw();
  });

  J.on("MicLevelChanged", (data) => {
    if (!session || !session.recording) return;
    const wave = document.getElementById("tw-wave");
    if (!wave) return;
    const bars = wave.children;
    const level = Math.min(1, data.level * 1.6);
    for (let index = 0; index < bars.length; index += 1) {
      const center = 1 - Math.abs(index - bars.length / 2) / (bars.length / 2);
      const jitter = 0.55 + Math.random() * 0.45;
      bars[index].style.height = `${Math.max(8, level * center * jitter * 100)}%`;
    }
  });

  J.on("VocabularyListed", (data) => {
    J.state.words = data.words || [];
    J.changed("words");
    if (J.state.view === "words") render();
  });

  J.views.words = { title: "Слова та вимова", subtitle: "Персональне навчання вимови: аліаси Vosk + акустичні шаблони", icon: "wave", render, count: () => J.state.words.length };
})();
