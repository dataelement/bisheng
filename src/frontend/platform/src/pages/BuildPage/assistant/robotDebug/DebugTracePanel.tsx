import type { DebugTurn } from "./useRobotDebug";
import { useTranslation } from "react-i18next";

interface DebugTracePanelProps { turn?: DebugTurn }

export function DebugTracePanel({ turn }: DebugTracePanelProps) {
  const { t } = useTranslation();
  const terminal = turn?.events.find(event => event.type === "completed" || event.type === "failed");
  const count = turn?.events.filter(event => event.type === "tool_start").length ?? 0;
  return (
    <section className="min-w-0 rounded-xl border bg-background p-4" aria-label={t("build.robotDebug.trace")}>
      <h2 className="text-base font-medium">{t("build.robotDebug.trace")}</h2>
      <p className="my-3 text-sm text-muted-foreground">{t("build.robotDebug.callCount", { count })}</p>
      {!turn && <p className="text-sm text-muted-foreground">{t("build.robotDebug.traceEmpty")}</p>}
      {terminal?.type === "failed" && <p role="alert" className="mb-3 text-sm text-destructive">{t("build.robotDebug.failedType", { type: terminal.data.error_type })}</p>}
      {turn?.events.filter(event => event.type !== "answer_delta").map(event => (
        <div key={event.seq} className="mb-4 border-t pt-3 text-sm">
          <p className="text-muted-foreground">{event.seq}. {t(`build.robotDebug.event.${event.type}`)}</p>
          {event.type === "context" && <p className="mt-2 break-words">{event.run_id}</p>}
          {event.type === "tool_start" && <>
            <p className="my-2 break-words">{event.data.tool_name}</p>
            <pre className="whitespace-pre-wrap break-words font-mono">{event.data.query}</pre>
            <details className="mt-2"><summary className="cursor-pointer py-2">{t("build.robotDebug.toolType")}</summary>
              <pre className="whitespace-pre-wrap break-words font-mono">{event.data.tool_type}{"\n"}{event.data.observer_type}</pre>
            </details>
          </>}
          {event.type === "tool_end" && <>
            <details open className="mt-2"><summary className="cursor-pointer py-2">{t("build.robotDebug.modelInput")}</summary>
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono">{event.data.model_tool_output}</pre>
            </details>
            <details className="mt-2"><summary className="cursor-pointer py-2">{t("build.robotDebug.rawMetadata")}</summary>
              <p className="mb-2 text-muted-foreground">{t("build.robotDebug.metadataNotice")}</p>
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono">{JSON.stringify(event.data.retrieval_metadata ?? [], null, 2)}</pre>
            </details>
          </>}
          {event.type === "tool_error" && <p role="alert" className="mt-2 text-destructive">{t("build.robotDebug.failedType", { type: event.data.error_type })}</p>}
        </div>
      ))}
    </section>
  );
}
