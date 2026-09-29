(function () {
  const J = window.J;
  const requestId = document.body.dataset.request;
  let start = null;
  let finished = false;

  function box(event) {
    const left = Math.min(start.x, event.clientX);
    const top = Math.min(start.y, event.clientY);
    return { left, top, width: Math.abs(event.clientX - start.x), height: Math.abs(event.clientY - start.y) };
  }

  function finish(fraction) {
    if (finished) return;
    finished = true;
    J.call("region_selected", requestId, fraction);
  }

  document.addEventListener("mousedown", (event) => {
    if (event.button !== 0) return;
    start = { x: event.clientX, y: event.clientY };
    document.body.classList.add("selecting");
  });

  document.addEventListener("mousemove", (event) => {
    if (!start) return;
    const rect = box(event);
    const node = document.getElementById("selection");
    node.style.display = "block";
    node.style.left = `${rect.left}px`;
    node.style.top = `${rect.top}px`;
    node.style.width = `${rect.width}px`;
    node.style.height = `${rect.height}px`;
    const ratio = window.devicePixelRatio || 1;
    document.getElementById("size").textContent = `${Math.round(rect.width * ratio)} × ${Math.round(rect.height * ratio)}`;
  });

  document.addEventListener("mouseup", (event) => {
    if (!start) return;
    const rect = box(event);
    start = null;
    if (rect.width < 4 || rect.height < 4) {
      document.body.classList.remove("selecting");
      document.getElementById("selection").style.display = "none";
      return;
    }
    const width = window.innerWidth;
    const height = window.innerHeight;
    finish([rect.left / width, rect.top / height, (rect.left + rect.width) / width, (rect.top + rect.height) / height]);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") finish(null);
    if (event.key === "Enter") finish([0, 0, 1, 1]);
  });
})();
