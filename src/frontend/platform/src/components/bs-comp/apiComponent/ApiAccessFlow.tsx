import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/bs-ui/card"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { copyText } from "@/utils"
import { Check, Clipboard } from "lucide-react"
import { useState } from "react"
import { useTranslation } from "react-i18next"
import { useParams } from "react-router-dom"
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter"
import { oneDark } from "react-syntax-highlighter/dist/cjs/styles/prism"

export function ApiAccessFlow() {
  const { t } = useTranslation()
  const { id } = useParams()
  const { message } = useToast()
  const [copied, setCopied] = useState(false)
  const invokeUrl = `${location.origin}/api/v3/workflow/invoke`
  const stopUrl = `${location.origin}/api/v3/workflow/stop`
  const websocketUrl = `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/v3/workflow/chat/${id}`
  const example = `import requests

response = requests.post(
    "${invokeUrl}",
    json={
        "workflow_id": "${id}",
        "stream": True,
        "input": None,
    },
    stream=True,
)
response.raise_for_status()
for line in response.iter_lines():
    if line:
        print(line.decode("utf-8"))`

  const handleCopyText = async (value: string) => {
    await copyText(value)
    message({ variant: "success", description: t("api.copySuccess") })
  }

  const handleCopyExample = async () => {
    await handleCopyText(example)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }

  return (
    <section className="max-w-[1600px] flex-grow">
      <Card className="mb-8">
        <CardHeader>
          <CardTitle>{t("api.publicWorkflow.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{t("api.publicWorkflow.description")}</p>
          <div className="flex flex-col gap-2">
            <button type="button" className="flex items-center gap-2 text-left" onClick={() => handleCopyText(invokeUrl)}>
              <Badge>POST</Badge><code>{invokeUrl}</code>
            </button>
            <button type="button" className="flex items-center gap-2 text-left" onClick={() => handleCopyText(stopUrl)}>
              <Badge>POST</Badge><code>{stopUrl}</code>
            </button>
            <button type="button" className="flex items-center gap-2 text-left" onClick={() => handleCopyText(websocketUrl)}>
              <Badge>WS</Badge><code>{websocketUrl}</code>
            </button>
          </div>
        </CardContent>
      </Card>

      <Card className="mb-8">
        <CardHeader><CardTitle>{t("api.exampleCode")}</CardTitle></CardHeader>
        <CardContent>
          <div className="relative">
            <Button variant="ghost" size="icon" className="absolute right-2 top-2 z-10" onClick={handleCopyExample}>
              {copied ? <Check size={18} /> : <Clipboard size={16} />}
              <span className="sr-only">{t("api.publicWorkflow.copyExample")}</span>
            </Button>
            <SyntaxHighlighter language="python" style={oneDark} className="custom-scroll overflow-auto text-sm">
              {example}
            </SyntaxHighlighter>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("api.publicWorkflow.contractTitle")}</CardTitle></CardHeader>
        <CardContent>
          <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
            <li>{t("api.publicWorkflow.stepInvoke")}</li>
            <li>{t("api.publicWorkflow.stepEvents")}</li>
            <li>{t("api.publicWorkflow.stepInput")}</li>
            <li>{t("api.publicWorkflow.stepClose")}</li>
          </ol>
        </CardContent>
      </Card>
    </section>
  )
}
