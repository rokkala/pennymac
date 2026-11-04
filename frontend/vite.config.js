import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// `npm run build`       -> dist/ served by the API (or S3 + CloudFront), talks to /api
// `npm run build:demo`  -> dist-demo/index.html, one self-contained file with an in-browser mock API
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === "demo" ? [viteSingleFile()] : [])],
  server: {
    proxy: { "/api": "http://localhost:8000" },
    fs: { allow: [".."] }, // Maintenance ?raw: aws/glue|stepfunctions|lambdas + backend/lbp
  },
  build: { chunkSizeWarningLimit: 4000 },
}));
