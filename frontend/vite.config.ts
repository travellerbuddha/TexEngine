import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { resolve } from "node:path"
import { defineConfig } from "vite"

// Dev (`vite`): served at / on :5173, proxying /api to the Frappe bench.
// Build (`vite build`): emits into the Frappe app's public/ folder, which
// Frappe serves at /assets/kamra/frontend/. The served SPA mounts at /kamra
// (see the router basename in main.tsx and website_route_rules in hooks.py).
export default defineConfig(({ command }) => ({
  base: command === "build" ? "/assets/kamra/frontend/" : "/",
  plugins: [
    react(),
    tailwindcss(),
    {
      // dev only: /book/* is the guest booking bundle (production: kamra/www/book.py)
      name: "tex-booking-dev-fallback",
      configureServer(server) {
        server.middlewares.use((req, _res, next) => {
          if (req.url && /^\/book(\/|\?|$)/.test(req.url) && !/\.[a-z0-9]+(\?|$)/i.test(req.url)) req.url = "/booking.html"
          next()
        })
      },
    },
  ],
  build: {
    outDir: "../kamra/public/frontend",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      // admin SPA (/kamra, /kamra/tex) + guest booking engine (/book, ADR-012)
      input: {
        index: resolve(__dirname, "index.html"),
        booking: resolve(__dirname, "booking.html"),
      },
    },
  },
  server: {
    // Defaults preserved; override with env when the standard ports are taken
    // (e.g. KAMRA_DEV_PORT=5174 KAMRA_API_TARGET=http://localhost:8080
    // KAMRA_API_HOST=test.localhost).
    port: Number(process.env.KAMRA_DEV_PORT) || 5173,
    proxy: Object.fromEntries(
      // API calls and uploaded files come from the bench
      ["/api", "/files", "/private/files"].map((path) => [
        path,
        {
          target: process.env.KAMRA_API_TARGET || "http://localhost:8000",
          headers: { Host: process.env.KAMRA_API_HOST || "kamra.localhost" },
        },
      ]),
    ),
  },
}))
