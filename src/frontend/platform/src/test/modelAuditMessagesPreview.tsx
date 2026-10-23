// Development-only visual fixture. No authentication or audit storage is accessed.
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { AuditMessageAssembler } from "@/pages/SystemPage/dsh/auditMessages";
import { ModelAuditMessage } from "@/pages/SystemPage/dsh/ModelAuditMessage";
import i18n from "../i18n";

const assembler = new AuditMessageAssembler();
const inputs = [
  { parameters: { model: "hidden-model-parameters", stream: true }, tools: [] },
  {
    role: "system",
    content:
      "You are a helpful assistant.\nKeep responses concise and explain the important details.",
  },
  { role: "user", content: "Explain how audit messages should be displayed." },
  {
    role: "assistant",
    content: null,
    tool_calls: [
      {
        id: "call_lookup",
        type: "function",
        function: {
          name: "lookup_document",
          arguments: '{"topic":"audit messages"}',
        },
      },
    ],
  },
  {
    role: "tool",
    tool_call_id: "call_lookup",
    content: "Render messages by role; combine streamed response fragments.",
  },
];
const outputs = [
  { delta: { reasoning_content: "First, identify the original messages. " } },
  {
    delta: {
      reasoning_content:
        "Then combine response fragments without duplicating them.",
    },
  },
  { delta: { content: "Messages are displayed in their original order.\n\n" } },
  {
    delta: {
      content:
        "Each role has a readable message block. Streamed output is combined into one assistant reply, and reasoning is shown separately.",
    },
  },
  { finish_reason: "stop" },
];
for (const [channel, values] of [
  ["input", inputs],
  ["output", outputs],
] as const)
  values.forEach((value, unit_index) =>
    assembler.accept({
      type: "part",
      seq: 0,
      channel,
      unit_index,
      fragment: JSON.stringify(value),
    }),
  );
assembler.finish();

export function ModelAuditMessagesPreview() {
  const { t } = useTranslation();
  useEffect(() => {
    void i18n.changeLanguage("zh-Hans");
  }, []);
  return (
    <main className="mx-auto max-w-6xl space-y-4 p-6">
      <h1 className="font-medium">{t("dsh.modelAudit")}</h1>
      <section className="space-y-3 rounded-lg border p-4">
        <p role="status">{t("dsh.modelAuditView.transfer.completed")}</p>
        {assembler.entries.map((entry) =>
          entry.type === "message" ? (
            <ModelAuditMessage key={entry.key} message={entry} />
          ) : null,
        )}
      </section>
    </main>
  );
}
