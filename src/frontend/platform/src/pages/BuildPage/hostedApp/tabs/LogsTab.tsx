/**
 * Run-log tab (AC-55, WB-13) — read-only.
 *
 * What it shows is the **application's own** stdout/stderr, including its error
 * traces; nothing from the platform side. Retention is the container log
 * rotation window, so the product promise is "the recent logs", not an archive:
 * an empty result is a legitimate answer for a freshly started app and is shown
 * as an empty state, never as an error.
 *
 * A caller without access gets business code 16161 inside a 200 envelope, which
 * is why the request is `silent`. A real 403/404 on a GET makes the platform
 * interceptor navigate the whole page to `/403` — one tab would cost the user
 * the entire detail page.
 */
import { DatePicker } from "@/components/bs-ui/calendar/datePicker"
import { Button } from "@/components/bs-ui/button"
import { SearchInput } from "@/components/bs-ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { Switch } from "@/components/bs-ui/switch"
import {
  getHostedAppErrorCode,
  getHostedAppErrorMessage,
  getHostedAppLogsApi,
  HOSTED_APP_ERROR,
} from "@/controllers/API/hostedApp"
import { RefreshCw } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

/** Auto-refresh cadence. There is no `usePolling` helper in this app. */
const POLL_INTERVAL_MS = 10_000

const TAIL_OPTIONS = [200, 500, 1000, 2000]

interface LogsTabProps {
  appId: string
}

export function LogsTab({ appId }: LogsTabProps) {
  const { t } = useTranslation()
  const [lines, setLines] = useState<string[]>([])
  const [keyword, setKeyword] = useState("")
  const [since, setSince] = useState<Date | null>(null)
  const [tail, setTail] = useState(500)
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [forbidden, setForbidden] = useState(false)
  const [failure, setFailure] = useState("")
  const [autoRefresh, setAutoRefresh] = useState(false)

  // Read through a ref so the polling effect does not have to be torn down and
  // rebuilt every time a filter changes.
  const queryRef = useRef({ keyword, since, tail })
  queryRef.current = { keyword, since, tail }

  const load = useCallback(() => {
    setLoading(true)
    const { keyword: kw, since: from, tail: size } = queryRef.current
    getHostedAppLogsApi(appId, {
      tail: size,
      keyword: kw.trim() || undefined,
      since: from ? String(Math.floor(from.getTime() / 1000)) : undefined,
    })
      .then((data) => {
        setLines(data?.lines || [])
        setForbidden(false)
        setFailure("")
      })
      .catch((error) => {
        setLines([])
        if (getHostedAppErrorCode(error) === HOSTED_APP_ERROR.LOG_FORBIDDEN) {
          setForbidden(true)
          setFailure("")
          setAutoRefresh(false)
        } else {
          setForbidden(false)
          setFailure(
            getHostedAppErrorMessage(error) || t("hostedApp.logs.loadFailed"),
          )
        }
      })
      .finally(() => {
        setLoading(false)
        setLoaded(true)
      })
  }, [appId, t])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(load, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [autoRefresh, load])

  const handleReset = () => {
    setKeyword("")
    setSince(null)
    queryRef.current = { keyword: "", since: null, tail }
    load()
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 pb-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-56">
          <DatePicker
            showTime
            value={since || ""}
            placeholder={t("hostedApp.logs.sincePlaceholder")}
            onChange={(date) => setSince(date)}
          />
        </div>
        <SearchInput
          className="w-64"
          value={keyword}
          placeholder={t("hostedApp.logs.keywordPlaceholder")}
          onChange={(event) => setKeyword(event.target.value)}
        />
        <Select value={String(tail)} onValueChange={(value) => setTail(Number(value))}>
          <SelectTrigger className="w-28">
            <SelectValue placeholder={t("hostedApp.logs.tail")} />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {TAIL_OPTIONS.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  {t("hostedApp.logs.tailLines", { lines: option })}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        <Button variant="outline" size="sm" disabled={loading} onClick={load}>
          <RefreshCw className={`mr-1 size-3.5 ${loading ? "animate-spin" : ""}`} />
          {t("hostedApp.logs.refresh")}
        </Button>
        <Button variant="ghost" size="sm" onClick={handleReset}>
          {t("hostedApp.logs.clear")}
        </Button>
        <label className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
          <Switch
            checked={autoRefresh}
            disabled={forbidden}
            onCheckedChange={setAutoRefresh}
          />
          {t("hostedApp.logs.autoRefresh")}
        </label>
      </div>

      <p className="text-xs text-muted-foreground">{t("hostedApp.logs.hint")}</p>

      <div className="min-h-0 flex-1 overflow-auto rounded-md border bg-[#1f2023] p-3">
        {forbidden ? (
          <p className="text-sm text-slate-300">{t("hostedApp.logs.forbidden")}</p>
        ) : failure ? (
          <p className="text-sm text-slate-300">{failure}</p>
        ) : loaded && lines.length === 0 ? (
          <p className="text-sm text-slate-400">{t("hostedApp.logs.empty")}</p>
        ) : (
          <pre className="whitespace-pre-wrap break-all font-mono text-xs leading-5 text-slate-100">
            {lines.join("\n")}
          </pre>
        )}
      </div>
    </div>
  )
}
