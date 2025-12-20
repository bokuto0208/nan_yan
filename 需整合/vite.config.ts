import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // bind to IPv4 localhost and use an alternate default port to avoid permission issues
    host: '127.0.0.1',
    // try a higher port number in case lower ports are restricted
    port: 51730
  }
})
