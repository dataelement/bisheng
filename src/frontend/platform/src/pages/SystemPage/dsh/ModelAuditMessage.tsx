import { useState } from "react";
import { useTranslation } from "react-i18next";
import { DshPager } from "./common";
import { Tag } from "@bisheng/ui";
import {
  auditTextPage,
  type AuditMessage,
  type AuditText,
} from "./auditMessages";

const TEXT_PAGE_SIZE = 16000;
const roles = new Set([
  "system",
  "developer",
  "user",
  "assistant",
  "tool",
  "function",
]);
const sourceKinds = new Set([
  "user",
  "system-prompt",
  "model",
  "tool",
  "skill-catalog",
  "runtime-context",
]);

interface AuditMessageTextProps {
  value: AuditText;
  code?: boolean;
}
function AuditMessageText({ value, code = false }: AuditMessageTextProps) {
  const { t } = useTranslation();
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(value.length / TEXT_PAGE_SIZE));
  const content = auditTextPage(value, page * TEXT_PAGE_SIZE, TEXT_PAGE_SIZE);
  return (
    <div className="min-w-0 space-y-2">
      {code ? (
        <pre className="whitespace-pre-wrap break-all font-mono text-sm">
          {content}
        </pre>
      ) : (
        <p className="whitespace-pre-wrap break-words text-sm">{content}</p>
      )}
      {pages > 1 && (
        <>
          <p className="text-sm text-muted-foreground">
            {t("dsh.modelAuditView.messages.text_page", {
              page: page + 1,
              pages,
            })}
          </p>
          <DshPager
            hideUnavailable
            previous={page > 0}
            next={page + 1 < pages}
            onPrevious={() => setPage((old) => old - 1)}
            onNext={() => setPage((old) => old + 1)}
          />
        </>
      )}
    </div>
  );
}

interface ModelAuditMessageProps {
  message: AuditMessage;
}
export function ModelAuditMessage({ message }: ModelAuditMessageProps) {
  const { t } = useTranslation();
  const role = roles.has(message.role) ? message.role : "unknown";
  const kinds = [
    ...new Set(message.sources?.map((source) => source.kind) || []),
  ];
  const empty =
    !message.reasoning.length &&
    !message.tools.length &&
    !message.content.some((block) => block.text.length);
  return (
    <article className="min-w-0 overflow-hidden rounded-lg border bg-background">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
        <p className="font-medium text-foreground">
          {t("dsh.modelAuditView." + message.channel)} ·{" "}
          {t("dsh.modelAuditView.messages.roles." + role)}
          {message.name && (
            <span className="ml-2 break-all">{message.name}</span>
          )}
        </p>
        {message.channel === "input" && !message.unparsed && (
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span>{t("dsh.modelAuditView.sources.label")}</span>
            {kinds.length ? (
              <>
                {kinds.length > 1 && (
                  <span>{t("dsh.modelAuditView.sources.mixed")}</span>
                )}
                {kinds.slice(0, 3).map((kind) => (
                  <Tag
                    key={kind}
                    size="small"
                    className="max-w-full whitespace-normal break-all font-normal"
                  >
                    {sourceKinds.has(kind)
                      ? t("dsh.modelAuditView.sources.kinds." + kind)
                      : t("dsh.modelAuditView.sources.unknown")}
                  </Tag>
                ))}
                {kinds.length > 3 && (
                  <span>
                    {t("dsh.modelAuditView.sources.more", {
                      count: kinds.length - 3,
                    })}
                  </span>
                )}
              </>
            ) : (
              <span>{t("dsh.modelAuditView.sources.missing")}</span>
            )}
          </div>
        )}
        {message.toolCallId && (
          <p className="min-w-0 break-all font-mono">
            {t("dsh.modelAuditView.messages.tool_id")} · {message.toolCallId}
          </p>
        )}
      </header>
      <div className="space-y-3 p-3 text-foreground">
        {message.incomplete && (
          <p role="alert">{t("dsh.modelAuditView.messages.incomplete")}</p>
        )}
        {message.unparsed && (
          <p role="alert">{t("dsh.modelAuditView.messages.unparsed")}</p>
        )}
        {message.reasoning.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm text-muted-foreground">
              {t("dsh.modelAuditView.messages.reasoning")}
            </summary>
            <div className="mt-2">
              <AuditMessageText value={message.reasoning} />
            </div>
          </details>
        )}
        {message.content.map((block, index) =>
          block.kind === "text" ? (
            <AuditMessageText
              key={index}
              value={block.text}
              code={message.unparsed}
            />
          ) : (
            <details key={index}>
              <summary className="cursor-pointer text-sm text-muted-foreground">
                {t("dsh.modelAuditView.messages." + block.kind)}
              </summary>
              <div className="mt-2">
                <AuditMessageText value={block.text} code />
              </div>
            </details>
          ),
        )}
        {message.tools.map((tool) => (
          <div key={tool.index} className="space-y-2 rounded-lg border p-3">
            <p className="text-sm font-medium">
              {t("dsh.modelAuditView.messages.tool_call")}
            </p>
            <AuditMessageText value={tool.name} />
            {tool.id && (
              <p className="break-all text-sm text-muted-foreground">
                {t("dsh.modelAuditView.messages.tool_id")} · {tool.id}
              </p>
            )}
            <AuditMessageText value={tool.arguments} code />
          </div>
        ))}
        {empty && (
          <p className="text-sm text-muted-foreground">
            {t("dsh.modelAuditView.messages.empty")}
          </p>
        )}
      </div>
    </article>
  );
}
