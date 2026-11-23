// Interruptor claro/oscuro de las paginas internas: arranca siempre en oscuro, igual que el inicio; solo cambia esta visita.
const root = document.documentElement, btn = document.getElementById("theme");
function setTheme(light) {
  root.classList.toggle("light", light);
  btn.setAttribute("aria-checked", String(!light));
  btn.setAttribute("aria-label", light ? "Cambiar a modo oscuro" : "Cambiar a modo claro");
}
setTheme(false);
btn.addEventListener("click", () => setTheme(!root.classList.contains("light")));
