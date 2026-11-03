import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Para trabajar en el visor con recarga automática: con la API corriendo,
// `npm run dev` y abrir http://localhost:5173. El navegador sigue viendo un
// solo origen, porque Vite le reenvía a la API lo que no es del visor.
const API = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: { '/api': API, '/media': API },
  },
  build: {
    // Swagger UI ocupa 1,5 MB, en una página aparte de la del visor.
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      input: { visor: 'index.html', docs: 'docs.html' },
    },
  },
})
