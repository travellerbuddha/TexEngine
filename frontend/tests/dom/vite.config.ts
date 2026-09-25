// Dev server for the browser checks of the TEX design-system overlays (tests/dom): the real
// components and styles (Tailwind scans the whole frontend), no bench and no API proxy.
// Started by tests/dom/playwright.config.ts; open /tests/dom/overlays.html, /tests/dom/keyboard.html or
// /tests/dom/history.html for a manual check.
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { fileURLToPath } from "node:url"
import { defineConfig } from "vite"

export default defineConfig({
  root: fileURLToPath(new URL("../..", import.meta.url)),
  define: { __TEX_BUILD_COMMIT__: JSON.stringify("") },
  plugins: [react(), tailwindcss()],
  logLevel: "warn",
  server: {
    host: "127.0.0.1",
    port: Number(process.env.TEX_DOM_PORT) || 5391,
    strictPort: true,
  },
})
