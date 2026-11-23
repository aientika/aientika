// Medicion con Google Analytics 4 (propiedad del sitio). Si localStorage «analitica» vale «no», la visita no se mide.
// Ademas de las paginas vistas, cuenta cuando alguien reproduce un video de ejemplo (evento «video_play» con el nombre del archivo).
(function () {
  var ID = "G-XXXXXXXXXX", CLAVE = "analitica";

  function leer() { try { return localStorage.getItem(CLAVE); } catch (e) { return null; } }

  // Trafico interno: cada navegador se marca una vez abriendo cualquier pagina con ?interno=1 (y se desmarca con ?interno=0); sus visitas salen con
  // traffic_type=internal y el filtro de datos «Internal Traffic» de la propiedad las excluye de los informes.
  var marca = new URLSearchParams(location.search).get("interno");
  if (marca === "1") { try { localStorage.setItem("analitica_interno", "si"); } catch (e) { /* sin almacenamiento */ } }
  if (marca === "0") { try { localStorage.removeItem("analitica_interno"); } catch (e) { /* sin almacenamiento */ } }
  function interno() { try { return localStorage.getItem("analitica_interno") === "si"; } catch (e) { return false; } }

  function cargar() {
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag("js", new Date());
    var opciones = { anonymize_ip: true };
    if (interno()) opciones.traffic_type = "internal";
    window.gtag("config", ID, opciones);
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" + ID;
    document.head.appendChild(s);
    document.querySelectorAll("video.demo").forEach(function (v) {
      v.addEventListener("play", function () {
        var nombre = (v.getAttribute("src") || "").split("/").pop();
        window.gtag("event", "video_play", { video: nombre, pagina: location.pathname });
      }, { once: true });
    });
  }

  // Conteo propio de las visitas que llegan desde Claude o ChatGPT: una imagen de 1 pixel al conector con solo el origen y la
  // pagina, sin cookies ni identificadores. Las visitas internas (?interno=1) no se cuentan.
  // Referencia de la visita: el enlace de una respuesta puede traer «r», cifrada, que une la visita con la búsqueda que la
  // originó. Se manda solo al conector y se BORRA de la barra de direcciones antes de que cargue Analytics, para que Google no la reciba.
  (function () {
    var params = new URLSearchParams(location.search);
    var r = params.get("r") || "";
    if (params.has("r")) {
      params.delete("r");
      var limpia = location.pathname + (params.toString() ? "?" + params.toString() : "") + location.hash;
      try { history.replaceState(null, "", limpia); } catch (e) { /* sin historial: se queda en la barra */ }
    }
    var utm = (params.get("utm_source") || "").toLowerCase();
    var ref = (document.referrer || "").toLowerCase();
    var origen = utm === "claude" || ref.indexOf("claude.ai") >= 0 ? "claude"
      : utm === "chatgpt" || ref.indexOf("chatgpt.com") >= 0 || ref.indexOf("openai.com") >= 0 ? "chatgpt" : "";
    var interno = false;
    try { interno = localStorage.getItem("analitica_interno") === "si"; } catch (e) { /* sin almacenamiento */ }
    if (!origen || interno) return;
    new Image().src = "/visita?o=" + origen +
      "&p=" + encodeURIComponent(location.pathname) + (/^[A-Za-z0-9_-]{40,160}$/.test(r) ? "&r=" + r : "");
  })();

  if (leer() !== "no") cargar();
})();
