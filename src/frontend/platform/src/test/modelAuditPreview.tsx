// Development-only fixture: actual audit components, synthetic identity and loopback proxy.
import { Button } from "@bisheng/ui";
import { Input } from "@bisheng/ui";
import { userContext } from "@/contexts/userContext";
import { ModelAuditPanel } from "@/pages/SystemPage/dsh/ModelAuditPanel";
import "@/style/index.css";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import i18n from "../i18n";
import { ModelAuditMessagesPreview } from "./modelAuditMessagesPreview";

if (!import.meta.env.DEV)
  throw new Error("Fixture is available only in development");

export function ModelAuditPreview() {
  const [token, setToken] = useState("");
  const [ready, setReady] = useState(false);
  const [readOnly, setReadOnly] = useState(false);
  return (
    <main className="mx-auto max-w-6xl space-y-4 p-6">
      <p className="text-sm">
        Isolated fixture: synthetic identity/model; real audit components and
        local test stores.
      </p>
      {!ready ? (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            localStorage.setItem("ws_token", token);
            void i18n.changeLanguage("zh-Hans");
            setReady(true);
          }}
        >
          <label htmlFor="fixture-token">Temporary fixture token</label>
          <Input
            id="fixture-token"
            value={token}
            type="password"
            onChange={(event) => setToken(event.target.value)}
          />
          <label className="flex gap-2">
            <input
              type="checkbox"
              checked={readOnly}
              onChange={(event) => setReadOnly(event.target.checked)}
            />
            Tenant-admin presentation
          </label>
          <Button type="submit" disabled={!token}>
            Open fixture
          </Button>
        </form>
      ) : (
        <userContext.Provider
          value={{
            user: {
              user_id: readOnly ? 2 : 1,
              tenant_id: 2,
              role: readOnly ? "tenant_admin" : "admin",
              is_global_super: !readOnly,
            },
            setUser: () => undefined,
            savedComponents: [],
            addSavedComponent: async () => undefined,
            checkComponentsName: () => false,
            delComponent: () => undefined,
          }}
        >
          <ModelAuditPanel />
        </userContext.Provider>
      )}
    </main>
  );
}
const target = document.getElementById("root");
if (target)
  createRoot(target).render(
    new URLSearchParams(location.search).get("view") === "messages" ? (
      <ModelAuditMessagesPreview />
    ) : (
      <ModelAuditPreview />
    ),
  );
