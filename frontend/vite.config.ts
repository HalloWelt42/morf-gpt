import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Version aus der einzigen Wahrheit (../version.json) - nirgends hart geschrieben.
const versionsDatei = fileURLToPath(new URL("../version.json", import.meta.url));
const version = JSON.parse(readFileSync(versionsDatei, "utf8")) as { version: string; voll: string };

const backendPort = process.env.MORF_BACKEND_PORT ?? "8460";
const frontendPort = Number(process.env.MORF_FRONTEND_PORT ?? "5460");

export default defineConfig({
  plugins: [svelte()],
  define: {
    __APP_VERSION__: JSON.stringify(version.version),
    __APP_VERSION_VOLL__: JSON.stringify(version.voll),
  },
  build: { outDir: "dist", emptyOutDir: true },
  css: {
    preprocessorOptions: {
      // Bootstrap nutzt noch @import und ältere Sass-Funktionen; deren
      // Hinweise sind Fremdcode und werden hier unterdrückt.
      scss: {
        quietDeps: true,
        silenceDeprecations: ["import", "mixed-decls", "color-functions", "global-builtin"],
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: frontendPort,
    strictPort: true,
    proxy: {
      "/api": { target: `http://127.0.0.1:${backendPort}`, changeOrigin: false },
    },
  },
});
