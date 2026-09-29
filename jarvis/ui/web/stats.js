(function () {
  const J = window.J;
  const PIPELINE = [
    ["exact_binding", "Точний бінд", "violet"],
    ["fuzzy_binding", "Нечіткий бінд", "violet"],
    ["rules", "Правила", "cyan"],
    ["deepseek_cache", "Кеш DeepSeek", "green"],
    ["deepseek", "DeepSeek", "amber"],
  ];

  function kpi(label, value, hint, glow) {
    return `<div class="card kpi" style="--glow:${glow}"><div class="label">${J.esc(label)}</div><div class="value">${J.esc(value)}</div><div class="hint">${J.esc(hint)}</div></div>`;
  }

  function render() {
    const root = document.getElementById("view-stats");
    const stats = J.state.stats;
    if (!stats) {
      root.innerHTML = `<div class="empty"><span class="spinner"></span><span>Збираю статистику…</span></div>`;
      return;
    }
    const counts = stats.stage_counts || {};
    const handled = PIPELINE.reduce((sum, [key]) => sum + (counts[key] || 0), 0);
    const remote = counts.deepseek || 0;
    const offline = handled ? J.percent(handled - remote, handled) : 100;
    const maxCount = Math.max(1, ...PIPELINE.map(([key]) => counts[key] || 0));
    const purposes = Object.entries(stats.by_purpose || {});
    root.innerHTML = `
      <div class="scroll" style="flex:1">
        <div class="kpis">
          ${kpi("Звернень до DeepSeek", stats.total_calls, `сьогодні: ${stats.calls_today}`, "rgba(255,181,71,.25)")}
          ${kpi("Оброблено офлайн", `${offline}%`, `${handled - remote} з ${handled} команд без мережі`, "rgba(46,242,160,.25)")}
          ${kpi("Відповідей з кешу", stats.cache_hits, "повторні фрази без запиту", "rgba(0,229,255,.25)")}
          ${kpi("Вивчено фраз", stats.learned_phrases, "самонавчання після DeepSeek", "rgba(124,92,255,.3)")}
        </div>
        <div class="card" style="margin-bottom:18px">
          <div class="card-header">${J.icon("bolt", 'width="18" height="18" style="color:var(--accent)"')}<h3>Конвеєр обробки команди</h3><span class="muted" style="font-size:12px">DeepSeek — лише останній крок</span></div>
          <div class="card-body"><div class="pipeline">
            ${PIPELINE.map(([key, label, color], index) => `
              <div class="stage-step">
                <div class="n">КРОК ${index + 1}</div>
                <div class="t">${J.esc(label)}</div>
                <div class="row" style="justify-content:space-between;margin-bottom:8px"><span class="badge ${color}">${counts[key] || 0}</span><span class="muted mono">${J.percent(counts[key] || 0, handled)}%</span></div>
                <div class="bar"><i style="width:${((counts[key] || 0) / maxCount) * 100}%"></i></div>
              </div>`).join("")}
          </div></div>
        </div>
        <div class="row" style="align-items:stretch;gap:18px">
          <div class="card grow">
            <div class="card-header">${J.icon("cloud", 'width="18" height="18" style="color:var(--amber)"')}<h3>Запити до API</h3></div>
            <div class="card-body">
              ${[
                ["Успішних", stats.successful_calls, "var(--green)"],
                ["З помилкою", stats.failed_calls, "var(--red)"],
                ["Токенів запиту", stats.prompt_tokens, "var(--accent)"],
                ["Токенів відповіді", stats.completion_tokens, "var(--violet)"],
                ["Середня затримка", `${Math.round(stats.average_latency_ms)} мс`, "var(--amber)"],
              ].map(([label, value, color]) => `<div class="setting"><div class="text"><b>${J.esc(label)}</b></div><b class="mono" style="color:${color}">${J.esc(value)}</b></div>`).join("")}
            </div>
          </div>
          <div class="card grow">
            <div class="card-header">${J.icon("brain", 'width="18" height="18" style="color:var(--violet)"')}<h3>За призначенням</h3></div>
            <div class="card-body">
              ${purposes.length ? purposes.map(([purpose, count]) => `
                <div style="margin-bottom:14px"><div class="row" style="justify-content:space-between;margin-bottom:6px"><span>${J.esc({ intent: "Розбір команд", music: "Підбір музики" }[purpose] || purpose)}</span><span class="mono muted">${count}</span></div>
                <div class="bar"><i style="width:${J.percent(count, stats.total_calls)}%"></i></div></div>`).join("") : '<div class="muted">Ще не було жодного запиту — усе обробляється локально.</div>'}
            </div>
          </div>
        </div>
      </div>`;
  }

  J.on("DeepSeekStatsChanged", (data) => {
    J.state.stats = data.stats;
    J.changed("stats");
    if (J.state.view === "stats") render();
  });

  J.views.stats = { title: "Статистика DeepSeek", subtitle: "Мінімум мережі: локальні бінди, правила й кеш", icon: "chart", render };
})();
