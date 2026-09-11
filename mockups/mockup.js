// Kleine Helfer für die Mockups: Thema umschalten, Hilfefenster zeigen, Regler-Werte
// anzeigen. Reines Anschauungs-Verhalten, kein App-Code.
document.addEventListener("DOMContentLoaded", () => {
  const html = document.documentElement;
  const gespeichert = localStorage.getItem("mk-thema");
  if (gespeichert) html.setAttribute("data-bs-theme", gespeichert);

  document.querySelectorAll("[data-thema]").forEach((k) => {
    k.addEventListener("click", () => {
      const neu = html.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      html.setAttribute("data-bs-theme", neu);
      localStorage.setItem("mk-thema", neu);
    });
  });

  const hilfe = document.querySelector(".m-hilfe");
  document.querySelectorAll("[data-hilfe]").forEach((k) => {
    k.addEventListener("click", () => {
      if (!hilfe) return;
      hilfe.hidden = !hilfe.hidden;
    });
  });
  document.querySelectorAll(".m-hilfe [data-schliessen]").forEach((k) => {
    k.addEventListener("click", () => {
      if (hilfe) hilfe.hidden = true;
    });
  });

  // Hilfefenster verschiebbar
  if (hilfe) {
    const kopf = hilfe.querySelector(".m-hilfe-kopf");
    let start = null;
    kopf?.addEventListener("mousedown", (e) => {
      start = { x: e.clientX - hilfe.offsetLeft, y: e.clientY - hilfe.offsetTop };
      e.preventDefault();
    });
    window.addEventListener("mousemove", (e) => {
      if (!start) return;
      hilfe.style.left = Math.max(0, e.clientX - start.x) + "px";
      hilfe.style.top = Math.max(0, e.clientY - start.y) + "px";
      hilfe.style.right = "auto";
      hilfe.style.bottom = "auto";
    });
    window.addEventListener("mouseup", () => (start = null));
  }

  // Regler zeigen ihren Wert
  document.querySelectorAll(".m-regler").forEach((r) => {
    const eingabe = r.querySelector("input[type=range]");
    const wert = r.querySelector(".wert");
    if (!eingabe || !wert) return;
    const zeige = () => {
      const einheit = eingabe.dataset.einheit || "";
      wert.textContent = eingabe.value + (einheit ? " " + einheit : "");
    };
    eingabe.addEventListener("input", zeige);
    zeige();
  });

  // Fundstellen abwählen
  document.querySelectorAll(".m-stelle [data-abwaehlen]").forEach((k) => {
    k.addEventListener("click", () => k.closest(".m-stelle")?.classList.toggle("abgewaehlt"));
  });
});
