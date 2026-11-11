import { defineConfig, loadEnv } from 'vite';
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'CCAI_');
  return {
    server: {
      proxy: { '/api': { target: env.CCAI_API_URL || 'http://127.0.0.1:8000', ws: true } },
    },
    build: { sourcemap: false },
  };
});
