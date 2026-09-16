import { Button } from "@/components/bs-ui/button"
import { toast } from "@/components/bs-ui/toast/use-toast"
import { locationContext } from "@/contexts/locationContext"
import { getDevToolkitVersionsApi } from "@/controllers/API/devToolkit"
import type { DevToolkitVersions } from "@/types/api/devToolkit"
import { copyText } from "@/utils"
import { Copy } from "lucide-react"
import { useContext, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"

/**
 * The access-information block at the top of the 「API 密钥」 tab (F053 AC-44 / AC-45).
 *
 * Everything shown here is public: four addresses and one command line. The key
 * itself is handed over separately and appears nowhere in this block — neither
 * on screen nor in the copied text — so an administrator can forward it in any
 * channel, as many times as they like.
 *
 * Two derivations, each from its own source and never invented here:
 *
 * * the MCP address (F052) and the OpenAI-compatible base URL (F051) come from
 *   `GET /api/v1/dev-toolkit/versions`, which asks the backend's single
 *   producer for them — composing `origin + /api/v2/model/v1` in the browser
 *   would be a second spelling of an address that already has one;
 * * the platform address and the installer link come from the browser's own
 *   origin, because that is the address the administrator actually reached the
 *   platform at, and the payload hands back `download_path` (a path, not a URL)
 *   precisely so the browser joins it.
 *
 * The block is absent where the open-capability layer is not deployed: the
 * endpoint is not even registered there, and `openPlatformEnabled` is the same
 * process-level setting, so the request is never made.
 */
export function AccessInfoPanel() {
  const { t } = useTranslation()
  const { appConfig } = useContext(locationContext)
  const [versions, setVersions] = useState<DevToolkitVersions | null>(null)

  const openPlatformEnabled = !!appConfig?.openPlatformEnabled

  useEffect(() => {
    if (!openPlatformEnabled) return
    let cancelled = false
    getDevToolkitVersionsApi()
      .then((data) => {
        if (!cancelled) setVersions(data)
      })
      .catch(() => {
        // Best-effort: the block is an accelerator, not a gate. A platform that
        // cannot answer just shows no block rather than an error on a page the
        // administrator opened to manage keys.
        if (!cancelled) setVersions(null)
      })
    return () => {
      cancelled = true
    }
  }, [openPlatformEnabled])

  if (!openPlatformEnabled || !versions) return null

  const platformAddress = window.location.origin
  const cliDownloadUrl = versions.cli
    ? `${platformAddress}${versions.cli.download_path}`
    : ""
  const loginCommand = `bisheng login ${platformAddress} --api-key ${t(
    "openApiManagement.accessInfo.keyPlaceholder",
  )}`

  const rows: Array<{ label: string; value: string; href?: string }> = [
    {
      label: t("openApiManagement.accessInfo.platformAddress"),
      value: platformAddress,
    },
  ]
  if (versions.mcp) {
    rows.push({
      label: t("openApiManagement.accessInfo.mcpAddress"),
      value: versions.mcp.url,
    })
  }
  if (versions.model) {
    rows.push({
      label: t("openApiManagement.accessInfo.modelBaseUrl"),
      value: versions.model.base_url,
    })
  }
  if (cliDownloadUrl) {
    rows.push({
      label: t("openApiManagement.accessInfo.cliDownload"),
      value: cliDownloadUrl,
      href: cliDownloadUrl,
    })
  }
  rows.push({
    label: t("openApiManagement.accessInfo.loginCommand"),
    value: loginCommand,
  })

  // Built at click time, never stored: an administrator who re-opens the page
  // after the platform moved gets the new addresses, not a snapshot (AC-45).
  const handleCopy = () => {
    const body = rows
      .map((row) =>
        t("openApiManagement.accessInfo.copyLine", {
          label: row.label,
          value: row.value,
        }),
      )
      .join("\n")
    copyText(
      [
        t("openApiManagement.accessInfo.copyHeader"),
        body,
        t("openApiManagement.accessInfo.copyFooter"),
      ].join("\n"),
    )
    toast({
      title: t("openApiManagement.accessInfo.title"),
      description: t("openApiManagement.feedback.copied"),
      variant: "success",
    })
  }

  return (
    <section
      aria-label={t("openApiManagement.accessInfo.title")}
      className="rounded-md border bg-muted/30 p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-medium">
            {t("openApiManagement.accessInfo.title")}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("openApiManagement.accessInfo.hint")}
          </p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={handleCopy}>
          <Copy aria-hidden="true" className="mr-1 size-3.5" />
          {t("openApiManagement.accessInfo.copy")}
        </Button>
      </div>
      <dl className="mt-3 space-y-2">
        {rows.map((row) => (
          <div
            key={row.label}
            className="flex flex-col gap-0.5 sm:flex-row sm:gap-3"
          >
            <dt className="shrink-0 text-xs text-muted-foreground sm:w-48">
              {row.label}
            </dt>
            <dd className="min-w-0 break-all text-xs">
              {row.href ? (
                <a
                  className="text-primary underline"
                  href={row.href}
                  rel="noreferrer"
                  target="_blank"
                >
                  {row.value}
                </a>
              ) : (
                <code>{row.value}</code>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {versions.cli ? null : (
        <p className="mt-2 text-xs text-muted-foreground">
          {t("openApiManagement.accessInfo.cliMissing")}
        </p>
      )}
    </section>
  )
}
