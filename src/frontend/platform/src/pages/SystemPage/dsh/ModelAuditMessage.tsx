import { useState } from "react";
import { useTranslation } from "react-i18next";
import { DshPager } from "./common";
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
  const empty =
    !message.reasoning.length &&
    !message.tools.length &&
    !message.content.some((block) => block.text.length);
  return (
    <article className="min-w-0 space-y-3 rounded-lg border p-4">
      <p className="text-sm font-medium">
        {t("dsh.modelAuditView." + message.channel)} ·{" "}
        {t("dsh.modelAuditView.messages.roles." + role)}
        {message.name && <span className="ml-2 break-all">{message.name}</span>}
      </p>
      {message.toolCallId && (
        <p className="break-all text-sm text-muted-foreground">
          {t("dsh.modelAuditView.messages.tool_id")} · {message.toolCallId}
        </p>
      )}
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
    </article>
  );
}
