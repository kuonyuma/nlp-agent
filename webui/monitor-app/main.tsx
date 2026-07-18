import React from "react";
import ReactDOM from "react-dom/client";
import { MonitorApp } from "../src/monitor/MonitorApp";
import "../src/monitor/monitor.css";

ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><MonitorApp /></React.StrictMode>);
