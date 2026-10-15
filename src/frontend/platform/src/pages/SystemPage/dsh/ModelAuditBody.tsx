import { readAuditBody } from "@/controllers/API/dshModelAudit";
import type { AuditBodyFrame } from "@/types/dshModelAudit";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DshPager } from "./common";

interface ModelAuditBodyProps {
  requestId: string;
  tenantId?: number;
}
export function ModelAuditBody({ requestId, tenantId }: ModelAuditBodyProps) {
  const { t } = useTranslation();
  const frames = useRef<AuditBodyFrame[]>([]);
  const [count, setCount] = useState(0);
  const [segment, setSegment] = useState(0);
  const [state, setState] = useState("loading");
  useEffect(() => {
    const controller = new AbortController();
    frames.current = [];
    setCount(0);
    setSegment(0);
    setState("loading");
    let size = 0;
    const read = async () => {
      for await (const frame of readAuditBody(
        requestId,
        tenantId,
        controller.signal,
      )) {
        if (controller.signal.aborted) return;
        if (frame.type === "part") {
          size += frame.fragment.length;
          if (size > 20 * 1024 * 1024)
            throw new Error("Display budget exceeded");
        }
        frames.current.push(frame);
        setCount(frames.current.length);
      }
      if (!controller.signal.aborted) setState("completed");
    };
    read().catch(() => {
      if (!controller.signal.aborted) setState("interrupted");
    });
    return () => {
      controller.abort();
      frames.current = [];
    };
  }, [requestId, tenantId]);
  return (
    <div className="space-y-3 rounded-lg border p-4">
      <p role={state === "interrupted" ? "alert" : "status"}>
        {t("dsh.modelAuditView.transfer." + state)}
      </p>
      {count > 100 && (
        <p className="text-sm text-muted-foreground">
          {t("dsh.modelAuditView.bodySegment", {
            page: segment + 1,
            pages: Math.ceil(count / 100),
          })}
        </p>
      )}
      {frames.current
        .slice(segment * 100, (segment + 1) * 100)
        .map((frame, index) =>
          frame.type === "part" ? (
            <div key={frame.seq}>
              <p className="text-sm text-muted-foreground">
                {t("dsh.modelAuditView." + frame.channel)} ·{" "}
                {frame.unit_index + 1}
              </p>
              <pre className="whitespace-pre-wrap break-all font-mono text-sm">
                {frame.fragment}
              </pre>
            </div>
          ) : frame.type === "gap" ? (
            <p key={"gap-" + index} role="alert">
              {t("dsh.modelAuditView.gap")}
            </p>
          ) : null,
        )}
      <DshPager
        hideUnavailable
        previous={segment > 0}
        next={(segment + 1) * 100 < count}
        onPrevious={() => setSegment((old) => old - 1)}
        onNext={() => setSegment((old) => old + 1)}
      />
    </div>
  );
}
