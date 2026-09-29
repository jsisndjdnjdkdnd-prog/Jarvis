(function () {
  const J = window.J;

  function render() {
    const root = document.getElementById("view-reminders");
    const items = J.state.reminders;
    root.innerHTML = `
      <div class="toolbar">
        <span class="muted">Додаються голосом: «Джарвіс, нагадай завтра о 9 подзвонити мамі» — переживають перезапуск.</span>
        <div class="grow"></div>
        <button class="btn" data-refresh>${J.icon("refresh")}Оновити</button>
      </div>
      <div class="scroll" style="flex:1">
        ${items.length ? items.map(card).join("") : `<div class="empty">${J.icon("bell")}<strong>Нагадувань немає</strong><span>Спробуйте: «нагадай через 20 хвилин вимкнути духовку»</span></div>`}
      </div>`;
    root.querySelector("[data-refresh]").onclick = () => J.call("bootstrap");
    root.querySelectorAll("[data-cancel-reminder]").forEach((button) => {
      button.onclick = () => J.call("cancel_reminder", Number(button.dataset.cancelReminder));
    });
  }

  function card(reminder) {
    return `
      <div class="card reminder">
        <div class="time"><b>${J.esc(J.formatTime(reminder.due_at))}</b><span>${J.esc(J.formatDay(reminder.due_at))}</span></div>
        <div class="msg-text">${J.esc(reminder.message)}<div class="muted" style="font-size:12px;margin-top:4px">${J.icon("clock", 'width="13" height="13" style="vertical-align:-2px"')} ${J.esc(J.relative(reminder.due_at))}</div></div>
        <button class="btn sm danger" data-cancel-reminder="${reminder.id}">${J.icon("x")}Скасувати</button>
      </div>`;
  }

  J.on("RemindersListed", (data) => {
    J.state.reminders = data.reminders || [];
    J.changed("reminders");
    if (J.state.view === "reminders") render();
  });

  J.on("ReminderDue", (data) => J.toast("Нагадування", data.reminder.message, "warn"));
  J.on("TimerFinished", (data) => J.toast("Таймер", `На ${data.label} — завершено`, "warn"));

  J.views.reminders = { title: "Нагадування", subtitle: "Toast-сповіщення Windows і голосом", icon: "bell", render, count: () => J.state.reminders.length };
})();
