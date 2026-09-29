(function () {
  const ICONS = {
    home: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/>',
    wave: '<path d="M3 12h2"/><path d="M7 8v8"/><path d="M11 4v16"/><path d="M15 7v10"/><path d="M19 10v4"/><path d="M21 12h0"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    sliders: '<path d="M4 6h10"/><path d="M18 6h2"/><circle cx="16" cy="6" r="2"/><path d="M4 12h4"/><path d="M12 12h8"/><circle cx="10" cy="12" r="2"/><path d="M4 18h12"/><path d="M20 18h0"/><circle cx="18" cy="18" r="2"/>',
    chart: '<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/><path d="M22 20H2"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
    send: '<path d="M4 12 20 4l-6 16-3-7z"/><path d="m11 13 9-9"/>',
    plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
    edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13 7 4 4"/>',
    trash: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
    upload: '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 20h16"/>',
    download: '<path d="M12 4v12"/><path d="m7 11 5 5 5-5"/><path d="M4 20h16"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.34 5.66"/><path d="M20 4v7h-7"/>',
    x: '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    check: '<path d="m5 12 5 5 9-10"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4"/><path d="M12 17h0"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h0"/>',
    music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    play: '<path d="M7 4v16l13-8z"/>',
    brain: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 3 3h1V4z"/><path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-3 3h-1V4z"/>',
    cloud: '<path d="M7 18a5 5 0 1 1 1.2-9.86A6 6 0 0 1 19.5 11 3.5 3.5 0 0 1 18 18z"/>',
  };

  const STATE_LABELS = {
    idle: "Очікую «Джарвіс»",
    listening: "Слухаю…",
    thinking: "Думаю…",
    executing: "Виконую…",
    speaking: "Говорю…",
    training: "Навчання",
    paused: "Пауза",
  };

  const STAGE_BADGES = {
    exact_binding: ["Бінд", "violet"],
    fuzzy_binding: ["Нечіткий бінд", "violet"],
    rules: ["Локально", "cyan"],
    deepseek_cache: ["Кеш", "green"],
    deepseek: ["DeepSeek", "amber"],
    confirmation: ["Підтвердження", ""],
  };

  const handlers = {};
  const listeners = [];

  const J = {
    state: {
      assistant: "idle",
      level: 0,
      messages: [],
      bindings: [],
      words: [],
      programs: [],
      reminders: [],
      stats: null,
      settings: null,
      nowPlaying: null,
      scanning: false,
      view: "home",
    },
    views: {},
    STATE_LABELS,
    STAGE_BADGES,

    icon(name, extra) {
      const body = ICONS[name] || ICONS.info;
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" ${extra || ""}>${body}</svg>`;
    },

    esc(value) {
      return String(value == null ? "" : value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    },

    on(type, fn) {
      (handlers[type] = handlers[type] || []).push(fn);
    },

    onChange(fn) {
      listeners.push(fn);
    },

    changed(section) {
      listeners.forEach((fn) => fn(section));
    },

    receive(batch) {
      for (const message of batch || []) {
        for (const fn of handlers[message.type] || []) {
          try {
            fn(message.data || {});
          } catch (error) {
            console.error(message.type, error);
          }
        }
      }
    },

    ready: new Promise((resolve) => {
      if (window.pywebview && window.pywebview.api) {
        resolve();
        return;
      }
      window.addEventListener("pywebviewready", () => resolve(), { once: true });
    }),

    async call(name, ...args) {
      await J.ready;
      const api = window.pywebview && window.pywebview.api;
      if (!api || typeof api[name] !== "function") {
        J.toast("Міст недоступний", `Метод ${name} не знайдено`, "error");
        return null;
      }
      try {
        const result = await api[name](...args);
        if (result && result.ok === false) {
          J.toast("Помилка", result.error || "Невідома помилка", "error");
        }
        return result;
      } catch (error) {
        J.toast("Помилка", String(error && error.message ? error.message : error), "error");
        return null;
      }
    },

    toast(title, text, kind) {
      const root = document.getElementById("toasts");
      if (!root) return;
      const type = kind || "info";
      const icon = { error: "alert", success: "check", warn: "clock", info: "info" }[type] || "info";
      const node = document.createElement("div");
      node.className = `toast ${type}`;
      node.innerHTML = `${J.icon(icon)}<div><b>${J.esc(title)}</b><span>${J.esc(text || "")}</span></div>`;
      root.appendChild(node);
      while (root.children.length > 4) root.firstChild.remove();
      setTimeout(() => {
        node.classList.add("leaving");
        setTimeout(() => node.remove(), 320);
      }, type === "error" ? 6500 : 4200);
    },

    modal({ title, body, footer, wide, onClose, header }) {
      const root = document.getElementById("modal-root");
      const backdrop = document.createElement("div");
      backdrop.className = "modal-backdrop";
      backdrop.innerHTML = `
        <div class="modal ${wide ? "wide" : ""}" role="dialog">
          <div class="modal-header"><h2>${J.esc(title)}</h2><button class="btn icon ghost x" data-close>${J.icon("x")}</button></div>
          ${header || ""}
          <div class="modal-body">${body || ""}</div>
          <div class="modal-footer">${footer || ""}</div>
        </div>`;
      const close = () => {
        backdrop.remove();
        document.removeEventListener("keydown", onKey);
        if (onClose) onClose();
      };
      const onKey = (event) => {
        if (event.key === "Escape") close();
      };
      backdrop.addEventListener("mousedown", (event) => {
        if (event.target === backdrop) close();
      });
      backdrop.querySelector("[data-close]").addEventListener("click", close);
      document.addEventListener("keydown", onKey);
      root.appendChild(backdrop);
      const modal = backdrop.querySelector(".modal");
      return {
        element: modal,
        close,
        set(bodyHtml, footerHtml, headerHtml) {
          if (bodyHtml != null) modal.querySelector(".modal-body").innerHTML = bodyHtml;
          if (footerHtml != null) modal.querySelector(".modal-footer").innerHTML = footerHtml;
          if (headerHtml != null) {
            const existing = modal.querySelector(".stepper");
            if (existing) existing.outerHTML = headerHtml;
          }
          J.hydrate(modal);
        },
      };
    },

    confirm(title, text, confirmLabel, danger) {
      return new Promise((resolve) => {
        let answered = false;
        const dialog = J.modal({
          title,
          body: `<p class="muted" style="margin:0 0 6px;line-height:1.6">${J.esc(text)}</p>`,
          footer: `<button class="btn ghost" data-no>Скасувати</button><button class="btn ${danger ? "danger" : "primary"}" data-yes>${J.esc(confirmLabel || "Так")}</button>`,
          onClose: () => {
            if (!answered) resolve(false);
          },
        });
        dialog.element.querySelector("[data-no]").onclick = () => dialog.close();
        dialog.element.querySelector("[data-yes]").onclick = () => {
          answered = true;
          resolve(true);
          dialog.close();
        };
      });
    },

    hydrate(root) {
      (root || document).querySelectorAll("[data-icon]").forEach((node) => {
        node.outerHTML = J.icon(node.getAttribute("data-icon"));
      });
    },

    formatTime(iso) {
      const date = new Date(iso);
      return date.toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit" });
    },

    formatDay(iso) {
      const date = new Date(iso);
      const today = new Date();
      const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      const diff = Math.round((new Date(date.getFullYear(), date.getMonth(), date.getDate()) - start) / 86400000);
      if (diff === 0) return "Сьогодні";
      if (diff === 1) return "Завтра";
      if (diff === 2) return "Післязавтра";
      return date.toLocaleDateString("uk-UA", { day: "numeric", month: "long" });
    },

    relative(iso) {
      const minutes = Math.round((new Date(iso) - new Date()) / 60000);
      if (minutes <= 0) return "зараз";
      if (minutes < 60) return `через ${minutes} хв`;
      const hours = Math.floor(minutes / 60);
      if (hours < 24) return `через ${hours} год ${minutes % 60 ? (minutes % 60) + " хв" : ""}`.trim();
      return `через ${Math.round(hours / 24)} дн`;
    },

    percent(part, total) {
      if (!total) return 0;
      return Math.round((part / total) * 100);
    },

    store: {
      get(key, fallback) {
        try {
          const value = localStorage.getItem(`jarvis.${key}`);
          return value == null ? fallback : JSON.parse(value);
        } catch (error) {
          return fallback;
        }
      },
      set(key, value) {
        try {
          localStorage.setItem(`jarvis.${key}`, JSON.stringify(value));
        } catch (error) {
          return;
        }
      },
    },
  };

  window.J = J;
  window.jarvis = { receive: (batch) => J.receive(batch) };
})();
