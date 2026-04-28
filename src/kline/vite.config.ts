// src/kline/vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: resolve(__dirname, 'chart/index.tsx'),
      name: 'PokieChart',
      fileName: (format) => `pokie-chart.${format === 'es' ? 'mjs' : 'umd.js'}`,
    },
    outDir: 'dist',
  },
});
