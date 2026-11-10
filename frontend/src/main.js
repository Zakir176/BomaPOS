import { createApp } from 'vue';
import './style.css';
import App from './App.vue';

const app = createApp(App);
app.mount('#app');

// Register Service Worker for Offline PWA Capabilities
if ('serviceWorker' in navigator && (window.location.protocol === 'https:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js')
      .then((registration) => {
        console.log('[BomaPOS PWA] Service Worker registered successfully with scope:', registration.scope);
      })
      .catch((error) => {
        console.warn('[BomaPOS PWA] Service Worker registration failed:', error);
      });
  });
}
