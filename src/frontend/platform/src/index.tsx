import ReactDOM from "react-dom/client";
import App from "./App";
import ContextWrapper from "./contexts";
import reportWebVitals from "./reportWebVitals";
import './i18n';
// @ts-ignore
import "./style/index.css";
// @ts-ignore
import "./style/applies.css";
// @ts-ignore
import "./style/classes.css";
// @ts-ignore
import "./style/markdown.css";
import { QueryClient, QueryClientProvider } from "react-query";

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

// Backdoor entry: when landing on /admin-login, drop any stored third-party
// redirect URLs synchronously — before React mounts and before /user/info fires —
// so the 401 interceptor in request.ts cannot bounce us straight to the IdP.
{
  // @ts-ignore
  const baseUrl: string = (typeof __APP_ENV__ !== 'undefined' && __APP_ENV__?.BASE_URL) || ''
  const normalizedPath = window.location.pathname.replace(baseUrl, '')
  if (normalizedPath === '/admin-login' || normalizedPath.startsWith('/admin-login/')) {
    localStorage.removeItem('THIRD_PARTY_LOGIN_URL')
    localStorage.removeItem('THIRD_PARTY_LOGOUT_URL')
  }
}

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
);


// Handle chunk loading failures after deployment (old HTML referencing new hashes)
// Vite emits this event when a dynamic import fails to preload
window.addEventListener('vite:preloadError', (event) => {
  // Prevent infinite reload: only reload once per session
  const lastReload = sessionStorage.getItem('chunk-reload');
  const now = Date.now();
  if (!lastReload || now - Number(lastReload) > 10000) {
    sessionStorage.setItem('chunk-reload', String(now));
    window.location.reload();
  }
});


const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      refetchOnMount: false,
      retry: 0
    }
  }
})
root.render(
  <QueryClientProvider client={queryClient}>
    <ContextWrapper>
      <App />
    </ContextWrapper>
  </QueryClientProvider>
);
reportWebVitals();
