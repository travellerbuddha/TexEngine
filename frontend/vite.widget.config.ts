import { defineConfig } from "vite"

// Embeddable widget (ADR-012): one self-contained ES module, no React, served at
// /assets/kamra/tex/tex-widget.js and loaded by hotel websites.
export default defineConfig({
  publicDir: false,
  build: {
    outDir: "../kamra/public/tex",
    emptyOutDir: true,
    sourcemap: false,
    lib: {
      entry: "src/widget/index.ts",
      formats: ["es"],
      fileName: () => "tex-widget.js",
    },
  },
})
