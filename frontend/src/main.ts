import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow/700.css";
import "@fortawesome/fontawesome-free/css/all.min.css";
import "./bootstrap.scss"; // Bootstrap zuerst, damit app.css das letzte Wort behält
import "./app.css";
import * as bootstrap from "bootstrap"; // Bootstrap-Verhalten (Dropdown, Tooltip, Collapse) mit Popper
import { mount } from "svelte";
import App from "./App.svelte";

// Global bereitstellen: data-bs-Attribute und programmatischer Zugriff (window.bootstrap).
(globalThis as unknown as { bootstrap: typeof bootstrap }).bootstrap = bootstrap;

const app = mount(App, { target: document.getElementById("app")! });

export default app;
