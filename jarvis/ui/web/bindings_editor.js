(function () {
  const J = window.J;
  const ACTIONS = {
    open_app: { label: "Відкрити програму", hint: "Назва програми, як ви її називаєте: Discord, дота", badge: "cyan" },
    launch: { label: "Файл / URL / steam://", hint: "C:\\Games\\game.exe, https://…, steam://rungameid/570", badge: "cyan", browse: "file" },
    close_process: { label: "Закрити процес", hint: "Назва програми або процесу: chrome, discord.exe", badge: "red" },
    open_folder: { label: "Відкрити папку", hint: "Завантаження, документи або повний шлях", badge: "amber", browse: "folder" },
    shell: { label: "Shell-команда", hint: "Будь-яка команда cmd, наприклад: ipconfig /flushdns", badge: "amber" },
    hotkey: { label: "Гаряча клавіша", hint: "ctrl+shift+esc, win+d, alt+tab", badge: "violet" },
    play_track: { label: "Увімкнути трек", hint: "Виконавець і назва треку на SoundCloud", badge: "violet" },
    macro: { label: "Макрос (ланцюжок)", hint: "", badge: "green" },
    intent: { label: "Вивчена команда", hint: "", badge: "green" },
  };
  const SOURCES = { user: "вручну", voice: "голосом", learned: "самонавчання", imported: "імпорт" };
  const STEP_TYPES = ["open_app", "launch", "close_process", "open_folder", "shell", "hotkey", "play_track"];
  let query = "";

  function describe(action) {
    if (action.type === "macro") {
      return (action.steps || []).map((step) => `${ACTIONS[step.type] ? ACTIONS[step.type].label : step.type}: ${step.target}`).join("  →  ");
    }
    if (action.type === "intent" && action.intent) return action.intent.name;
    return action.target || "";
  }

  function render() {
    const root = document.getElementById("view-bindings");
    const items = J.state.bindings.filter((binding) => {
      if (!query) return true;
      const haystack = `${binding.phrase} ${describe(binding.action)}`.toLowerCase();
      return haystack.includes(query);
    });
    root.innerHTML = `
      <div class="toolbar">
        <div class="search">${J.icon("search")}<input class="input" id="binding-search" placeholder="Пошук фрази або дії" value="${J.esc(query)}"></div>
        <span class="muted">${items.length} з ${J.state.bindings.length}</span>
        <div class="grow"></div>
        <button class="btn" data-bind-import>${J.icon("upload")}Імпорт</button>
        <button class="btn" data-bind-export>${J.icon("download")}Експорт</button>
        <button class="btn primary" data-bind-new>${J.icon("plus")}Новий бінд</button>
      </div>
      <div class="scroll" style="flex:1">
        ${items.length ? table(items) : empty()}
      </div>`;
    const search = root.querySelector("#binding-search");
    search.addEventListener("input", () => {
      query = search.value.trim().toLowerCase();
      render();
      const again = document.getElementById("binding-search");
      again.focus();
      again.setSelectionRange(again.value.length, again.value.length);
    });
    root.querySelector("[data-bind-new]").onclick = () => openEditor(null);
    root.querySelector("[data-bind-import]").onclick = () => J.call("import_bindings");
    root.querySelector("[data-bind-export]").onclick = () => J.call("export_bindings");
    root.querySelectorAll("[data-edit]").forEach((button) => {
      button.onclick = () => openEditor(J.state.bindings.find((item) => String(item.id) === button.dataset.edit));
    });
    root.querySelectorAll("[data-delete]").forEach((button) => {
      button.onclick = async () => {
        const binding = J.state.bindings.find((item) => String(item.id) === button.dataset.delete);
        if (binding && (await J.confirm("Видалити бінд?", `Фраза «${binding.phrase}» більше не спрацьовуватиме.`, "Видалити", true))) {
          J.call("delete_binding", binding.id);
        }
      };
    });
  }

  function table(items) {
    return `
      <table class="table">
        <thead><tr><th>Фраза</th><th>Дія</th><th>Ціль</th><th>Джерело</th><th style="text-align:right">Разів</th><th></th></tr></thead>
        <tbody>
          ${items.map((binding) => {
            const meta = ACTIONS[binding.action.type] || { label: binding.action.type, badge: "" };
            return `
              <tr>
                <td><b>${J.esc(binding.phrase)}</b></td>
                <td><span class="badge ${meta.badge}">${J.esc(meta.label)}</span></td>
                <td class="mono ellipsis" style="max-width:320px" title="${J.esc(describe(binding.action))}">${J.esc(describe(binding.action))}</td>
                <td><span class="muted">${J.esc(SOURCES[binding.source] || binding.source)}</span></td>
                <td style="text-align:right" class="mono">${binding.use_count || 0}</td>
                <td><div class="actions">
                  <button class="btn icon sm" data-edit="${binding.id}" title="Редагувати">${J.icon("edit")}</button>
                  <button class="btn icon sm danger" data-delete="${binding.id}" title="Видалити">${J.icon("trash")}</button>
                </div></td>
              </tr>`;
          }).join("")}
        </tbody>
      </table>`;
  }

  function empty() {
    return `<div class="empty">${J.icon("link")}<strong>Бінди ще не створені</strong><span>Натисніть «Новий бінд» або скажіть: «Джарвіс, запам'ятай: коли я кажу "бойовий режим" — відкрий Discord і Dota»</span></div>`;
  }

  function typeOptions(selected, allowed) {
    return allowed.map((type) => `<option value="${type}" ${type === selected ? "selected" : ""}>${J.esc(ACTIONS[type].label)}</option>`).join("");
  }

  function stepRow(step) {
    return `
      <div class="macro-step">
        <select class="select" data-step-type>${typeOptions(step.type, STEP_TYPES)}</select>
        <input class="input" data-step-target value="${J.esc(step.target || "")}" placeholder="${J.esc(ACTIONS[step.type].hint)}">
        <button class="btn icon" data-step-remove title="Прибрати">${J.icon("x")}</button>
      </div>`;
  }

  function openEditor(binding) {
    const action = binding ? binding.action : { type: "open_app", target: "" };
    const allowed = action.type === "intent" ? [...Object.keys(ACTIONS)] : Object.keys(ACTIONS).filter((type) => type !== "intent");
    const dialog = J.modal({
      title: binding ? "Редагування бінду" : "Новий бінд",
      wide: true,
      body: `
        <div class="field"><label>Фраза — як ви її кажете</label><input class="input" id="be-phrase" value="${J.esc(binding ? binding.phrase : "")}" placeholder="відкрий дотку"></div>
        <div class="field"><label>Тип дії</label><select class="select" id="be-type">${typeOptions(action.type, allowed)}</select></div>
        <div id="be-dynamic"></div>`,
      footer: `<button class="btn ghost" data-cancel>Скасувати</button><button class="btn primary" data-save>${J.icon("check")}Зберегти</button>`,
    });
    const element = dialog.element;
    const typeSelect = element.querySelector("#be-type");
    const dynamic = element.querySelector("#be-dynamic");
    let steps = action.type === "macro" ? (action.steps || []).map((step) => ({ type: step.type, target: step.target })) : [{ type: "open_app", target: "" }];

    const drawSteps = () => {
      const list = dynamic.querySelector("#be-steps");
      list.innerHTML = steps.map(stepRow).join("");
      list.querySelectorAll(".macro-step").forEach((row, index) => {
        row.querySelector("[data-step-type]").onchange = (event) => {
          steps[index].type = event.target.value;
          drawSteps();
        };
        row.querySelector("[data-step-target]").oninput = (event) => {
          steps[index].target = event.target.value;
        };
        row.querySelector("[data-step-remove]").onclick = () => {
          steps.splice(index, 1);
          drawSteps();
        };
      });
    };

    const drawDynamic = () => {
      const type = typeSelect.value;
      const meta = ACTIONS[type];
      if (type === "macro") {
        dynamic.innerHTML = `<div class="field"><label>Кроки виконуються по черзі</label><div id="be-steps"></div><div><button class="btn sm" id="be-add-step">${J.icon("plus")}Додати крок</button></div></div>`;
        dynamic.querySelector("#be-add-step").onclick = () => {
          steps.push({ type: "open_app", target: "" });
          drawSteps();
        };
        drawSteps();
        return;
      }
      if (type === "intent") {
        dynamic.innerHTML = `<div class="field"><label>Інтент (вивчено автоматично після відповіді DeepSeek)</label><textarea class="textarea" readonly>${J.esc(JSON.stringify(action.intent || {}, null, 2))}</textarea></div>`;
        return;
      }
      const current = action.type === type ? action.target || "" : "";
      dynamic.innerHTML = `
        <div class="field"><label>Ціль</label>
          <div class="row"><input class="input grow" id="be-target" value="${J.esc(current)}" placeholder="${J.esc(meta.hint)}">
          ${meta.browse ? `<button class="btn" id="be-browse">${J.icon("folder")}Огляд</button>` : ""}</div>
        </div>`;
      const browse = dynamic.querySelector("#be-browse");
      if (browse) {
        browse.onclick = async () => {
          const result = await J.call(meta.browse === "folder" ? "browse_folder" : "browse_file");
          if (result && result.path) dynamic.querySelector("#be-target").value = result.path;
        };
      }
    };

    typeSelect.onchange = drawDynamic;
    drawDynamic();
    element.querySelector("[data-cancel]").onclick = () => dialog.close();
    element.querySelector("[data-save]").onclick = async () => {
      const phrase = element.querySelector("#be-phrase").value.trim();
      const type = typeSelect.value;
      let payload;
      if (type === "macro") {
        const cleaned = steps.filter((step) => step.target.trim());
        if (!cleaned.length) {
          J.toast("Макрос порожній", "Додайте хоча б один крок", "warn");
          return;
        }
        payload = { type, steps: cleaned.map((step) => ({ type: step.type, target: step.target.trim() })) };
      } else if (type === "intent") {
        payload = action;
      } else {
        const target = element.querySelector("#be-target").value.trim();
        if (!target) {
          J.toast("Вкажіть ціль", ACTIONS[type].hint, "warn");
          return;
        }
        payload = { type, target };
      }
      const result = await J.call("save_binding", binding ? binding.id : null, phrase, payload);
      if (result && result.ok) {
        J.toast("Бінд збережено", `«${phrase}»`, "success");
        dialog.close();
      }
    };
    setTimeout(() => element.querySelector("#be-phrase").focus(), 60);
  }

  J.on("BindingsListed", (data) => {
    J.state.bindings = data.bindings || [];
    J.changed("bindings");
    if (J.state.view === "bindings") render();
  });

  J.views.bindings = { title: "Бінди", subtitle: "Фраза → дія: програми, файли, макроси, гарячі клавіші", icon: "link", render, count: () => J.state.bindings.length };
})();
