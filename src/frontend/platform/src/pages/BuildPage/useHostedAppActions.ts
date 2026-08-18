/**
 * The three operational actions on a hosted application — stop, resume, delete
 * — together with their confirmation copy.
 *
 * The card and the detail page's publish tab both call this hook rather than
 * writing their own dialogs: the copy is part of the contract (the offline
 * dialog has to say the entry and the square will show "offline"; the delete
 * dialog has to say code, conversation history and production data all go), and
 * two copies of it drift within one release.
 *
 * Each action resolves to `true` only when the state actually changed, so a
 * caller can drive an optimistic switch off the return value. A user who
 * cancels the dialog gets `false`, which is not an error.
 */
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { toast } from "@/components/bs-ui/toast/use-toast"
import {
  deleteHostedAppApi,
  getHostedAppErrorMessage,
  manualPublishHostedAppApi,
  resumeHostedAppApi,
  stopHostedAppApi,
  type HostedAppActionResult,
} from "@/controllers/API/hostedApp"
import { useCallback } from "react"
import { useTranslation } from "react-i18next"
import type { HostedAppRef } from "./hostedApp/types"

export type HostedAppActionKind = "stop" | "resume" | "manualPublish" | "delete"

type ActionKind = HostedAppActionKind

interface UseHostedAppActionsOptions {
  /**
   * Called after every attempt, successful or not, with the server's own
   * verdict — `null` when the call failed.
   *
   * A failure is reported too because the most common one *is* a state change:
   * the action already landed and this second attempt lost the race (16102).
   * Staying silent there is what leaves the card showing a state the server
   * abandoned until the user reloads the page by hand.
   */
  onChanged?: (kind: ActionKind, result: HostedAppActionResult | null) => void
}

interface ConfirmSpec {
  title: string
  desc: string
  okTxt: string
}

function confirmAsync(spec: ConfirmSpec): Promise<boolean> {
  return new Promise((resolve) => {
    bsConfirm({
      title: spec.title,
      desc: spec.desc,
      okTxt: spec.okTxt,
      onOk(next) {
        // Resolve before closing: `next()` also fires `onClose`, and the first
        // settle of a promise is the one that counts.
        resolve(true)
        next()
      },
      onCancel() {
        resolve(false)
      },
      onClose() {
        resolve(false)
      },
    })
  })
}

export function useHostedAppActions(options: UseHostedAppActionsOptions = {}) {
  const { t } = useTranslation()
  const { onChanged } = options

  const run = useCallback(
    async (
      kind: ActionKind,
      appId: string,
      call: (id: string) => Promise<HostedAppActionResult>,
    ): Promise<boolean> => {
      try {
        const result = await call(appId)
        // `ok: false` is a handled outcome, not a transport failure: the app was
        // parked for capacity or failed to start, and `reason` explains it.
        if (result && result.ok === false) {
          toast({
            title: t("prompt"),
            variant: "warning",
            description:
              result.reason || t("hostedApp.actions.capacityShortage"),
          })
        } else {
          toast({
            title: t("prompt"),
            variant: "success",
            description: t(`hostedApp.actions.done.${kind}`),
          })
        }
        onChanged?.(kind, result)
        return true
      } catch (error) {
        toast({
          title: t("prompt"),
          variant: "error",
          description:
            getHostedAppErrorMessage(error) || t("hostedApp.actions.failed"),
        })
        onChanged?.(kind, null)
        return false
      }
    },
    [onChanged, t],
  )

  const stopApp = useCallback(
    async (app: HostedAppRef): Promise<boolean> => {
      const confirmed = await confirmAsync({
        title: t("hostedApp.actions.stopTitle"),
        desc: t("hostedApp.actions.stopDesc", { name: app.name }),
        okTxt: t("hostedApp.actions.stopOk"),
      })
      if (!confirmed) return false
      return run("stop", app.appId, stopHostedAppApi)
    },
    [run, t],
  )

  const resumeApp = useCallback(
    async (app: HostedAppRef): Promise<boolean> => {
      const confirmed = await confirmAsync({
        title: t("hostedApp.actions.resumeTitle"),
        desc: t("hostedApp.actions.resumeDesc", { name: app.name }),
        okTxt: t("hostedApp.actions.resumeOk"),
      })
      if (!confirmed) return false
      return run("resume", app.appId, resumeHostedAppApi)
    },
    [run, t],
  )

  /** Retry an application parked for capacity, without a second approval. */
  const manualPublishApp = useCallback(
    async (app: HostedAppRef): Promise<boolean> => {
      const confirmed = await confirmAsync({
        title: t("hostedApp.actions.manualPublishTitle"),
        desc: t("hostedApp.actions.manualPublishDesc", { name: app.name }),
        okTxt: t("hostedApp.actions.manualPublishOk"),
      })
      if (!confirmed) return false
      return run("manualPublish", app.appId, manualPublishHostedAppApi)
    },
    [run, t],
  )

  /**
   * AC-43 — no name to type in, but the copy must spell out what goes with it.
   */
  const deleteApp = useCallback(
    async (app: HostedAppRef): Promise<boolean> => {
      const confirmed = await confirmAsync({
        title: t("hostedApp.actions.deleteTitle"),
        desc: t("hostedApp.actions.deleteDesc", { name: app.name }),
        okTxt: t("hostedApp.actions.deleteOk"),
      })
      if (!confirmed) return false
      return run("delete", app.appId, deleteHostedAppApi)
    },
    [run, t],
  )

  return { stopApp, resumeApp, manualPublishApp, deleteApp }
}
