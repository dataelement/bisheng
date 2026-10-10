import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Textarea } from "@/components/bs-ui/textarea";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { DebugTracePanel } from "./DebugTracePanel";
import { useRobotDebug } from "./useRobotDebug";

export function RobotDebugPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const assistantId = params.get("assistantId") ?? "";
  if (import.meta.env.VITE_EPLUS_DEBUG_ENABLED !== "true" || !assistantId) {
    return <p role="alert" className="p-6">{t("build.robotDebug.unavailable")}</p>;
  }
  return <RobotDebugSession key={assistantId} assistantId={assistantId} />;
}

interface RobotDebugSessionProps { assistantId: string }

function RobotDebugSession({ assistantId }: RobotDebugSessionProps) {
  const { t } = useTranslation();
  const debug = useRobotDebug(assistantId);
  const [userId, setUserId] = useState("");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  useEffect(() => { if (debug.context) setUserId(String(debug.context.test_user_id)); }, [debug.context?.test_user_id]);
  useEffect(() => { setSelectedId(debug.turns.at(-1)?.id ?? ""); }, [debug.turns.length]);
  const selectedTurn = debug.turns.find(turn => turn.id === selectedId);
  const handleSend = () => { if (query.trim() && query.trim().length <= 4096) { void debug.send(query); setQuery(""); } };
  const handleClear = () => { debug.clear(); setQuery(""); };
  const userValid = /^\d+$/.test(userId) && Number.isSafeInteger(Number(userId)) && Number(userId) > 0;
  return (
    <main className="h-screen overflow-auto bg-muted/30 p-4 md:p-6">
      <div className="mx-auto max-w-7xl space-y-4">
        <header className="space-y-2">
          <Link className="text-sm text-primary underline" to={`/assistant/${encodeURIComponent(assistantId)}/`}>{t("build.robotDebug.back")}</Link>
          <h1 className="text-xl font-medium">{t("build.robotDebug.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("build.robotDebug.boundary")}</p>
        </header>
        <section className="space-y-3 rounded-xl border bg-background p-4" aria-label={t("build.robotDebug.configuration")}>
          {debug.loading && <p>{t("loading")}</p>}
          {debug.error && <p role="alert" className="text-sm text-destructive">{t("build.robotDebug.contextError")}</p>}
          {debug.context && <>
            <p className="text-sm">{t("build.robotDebug.assistantModel", { name: debug.context.assistant_name, model: debug.context.model_name ?? debug.context.configured_model_id })}</p>
            <p className="break-words text-sm">{t("build.robotDebug.bot", { id: debug.context.bot_id })}</p>
            <p className="break-words text-sm">{t("build.robotDebug.spaces")}: {debug.context.spaces.map(space => `${space.name} (${space.id})`).join(", ")}</p>
            <p className="text-sm">{t("build.robotDebug.identity", { name: debug.context.test_user_name, id: debug.context.test_user_id })} · {t(debug.context.external_identity_available ? "build.robotDebug.externalPresent" : "build.robotDebug.externalMissing")}</p>
            {debug.context.execution_mode && <p className="text-sm">{t("build.robotDebug.executionMode", { mode: debug.context.execution_mode })}</p>}
            {debug.context.test_tools && <p className="text-sm">{t("build.robotDebug.enabledTools", { tools: debug.context.test_tools.join(", ") })}</p>}
            {debug.context.execution_mode === "ReAct" && <p className="text-sm text-muted-foreground">{t("build.robotDebug.reactNotice")}</p>}
            {!!debug.context.disabled_tools?.length && <p className="break-words text-sm text-muted-foreground">{t("build.robotDebug.disabledTools", { tools: debug.context.disabled_tools.join(", ") })}</p>}
          </>}
          <div className="flex flex-wrap items-end gap-2">
            <div><label htmlFor="robot-debug-user" className="mb-2 block text-sm">{t("build.robotDebug.testUser")}</label>
              <Input id="robot-debug-user" className="w-44" value={userId} inputMode="numeric" onChange={event => setUserId(event.target.value)} />
            </div>
            <Button variant="outline" disabled={!userValid || debug.busy || debug.loading} onClick={() => { setQuery(""); void debug.loadContext(Number(userId)); }}>{t("build.robotDebug.applyUser")}</Button>
          </div>
        </section>
        <div className="grid items-start gap-4 md:grid-cols-2">
          <section className="min-w-0 space-y-4 rounded-xl border bg-background p-4" aria-label={t("build.robotDebug.conversation")}>
            <h2 className="text-base font-medium">{t("build.robotDebug.conversation")}</h2>
            {!debug.turns.length && <p className="text-sm text-muted-foreground">{t("build.robotDebug.empty")}</p>}
            {debug.turns.map(turn => <article key={turn.id} className="space-y-2 border-t pt-3">
              <p className="whitespace-pre-wrap break-words text-sm font-medium">{turn.question}</p>
              <p className="whitespace-pre-wrap break-words text-sm">{turn.answer || t("build.robotDebug.waiting")}</p>
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm text-muted-foreground">{t(`build.robotDebug.state.${turn.state}`)}</p>
                <Button variant="link" onClick={() => setSelectedId(turn.id)}>{t("build.robotDebug.inspect")}</Button>
              </div>
            </article>)}
            <label htmlFor="robot-debug-query" className="block text-sm">{t("build.robotDebug.question")}</label>
            <Textarea id="robot-debug-query" value={query} disabled={debug.busy || !debug.context} onChange={event => setQuery(event.target.value)} placeholder={t("build.robotDebug.queryExample")} />
            {query.trim().length > 4096 && <p role="alert" className="text-sm text-destructive">{t("build.robotDebug.queryTooLong")}</p>}
            <div className="flex gap-2">
              <Button disabled={debug.busy || debug.loading || !debug.context || !query.trim() || query.trim().length > 4096} onClick={handleSend}>{t("build.robotDebug.send")}</Button>
              <Button variant="outline" disabled={!debug.busy} onClick={debug.stop}>{t("build.robotDebug.stop")}</Button>
              <Button variant="outline" onClick={handleClear}>{t("build.robotDebug.clear")}</Button>
            </div>
          </section>
          <DebugTracePanel turn={selectedTurn} />
        </div>
      </div>
    </main>
  );
}
