import { useLayoutEffect } from "react";
import { useLocation } from "react-router-dom";
import { refreshClientEnvironment } from "~/utils/clientEnvironment";

/** Sample explicit SPA entries before paint, including routes outside auth. */
export function ClientEnvironmentSync() {
  const location = useLocation();
  useLayoutEffect(() => {
    refreshClientEnvironment();
  }, [location]);
  return null;
}
