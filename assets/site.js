// Botões de copiar, menu em telas pequenas e seção ativa no menu (de OSMnx Routing & Isochrones).
(function () {
  document.querySelectorAll("pre").forEach(function (pre) {
    var b = document.createElement("button");
    b.className = "copy";
    b.type = "button";
    b.textContent = document.documentElement.dataset.copy || "Copy";
    b.addEventListener("click", function () {
      var text = pre.querySelector("code").innerText;
      navigator.clipboard.writeText(text).then(function () {
        var old = b.textContent;
        b.textContent = "✓";
        setTimeout(function () { b.textContent = old; }, 1400);
      });
    });
    pre.appendChild(b);
  });

  document.querySelectorAll(".lang a").forEach(function (a) {
    a.addEventListener("click", function () {
      try { localStorage.setItem("topodata-doc-lang", a.dataset.lang); } catch (e) { /* private mode */ }
    });
  });

  // Menu button (small screens): opens the section list under the top bar
  var btn = document.querySelector(".menu-btn");
  var panel = document.getElementById("mobile-nav");
  function setMenu(open) {
    if (!btn || !panel) return;
    panel.classList.toggle("hidden", !open);
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (btn && panel) {
    btn.addEventListener("click", function () { setMenu(panel.classList.contains("hidden")); });
    panel.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () { setMenu(false); });
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") setMenu(false); });
    window.matchMedia("(min-width: 1280px)").addEventListener("change", function () { setMenu(false); });
  }

  var links = Array.prototype.slice.call(document.querySelectorAll(".topnav a"));
  if (!("IntersectionObserver" in window) || !links.length) return;
  var byId = {};
  links.forEach(function (a) {
    var id = a.getAttribute("href").slice(1);
    (byId[id] = byId[id] || []).push(a);
  });
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting && byId[e.target.id]) {
        links.forEach(function (a) { a.classList.remove("active"); });
        byId[e.target.id].forEach(function (a) { a.classList.add("active"); });
      }
    });
  }, { rootMargin: "-40% 0px -55% 0px" });
  document.querySelectorAll("section[id]").forEach(function (s) { observer.observe(s); });
})();
