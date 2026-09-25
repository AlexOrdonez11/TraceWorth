import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
const proxy = {'/api': {target: process.env.TRACEWORTH_DEV_API_TARGET || 'http://127.0.0.1:18766', changeOrigin: true}};
export default defineConfig({ plugins: [react()], server: {host: '127.0.0.1', port: 18767, strictPort: true, proxy}, preview: {proxy} });
