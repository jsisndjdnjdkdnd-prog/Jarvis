(function () {
  const SEGMENTS = 12;
  let counter = 0;

  function segmentPath(index) {
    const center = 100;
    const inner = 40;
    const outer = 52;
    const span = (Math.PI * 2) / SEGMENTS;
    const gap = 0.07;
    const start = index * span + gap - Math.PI / 2;
    const end = (index + 1) * span - gap - Math.PI / 2;
    const point = (radius, angle) => `${(center + radius * Math.cos(angle)).toFixed(2)} ${(center + radius * Math.sin(angle)).toFixed(2)}`;
    return `M ${point(inner, start)} L ${point(outer, start)} A ${outer} ${outer} 0 0 1 ${point(outer, end)} L ${point(inner, end)} A ${inner} ${inner} 0 0 0 ${point(inner, start)} Z`;
  }

  function markup(id) {
    const segments = Array.from({ length: SEGMENTS }, (_, index) => `<path class="r-seg" data-seg="${index}" d="${segmentPath(index)}"/>`).join("");
    return `
      <svg class="reactor" viewBox="0 0 200 200" aria-hidden="true">
        <defs>
          <radialGradient id="r-halo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" style="stop-color:var(--state);stop-opacity:0.35"/>
            <stop offset="55%" style="stop-color:var(--state);stop-opacity:0.08"/>
            <stop offset="100%" style="stop-color:var(--state);stop-opacity:0"/>
          </radialGradient>
          <radialGradient id="r-core" cx="50%" cy="45%" r="55%">
            <stop offset="0%" stop-color="#ffffff"/>
            <stop offset="35%" stop-color="#d9fbff"/>
            <stop offset="70%" style="stop-color:var(--state)"/>
            <stop offset="100%" style="stop-color:var(--state);stop-opacity:0.2"/>
          </radialGradient>
        </defs>
        <circle class="r-halo" cx="100" cy="100" r="100"/>
        <circle class="r-track" cx="100" cy="100" r="92"/>
        <circle class="r-ring r1" cx="100" cy="100" r="86"/>
        <circle class="r-ring r2" cx="100" cy="100" r="75"/>
        <circle class="r-ring r3" cx="100" cy="100" r="63"/>
        <g class="r-segments" data-reactor-id="${id}">${segments}</g>
        <circle class="r-core" cx="100" cy="100" r="30"/>
        <circle class="r-core-ring" cx="100" cy="100" r="21"/>
        <circle class="r-core-dot" cx="100" cy="100" r="9"/>
      </svg>`;
  }

  const instances = [];
  let phase = 0;

  function tick() {
    phase += 1;
    const state = document.body.dataset.state || "idle";
    const level = Number(getComputedStyle(document.body).getPropertyValue("--level")) || 0;
    for (const group of instances) {
      const segments = group.querySelectorAll(".r-seg");
      const active = state === "thinking" || state === "executing";
      const lit = state === "listening" ? Math.round(level * SEGMENTS * 1.4) : 0;
      segments.forEach((segment, index) => {
        let on = index < lit;
        if (active) on = (index + Math.floor(phase / 3)) % 4 === 0;
        if (state === "speaking") on = (index + Math.floor(phase / 4)) % 2 === 0;
        if (state === "idle") on = (index + Math.floor(phase / 12)) % SEGMENTS === 0;
        segment.classList.toggle("lit", on);
      });
    }
    requestAnimationFrame(() => setTimeout(tick, 60));
  }

  window.JReactor = {
    mount(root) {
      (root || document).querySelectorAll("[data-reactor]").forEach((node) => {
        counter += 1;
        node.outerHTML = markup(counter);
      });
      document.querySelectorAll(".r-segments").forEach((group) => {
        if (!instances.includes(group)) instances.push(group);
      });
    },
    start() {
      tick();
    },
  };
})();
