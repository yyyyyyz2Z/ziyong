import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  build: {
    outDir: "dist/client",
  },
  optimizeDeps: {
    include: ["react", "react-dom/client", "onnxruntime-web/wasm"],
  },
  resolve: {alias: {
    "#pianocv-session": fileURLToPath(new URL("keynetsession.ts", import.meta.resolve("pianocv"))),
    "#pianocv-core": fileURLToPath(new URL("keycore.ts", import.meta.resolve("pianocv"))),
  }},
  worker: {format: "es"},
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    warmup: {
      clientFiles: ["./src/main.jsx"],
    },
  },
  plugins: [react()],
});
