import { defineConfig } from "astro/config";
import react from "@astrojs/react";

// Astro usa Vite por dentro: el proxy del API local se configura aquí, no en un
// `vite.config.ts` aparte.
export default defineConfig({
  integrations: [react()],
  server: { port: 5173 },
  vite: {
    server: {
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
  },
});
