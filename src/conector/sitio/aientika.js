// Ventanas de instalación y de ejemplos, y el botón Copiar.
    // Dirección del conector. «Pedir acceso» va al formulario de Google.
    var DIRECCION = "https://aientika.ai/mcp";  // dirección corta; la anterior sigue sirviendo a quien ya la instaló
    var modal = document.getElementById("modal");
    document.getElementById("direccion").textContent = DIRECCION;
    var ejemplos = document.getElementById("ejemplos");
    // Al cerrar una ventana se pausan sus videos (si no, el sonido o la descarga siguen detrás).
    function pausar(m) { m.querySelectorAll("video").forEach(function (v) { v.pause(); }); }
    function mostrar(m, si) { m.classList.toggle("open", si); m.setAttribute("aria-hidden", String(!si)); if (!si) pausar(m); }
    function abrir(si) { mostrar(modal, si); }
    document.getElementById("ver-ejemplos").addEventListener("click", function () { mostrar(ejemplos, true); });
    document.querySelectorAll("[data-ejemplo]").forEach(function (b) {
      b.addEventListener("click", function () {
        var cual = b.getAttribute("data-ejemplo");
        document.querySelectorAll("[data-ejemplo]").forEach(function (o) { o.setAttribute("aria-pressed", String(o === b)); });
        document.querySelectorAll("[data-video]").forEach(function (o) { o.hidden = o.getAttribute("data-video") !== cual; });
        pausar(ejemplos);
      });
    });
    ejemplos.addEventListener("click", function (e) { if (e.target === ejemplos || e.target.classList.contains("cerrar")) mostrar(ejemplos, false); });
    var asistente = "Claude";
    document.querySelectorAll("[data-asistente]").forEach(function (b) {
      b.addEventListener("click", function () {
        var cual = b.getAttribute("data-asistente");
        asistente = cual === "chatgpt" ? "ChatGPT" : "Claude";
        document.getElementById("mt").textContent = "Instalar Aiéntika en " + asistente;
        document.querySelectorAll("[data-pasos]").forEach(function (o) { o.hidden = o.getAttribute("data-pasos") !== cual; });
        pausar(modal);
        document.getElementById("estado").textContent = "";
        abrir(true);
      });
    });
    modal.addEventListener("click", function (e) { if (e.target === modal || e.target.classList.contains("cerrar")) abrir(false); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { abrir(false); mostrar(ejemplos, false); } });
    document.getElementById("copiar").addEventListener("click", function () {
      var estado = document.getElementById("estado");
      function manual() {
        var r = document.createRange(); r.selectNodeContents(document.getElementById("direccion"));
        var s = getSelection(); s.removeAllRanges(); s.addRange(r); estado.textContent = "Seleccionada: copiala con Ctrl+C";
      }
      try { navigator.clipboard.writeText(DIRECCION).then(function () { estado.textContent = "Copiada. Pegala en " + asistente + "."; }, manual); }
      catch (e) { manual(); }
    });
