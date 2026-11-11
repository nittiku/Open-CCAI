import { defineConfig } from 'vite';
export default defineConfig({
  build: {
    lib: {
      entry: 'src/index.ts',
      name: 'OpenCCAI',
      formats: ['iife'],
      fileName: () => 'open-ccai.js',
    },
    minify: true,
  },
});
