/** Persist light/dark; maps to documentElement data-theme. */
const KEY = "lbp.theme";

export function getTheme() {
  const v = localStorage.getItem(KEY);
  return v === "light" || v === "dark" ? v : "light";
}

export function applyTheme(theme) {
  const t = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", t);
  return t;
}

export function setTheme(theme) {
  const t = applyTheme(theme);
  localStorage.setItem(KEY, t);
  return t;
}

export function initTheme() {
  return applyTheme(getTheme());
}
