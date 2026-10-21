import { Button } from "@/components/bs-ui/button"
import { Label } from "@/components/bs-ui/label"
import { useTranslation } from "react-i18next"

export interface SandboxProbeResult {
  url: string
  status: string
}

interface SandboxEndpointFieldsProps {
  addressText: string
  token: string
  addressSource: string
  tokenSource: string
  deploymentAddress: string
  testing: boolean
  results: SandboxProbeResult[]
  onAddressChange: (value: string) => void
  onTokenChange: (value: string) => void
  onTest: () => void
}

const SOURCE_KEYS: Record<string, string> = {
  page: "sandboxSourcePage",
  deployment: "sandboxSourceDeployment",
  default: "sandboxSourceDefault",
}

const STATUS_KEYS: Record<string, string> = {
  ok: "sandboxTestOk",
  unreachable: "sandboxTestUnreachable",
  token_rejected: "sandboxTestTokenRejected",
  busy: "sandboxTestBusy",
}

export function SandboxEndpointFields({
  addressText,
  token,
  addressSource,
  tokenSource,
  deploymentAddress,
  testing,
  results,
  onAddressChange,
  onTokenChange,
  onTest,
}: SandboxEndpointFieldsProps) {
  const { t } = useTranslation("tool")
  const sourceLabel = (source: string) => t(SOURCE_KEYS[source] || "sandboxSourceDefault")
  return (
    <div className="space-y-4">
      <div>
        <Label className="mb-2 block" htmlFor="sandbox-address">
          {t("sandboxAddressLabel")} ({sourceLabel(addressSource)})
        </Label>
        <textarea
          id="sandbox-address"
          className="border-input bg-background min-h-24 w-full rounded-md border px-3 py-2 text-sm"
          value={addressText}
          placeholder={t("sandboxAddressPlaceholder")}
          onChange={(event) => onAddressChange(event.target.value)}
        />
        <p className="text-muted-foreground mt-2 text-xs">{t("sandboxAddressHint")}</p>
        {deploymentAddress ? (
          <p className="text-muted-foreground mt-1 text-xs">
            {t("sandboxDeploymentAddress")}: {deploymentAddress}
          </p>
        ) : null}
      </div>
      <div>
        <Label className="mb-2 block" htmlFor="sandbox-token">
          {t("sandboxTokenLabel")} ({sourceLabel(tokenSource)})
        </Label>
        <input
          id="sandbox-token"
          className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
          type="password"
          autoComplete="off"
          value={token}
          placeholder={t("sandboxTokenPlaceholder")}
          onChange={(event) => onTokenChange(event.target.value)}
        />
      </div>
      <div>
        <Button type="button" variant="outline" disabled={testing} onClick={onTest}>
          {t("sandboxTestConnection")}
        </Button>
        <p className="text-muted-foreground mt-2 text-xs">{t("sandboxTestScope")}</p>
        <ul className="mt-2 space-y-1 text-sm">
          {results.map((item) => (
            <li key={item.url}>
              {item.url} — {t(STATUS_KEYS[item.status] || "sandboxTestUnreachable")}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
