import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

function vendorChunk(id: string): string | undefined {
  if (!id.includes("node_modules")) return undefined;

  if (id.includes("/react/") || id.includes("/react-dom/") || id.includes("react-router")) {
    return "vendor-react";
  }
  if (id.includes("@radix-ui") || id.includes("lucide-react") || id.includes("sonner")) {
    return "vendor-ui";
  }
  if (id.includes("reactflow") || id.includes("dagre")) {
    return "vendor-flow";
  }
  if (
    id.includes("@react-sigma") ||
    id.includes("sigma") ||
    id.includes("graphology") ||
    id.includes("react-force-graph")
  ) {
    return "vendor-graph";
  }
  if (id.includes("react-markdown") || id.includes("remark") || id.includes("micromark")) {
    return "vendor-markdown";
  }
  if (id.includes("recharts")) {
    return "vendor-recharts";
  }
  if (id.includes("/d3-")) {
    return "vendor-d3";
  }
  if (id.includes("framer-motion")) {
    return "vendor-motion";
  }
  if (id.includes("posthog-js")) {
    return "vendor-analytics";
  }

  return undefined;
}

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    host: "::",
    port: 8080,
    allowedHosts: ["app.dev.contextd.local", "localhost", "app.contextd.local"],
  },
  plugins: [
    react(),
  ].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
    extensions: ['.mjs', '.js', '.ts', '.jsx', '.tsx', '.json']
  },
  build: {
    // Ensure no host checking in the production build
    ssrManifest: false,
    // Generate source maps for debugging
    sourcemap: mode !== 'production',
    commonjsOptions: {
      include: [/src\/lib/, /node_modules/],
    },
    rollupOptions: {
      output: {
        manualChunks: vendorChunk,
      },
      onwarn(warning, warn) {
        // Ignore certain warnings
        if (warning.code === 'MODULE_LEVEL_DIRECTIVE') return;
        warn(warning);
      }
    }
  },
}));
