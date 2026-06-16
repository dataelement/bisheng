// Polyfill Object.hasOwn for browsers that do not support ES2022
if (!Object.hasOwn) {
  Object.hasOwn = function hasOwn(obj, prop) {
    return Object.prototype.hasOwnProperty.call(obj, prop);
  };
}

const DEV_SW_RESET_KEY = '__bisheng_dev_sw_reset__';

// Dev mode never ships a service worker (VitePWA devOptions.enabled = false),
// so proactively unregister any stale SW left over from a prior prod build on
// this origin. Must NOT be gated on hostname: LAN-IP access (e.g. a shared dev
// box reached via 192.168.x.x) would otherwise keep serving stale cached chunks
// from the dead SW and white-screen on every visit.
if (
  import.meta.env.DEV &&
  typeof window !== 'undefined' &&
  'serviceWorker' in navigator &&
  window.sessionStorage.getItem(DEV_SW_RESET_KEY) !== 'done'
) {
  void (async () => {
    try {
      const registrations = await navigator.serviceWorker.getRegistrations();
      if (!registrations.length) {
        window.sessionStorage.setItem(DEV_SW_RESET_KEY, 'done');
        return;
      }

      await Promise.all(registrations.map((registration) => registration.unregister()));

      if ('caches' in window) {
        const cacheKeys = await window.caches.keys();
        await Promise.all(cacheKeys.map((cacheKey) => window.caches.delete(cacheKey)));
      }

      window.sessionStorage.setItem(DEV_SW_RESET_KEY, 'done');
      window.location.reload();
    } catch (error) {
      console.warn('Failed to reset dev service workers', error);
    }
  })();
}

import 'regenerator-runtime/runtime';
import { createRoot } from 'react-dom/client';
import './locales/i18n';
import App from './App';
import './style.css';
import './mobile.css';
import { ApiErrorBoundaryProvider } from './hooks/ApiErrorBoundaryContext';

if (__VCONSOLE_ENABLED__) {
  import('vconsole').then(({ default: VConsole }) => {
    const vc = new VConsole();
    vc.hideSwitch();
    let visible = false;
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'd') {
        e.preventDefault();
        visible ? vc.hide() : vc.show();
        visible = !visible;
      }
    });
  });
}

const container = document.getElementById('root');
const root = createRoot(container);

root.render(
  <ApiErrorBoundaryProvider>
    <App />
  </ApiErrorBoundaryProvider>,
);
