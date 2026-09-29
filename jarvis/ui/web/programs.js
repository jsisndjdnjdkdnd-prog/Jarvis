(function () {
  const J = window.J;
  const KINDS = {
    steam: ["Steam", "#66c0f4"],
    epic: ["Epic", "#e7e7e7"],
    uwp: ["Store", "#7c5cff"],
    lnk: ["Пуск", "#00e5ff"],
    exe: ["EXE", "#ffb547"],
    system: ["Windows", "#2ef2a0"],
    user: ["Моя", "#ff7ab6"],
    url: ["URL", "#a78bfa"],
  };
  const LIMIT = 400;
  let query = "";
  let kind = "all";

  function matches(program) {
    if (kind !== "all" && program.kind !== kind) return false;
    if (!query) return true;
    return program.normalized.includes(query) || (program.aliases || []).some((alias) => alias.includes(query));
  }

  function render() {
    const root = document.getElementById("view-programs");
    const all = J.state.programs;
    const items = all.filter(matches);
    const kinds = ["all", ...Object.keys(KINDS).filter((key) => all.some((program) => program.kind === key))];
    root.innerHTML = `
      <div class="toolbar">
        <div class="search">${J.icon("search")}<input class="input" id="program-search" placeholder="хром, дота, telegram…" value="${J.esc(query)}"></div>
        <div class="segmented">${kinds.map((key) => `<button class="${key === kind ? "active" : ""}" data-kind="${key}">${key === "all" ? "Усі" : KINDS[key][0]}</button>`).join("")}</div>
        <span class="muted">${items.length} з ${all.length}</span>
        <div class="grow"></div>
        <button class="btn" data-rescan ${J.state.scanning ? "disabled" : ""}>${J.state.scanning ? '<span class="spinner"></span>Сканую…' : `${J.icon("refresh")}Оновити індекс`}</button>
        <button class="btn primary" data-add-program>${J.icon("plus")}Додати програму</button>
      </div>
      <div class="scroll" style="flex:1">
        ${items.length ? table(items.slice(0, LIMIT)) : `<div class="empty">${J.icon("grid")}<strong>Нічого не знайдено</strong><span>Оновіть індекс або додайте програму вручну</span></div>`}
        ${items.length > LIMIT ? `<div class="muted" style="text-align:center;padding:12px">Показано ${LIMIT} — уточніть пошук</div>` : ""}
      </div>`;
    const search = root.querySelector("#program-search");
    search.addEventListener("input", () => {
      query = search.value.trim().toLowerCase();
      render();
      const again = document.getElementById("program-search");
      again.focus();
      again.setSelectionRange(again.value.length, again.value.length);
    });
    root.querySelectorAll("[data-kind]").forEach((button) => {
      button.onclick = () => {
        kind = button.dataset.kind;
        render();
      };
    });
    root.querySelector("[data-rescan]").onclick = () => {
      J.state.scanning = true;
      render();
      J.call("rescan_programs");
    };
    root.querySelector("[data-add-program]").onclick = addProgram;
    root.querySelectorAll("[data-program-delete]").forEach((button) => {
      button.onclick = async () => {
        const program = all.find((item) => String(item.id) === button.dataset.programDelete);
        if (program && (await J.confirm("Прибрати з індексу?", `«${program.name}» зникне зі списку до наступного сканування.`, "Прибрати", true))) {
          J.call("delete_program", program.id);
        }
      };
    });
  }

  function table(items) {
    return `
      <table class="table">
        <thead><tr><th>Програма</th><th>Аліаси</th><th>Процеси</th><th>Джерело</th><th></th></tr></thead>
        <tbody>${items.map((program) => {
          const [label, color] = KINDS[program.kind] || [program.kind, "#8199ad"];
          return `
            <tr>
              <td><div class="row"><div class="avatar-letter" style="background:${color}">${J.esc((program.name || "?").trim().charAt(0).toUpperCase())}</div><div style="min-width:0"><b class="ellipsis" style="display:block;max-width:280px">${J.esc(program.name)}</b><span class="badge" style="margin-top:4px;color:${color}">${J.esc(label)}</span></div></div></td>
              <td><div class="ellipsis muted" style="max-width:260px" title="${J.esc((program.aliases || []).join(", "))}">${J.esc((program.aliases || []).slice(0, 5).join(", "))}</div></td>
              <td class="mono ellipsis muted" style="max-width:180px">${J.esc((program.process_names || []).slice(0, 3).join(", ") || "—")}</td>
              <td class="muted">${J.esc(program.source)}</td>
              <td><div class="actions"><button class="btn icon sm danger" data-program-delete="${program.id}" title="Прибрати">${J.icon("trash")}</button></div></td>
            </tr>`;
        }).join("")}</tbody>
      </table>`;
  }

  function addProgram() {
    const dialog = J.modal({
      title: "Додати програму",
      body: `<div class="field"><label>Як ви називаєте її голосом</label><input class="input" id="ap-name" placeholder="моя гра"></div><p class="muted" style="margin:0">Після натискання «Обрати файл» вкажіть .exe, .lnk або .url</p>`,
      footer: `<button class="btn ghost" data-cancel>Скасувати</button><button class="btn primary" data-pick>${J.icon("folder")}Обрати файл</button>`,
    });
    dialog.element.querySelector("[data-cancel]").onclick = () => dialog.close();
    dialog.element.querySelector("[data-pick]").onclick = async () => {
      const name = dialog.element.querySelector("#ap-name").value.trim();
      const result = await J.call("add_program", name);
      if (result && result.ok && !result.cancelled) {
        J.toast("Програму додано", name || "Готово", "success");
        dialog.close();
      }
    };
  }

  function askLocation(name) {
    let answered = false;
    const dialog = J.modal({
      title: "Програму не знайдено",
      body: `<div class="empty" style="padding:16px 0 4px">${J.icon("search")}<strong>«${J.esc(name)}»</strong><span>Не знайшов такої програми. Покажете, де вона? Я запам'ятаю назву.</span></div>`,
      footer: `<button class="btn ghost" data-skip>Пропустити</button><button class="btn primary" data-locate>${J.icon("folder")}Вказати файл</button>`,
      onClose: () => {
        if (!answered) J.call("skip_program", name);
      },
    });
    dialog.element.querySelector("[data-skip]").onclick = () => dialog.close();
    dialog.element.querySelector("[data-locate]").onclick = async () => {
      answered = true;
      dialog.close();
      await J.call("locate_program", name);
    };
  }

  J.on("ProgramsListed", (data) => {
    J.state.programs = data.programs || [];
    J.state.scanning = false;
    J.changed("programs");
    if (J.state.view === "programs") render();
  });

  J.on("ProgramsIndexed", (data) => {
    J.state.scanning = false;
    J.toast("Індекс оновлено", `Знайдено програм: ${data.count}`, "success");
  });

  J.on("ProgramLocationRequested", (data) => askLocation(data.program_name));

  J.views.programs = { title: "Програми", subtitle: "Меню «Пуск», Program Files, реєстр, Steam, Epic, Microsoft Store", icon: "grid", render, count: () => J.state.programs.length };
})();
