import React from "react";
import ReactDOM from "react-dom/client";
import faviconUrl from "../logo/nova_32x32.png";

import { App } from "./app/App";
import "./app/styles.css";

const favicon = document.querySelector<HTMLLinkElement>("#app-favicon");
if (favicon) {
  favicon.href = `${faviconUrl}?v=3`;
  const faviconImage = new Image();
  faviconImage.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = 32;
    canvas.height = 32;
    const context = canvas.getContext("2d");
    if (!context) return;
    const scale = 1.45;
    const offset = (canvas.width - canvas.width * scale) / 2;
    context.drawImage(faviconImage, offset, offset, canvas.width * scale, canvas.height * scale);
    favicon.href = canvas.toDataURL("image/png");
  };
  faviconImage.src = faviconUrl;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
