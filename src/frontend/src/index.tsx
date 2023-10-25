import ReactDOM from "react-dom/client";
import App from "./App";
import ContextWrapper from "./contexts";
import reportWebVitals from "./reportWebVitals";
import './i18n';
import "./index.css";

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement
);
root.render(
  <ContextWrapper>
    <App />
  </ContextWrapper>
);
reportWebVitals();
