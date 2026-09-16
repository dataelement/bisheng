/**
 * Version diff on the detail page's version tab (F055 AC-41 / T064).
 *
 * The rendering is `@bisheng/file-viewers`' `VersionDiffView` — the *same*
 * component the client's review view mounts, which is what AC-41 means by
 * "版本 tab 与审读视图同一呈现". Everything app-specific stays here: which two
 * versions to compare, how to fetch them, and how a refusal reads.
 *
 * The default pair is "the running version → the one waiting to go live",
 * because that is the comparison an owner opens this tab for. Both sides stay
 * changeable: a version record is append-only and never rolled back, so
 * looking at what an earlier release changed is a legitimate read.
 *
 * `react-query` v3 is frozen in this app (design K11 ①), hence the plain
 * `useState` + `useEffect` pair rather than a query hook.
 */
import {
  getHostedAppErrorMessage,
  getHostedAppVersionDiffApi,
  getHostedAppVersionsApi,
  type HostedAppVersion,
  type HostedAppVersionDiff,
} from "@/controllers/API/hostedApp"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { VersionDiffView } from "@bisheng/file-viewers"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"

interface VersionDiffProps {
  appId: string
  /** Changing this re-reads the version list — a release moved underneath us. */
  reloadKey?: string
}

/**
 * The pair to open with: newest version on the right, and on the left the
 * newest *published* one below it — "上一已发布版本" in AC-41's words. Falls
 * back to the next version down when nothing has been published yet, so an
 * application whose first release was rejected still shows a comparison.
 */
export function defaultDiffPair(
  versions: HostedAppVersion[],
): { base: string; target: string } | null {
  if (versions.length < 2) return null
  const target = versions.find((one) => one.is_pending) ?? versions[0]
  const older = versions.filter(
    (one) =>
      one.version_id !== target.version_id &&
      one.version_no < target.version_no,
  )
  if (older.length === 0) return null
  const base =
    older.find((one) => one.is_current) ??
    older.find((one) => one.terminal_state === "online") ??
    older[0]
  return { base: base.version_id, target: target.version_id }
}

function versionLabel(version: HostedAppVersion): string {
  return `v${version.version_no}`
}

export function VersionDiff({ appId, reloadKey = "" }: VersionDiffProps) {
  const { t } = useTranslation()
  const [versions, setVersions] = useState<HostedAppVersion[]>([])
  const [base, setBase] = useState("")
  const [target, setTarget] = useState("")
  const [diff, setDiff] = useState<HostedAppVersionDiff | null>(null)
  const [loading, setLoading] = useState(true)
  // What failed, not how it reads. `useTranslation()` hands back a fresh `t`
  // on every render, so translating inside an effect would force `t` into its
  // dependency list and the fetch would re-fire forever.
  const [failure, setFailure] = useState<{
    message: string
    fallbackKey: string
  } | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getHostedAppVersionsApi(appId)
      .then((rows) => {
        if (cancelled) return
        // A row without an id would crash the Radix SelectItem below and take
        // the whole page with it, so it never reaches the list.
        const usable = (rows || []).filter((one) => !!one.version_id)
        setVersions(usable)
        const pair = defaultDiffPair(usable)
        setBase(pair?.base ?? "")
        setTarget(pair?.target ?? "")
        setFailure(null)
      })
      .catch((error) => {
        if (cancelled) return
        setVersions([])
        setFailure({
          message: getHostedAppErrorMessage(error),
          fallbackKey: "hostedApp.versions.loadFailed",
        })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [appId, reloadKey])

  useEffect(() => {
    if (!base || !target || base === target) {
      setDiff(null)
      return
    }
    let cancelled = false
    setLoading(true)
    getHostedAppVersionDiffApi(appId, base, target)
      .then((data) => {
        if (cancelled) return
        setDiff(data)
        setFailure(null)
      })
      .catch((error) => {
        if (cancelled) return
        setDiff(null)
        setFailure({
          message: getHostedAppErrorMessage(error),
          fallbackKey: "hostedApp.versionDiff.loadFailed",
        })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [appId, base, target])

  const caption = useMemo(() => {
    const from = versions.find((one) => one.version_id === base)
    const to = versions.find((one) => one.version_id === target)
    return from && to ? `${versionLabel(from)} → ${versionLabel(to)}` : ""
  }, [versions, base, target])

  const failureText = failure
    ? failure.message || t(failure.fallbackKey)
    : undefined

  const emptyMessage =
    versions.length < 2
      ? t("hostedApp.versionDiff.needTwoVersions")
      : base && target && base === target
        ? t("hostedApp.versionDiff.pickTwoDifferent")
        : undefined

  return (
    <section className="flex flex-col gap-3" data-testid="hosted-app-version-diff">
      <h3 className="text-sm font-medium">{t("hostedApp.versionDiff.title")}</h3>

      {versions.length >= 2 && (
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            {t("hostedApp.versionDiff.base")}
            <Select value={base} onValueChange={setBase}>
              <SelectTrigger className="w-32">
                <SelectValue placeholder={t("hostedApp.versionDiff.base")} />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {versions.map((one) => (
                    <SelectItem key={one.version_id} value={one.version_id}>
                      {versionLabel(one)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            {t("hostedApp.versionDiff.target")}
            <Select value={target} onValueChange={setTarget}>
              <SelectTrigger className="w-32">
                <SelectValue placeholder={t("hostedApp.versionDiff.target")} />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {versions.map((one) => (
                    <SelectItem key={one.version_id} value={one.version_id}>
                      {versionLabel(one)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </label>
        </div>
      )}

      <VersionDiffView
        summary={diff?.summary ?? null}
        files={diff?.files ?? []}
        patches={diff?.patches ?? []}
        caption={caption}
        loading={loading}
        errorMessage={failureText}
        emptyMessage={emptyMessage}
      />
    </section>
  )
}
