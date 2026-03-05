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
