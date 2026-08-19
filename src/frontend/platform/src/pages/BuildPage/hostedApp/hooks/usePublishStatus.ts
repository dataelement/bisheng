/**
 * Release state of one hosted application (AC-38).
 *
 * Kept apart from `useHostedApp` on purpose. The detail payload *is* the page —
 * without it there is nothing to render — while the release read model is one
 * more card: a viewer who may see the application but not its release gets a
 * business refusal, and the page has to stay up around that. Merging the two
 * loads would turn a refused card into a blank page.
 *
 * Plain `useState` / `useEffect`: react-query v3 is frozen by lint in this app
 * and the @tanstack migration has not happened, so new data fetching gets
 * neither.
 */
import {
  getHostedAppErrorCode,
  getHostedAppErrorMessage,
  getPublishStatusApi,
  HOSTED_APP_ERROR,
  type HostedAppPublishStatus,
} from "@/controllers/API/hostedApp"
import { useCallback, useEffect, useState } from "react"

export interface UsePublishStatusResult {
  status: HostedAppPublishStatus | null
  loading: boolean
  /** The caller may see the application but not its release state. */
  forbidden: boolean
  /** The backend's own copy, when it sent any. */
  errorMessage: string
  reload: () => void
}

export function usePublishStatus(
  appId: string | undefined,
): UsePublishStatusResult {
  const [status, setStatus] = useState<HostedAppPublishStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [forbidden, setForbidden] = useState(false)
  const [errorMessage, setErrorMessage] = useState("")

  const reload = useCallback(() => {
    if (!appId) {
      setLoading(false)
      return
    }
    setLoading(true)
    getPublishStatusApi(appId)
      .then((data) => {
        setStatus(data)
        setForbidden(false)
        setErrorMessage("")
      })
      .catch((error) => {
        setStatus(null)
        const code = getHostedAppErrorCode(error)
        // 16254 covers both "not visible to you" and "no such application";
        // the page shell has already decided which of those it is, so this
        // hook only needs to know that the card must not pretend to be empty.
        setForbidden(
          code === HOSTED_APP_ERROR.PUBLISH_OWNER_ONLY ||
            code === HOSTED_APP_ERROR.OWNER_ONLY ||
            code === HOSTED_APP_ERROR.MANAGE_FORBIDDEN,
        )
        setErrorMessage(getHostedAppErrorMessage(error))
      })
      .finally(() => setLoading(false))
  }, [appId])

  useEffect(() => {
    reload()
  }, [reload])

  return { status, loading, forbidden, errorMessage, reload }
}
