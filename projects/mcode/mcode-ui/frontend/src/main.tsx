import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

// Restore saved theme
try {
  const saved = localStorage.getItem("mcode-theme");
  if (saved === "dark") document.documentElement.classList.add("theme-dark");
} catch { /* ignore */ }

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
