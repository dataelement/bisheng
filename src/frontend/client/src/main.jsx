// Polyfill Object.hasOwn for browsers that do not support ES2022
if (!Object.hasOwn) {
  Object.hasOwn = function hasOwn(obj, prop) {
    return Object.prototype.hasOwnProperty.call(obj, prop);
  };
}

import 'regenerator-runtime/runtime';
import { createRoot } from 'react-dom/client';
import './locales/i18n';
import App from './App';
import './style.css';
import './mobile.css';
import './vditor.css';
import { ApiErrorBoundaryProvider } from './hooks/ApiErrorBoundaryContext';

// if (__VCONSOLE_ENABLED__) {
//   import('vconsole').then(({ default: VConsole }) => {
//     const vc = new VConsole();
//     vc.hideSwitch();
//     let visible = false;
//     window.addEventListener('keydown', (e) => {
//       if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'd') {
//         e.preventDefault();
//         visible ? vc.hide() : vc.show();
//         visible = !visible;
//       }
//     });
//   });
// }

const container = document.getElementById('root');
const root = createRoot(container);

root.render(
  <ApiErrorBoundaryProvider>
    <App />
  </ApiErrorBoundaryProvider>,
);
