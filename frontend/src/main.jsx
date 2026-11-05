import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { DEMO, setSignedIn } from "./api.js";
import { initTheme } from "./theme.js";
import "./styles.css";

initTheme();
const root = createRoot(document.getElementById("root"));

async function boot() {
  if (!DEMO) {
    try {
      const { initAuth } = await import("./auth.js");
      const user = await initAuth();
      if (user) setSignedIn(user);
    } catch (e) {
      root.render(<div className="empty" role="alert">Sign-in failed: {String(e.message || e)}. <a href="/">Try again</a></div>);
      return;
    }
  }
  root.render(<App />);
}
boot();
