import { readAuditBody } from "@/controllers/API/dshModelAudit";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pagination } from "@bisheng/ui";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { AuditMessageAssembler } from "./auditMessages";
import { ModelAuditMessage } from "./ModelAuditMessage";

interface ModelAuditBodyProps {
  requestId: string;
  tenantId?: number;
}
export function ModelAuditBody({ requestId, tenantId }: ModelAuditBodyProps) {
  const { t } = useTranslation();
  const paginationLocale = usePaginationLocale();
  const messages = useRef(new AuditMessageAssembler());
  const [, setRevision] = useState(0);
  const [segment, setSegment] = useState(0);
  const [state, setState] = useState("loading");
  const region = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (region.current) region.current.scrollTop = 0;
  }, [requestId, tenantId, segment]);
  useEffect(() => {
    const controller = new AbortController();
    const assembler = new AuditMessageAssembler();
    messages.current = assembler;
    setRevision((old) => old + 1);
    setSegment(0);
    setState("loading");
    let timer: ReturnType<typeof setTimeout> | undefined;
    const publish = () => {
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      if (!controller.signal.aborted) setRevision((old) => old + 1);
    };
    const read = async () => {
      for await (const frame of readAuditBody(
        requestId,
        tenantId,
        controller.signal,
      )) {
        if (controller.signal.aborted) return;
        assembler.accept(frame);
        timer ??= setTimeout(publish, 40);
      }
      if (!controller.signal.aborted) {
        assembler.finish();
        publish();
        setState("completed");
      }
    };
    read().catch(() => {
      if (!controller.signal.aborted) {
        assembler.finish(true);
        publish();
        setState("interrupted");
      }
    });
    return () => {
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
      messages.current = new AuditMessageAssembler();
    };
  }, [requestId, tenantId]);
  const entries = [...messages.current.entries].reverse();
  const count = entries.length;
  return (
    <div
      ref={region}
      role="region"
      aria-label={t("dsh.modelAuditView.message_content")}
      tabIndex={0}
      className="h-96 min-w-0 space-y-3 overflow-y-auto overscroll-contain bg-background p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <p role={state === "interrupted" ? "alert" : "status"}>
          {t("dsh.modelAuditView.transfer." + state)}
        </p>
        <p>{t("dsh.modelAuditView.newest_first")}</p>
        {messages.current.partial && (
          <p role="alert">{t("dsh.modelAuditView.gap")}</p>
        )}
        {["PARTIAL", "INVALID", "UNAVAILABLE", "PENDING"].includes(
          messages.current.sourcesStatus,
        ) && (
          <p role="status">
            {t(
              "dsh.modelAuditView.sources.status." +
                messages.current.sourcesStatus,
            )}
          </p>
        )}
      </div>
      {entries.slice(segment * 100, (segment + 1) * 100).map((entry) =>
        entry.type === "message" ? (
          <ModelAuditMessage key={entry.key} message={entry} />
        ) : (
          <p key={entry.key} role="alert">
            {t("dsh.modelAuditView.gap")}
          </p>
        ),
      )}
      {count > 100 && (
        <Pagination
          locale={paginationLocale}
          size="small"
          simple
          current={segment + 1}
          pageSize={100}
          total={count}
          onChange={(nextPage) => setSegment(nextPage - 1)}
        />
      )}
    </div>
  );
}
