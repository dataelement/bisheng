import type { TFunction } from "i18next"

import type {
  PermissionCatalogAction,
  PermissionCatalogModel,
} from "@/controllers/API/permission"
import { actionLabel } from "./actionLabels"

/**
 * Turn a raw publish blocker into guidance an administrator can act on.
 *
 * The backend reports release blockers as stable English strings keyed by the
 * model's stable key and raw action codes, e.g.
 *   "custom model 27b7…f37 selects unavailable actions: download"
 *   "active custom model only-edit has no effective actions"
 * Rendering those verbatim (as the dialog used to) left the operator staring at
 * a hash and a code with no idea that the fix is to edit that custom permission
 * first. Here we recognise the known shapes, resolve the model's display name
 * and the localized action names, and explain the required next step. Anything
 * we do not recognise falls back to the original string so a new blocker is
 * never swallowed silently.
 */

const UNAVAILABLE_ACTIONS = /^custom model (.+) selects unavailable actions: (.+)$/
const NO_EFFECTIVE_ACTIONS = /^active custom model (.+) has no effective actions$/

interface BlockerContext {
  models?: PermissionCatalogModel[]
  actions?: PermissionCatalogAction[]
}

function modelName(
  models: PermissionCatalogModel[] | undefined,
  modelKey: string,
): string {
  return models?.find((model) => model.key === modelKey)?.name || modelKey
}

function actionNames(
  t: TFunction,
  actions: PermissionCatalogAction[] | undefined,
  codes: string[],
): string {
  const byCode = new Map(actions?.map((action) => [action.code, action]) ?? [])
  return codes
    .map((code) => actionLabel(t, code, byCode.get(code)?.name))
    .join("、")
}

export function formatBlockerMessage(
  t: TFunction,
  blocker: string,
  context: BlockerContext = {},
): string {
  const { models, actions } = context

  const unavailable = blocker.match(UNAVAILABLE_ACTIONS)
  if (unavailable) {
    const [, modelKey, codeList] = unavailable
    const codes = codeList
      .split(",")
      .map((code) => code.trim())
      .filter(Boolean)
    return t("impact.blockerUnavailableActions", {
      model: modelName(models, modelKey),
      actions: actionNames(t, actions, codes),
    })
  }

  const empty = blocker.match(NO_EFFECTIVE_ACTIONS)
  if (empty) {
    const [, modelKey] = empty
    return t("impact.blockerNoEffectiveActions", {
      model: modelName(models, modelKey),
    })
  }

  return blocker
}
