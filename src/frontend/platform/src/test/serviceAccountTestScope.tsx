import type { ReactElement } from "react"
import type { RenderOptions } from "@testing-library/react"
import { vi } from "vitest"
import type { ServiceAccountRequestScope } from "@/controllers/API/serviceAccount"
import { ServiceAccountRequestScopeContext } from "@/pages/SystemPage/components/ServiceAccount/useServiceAccountManagementScope"
import { render } from "@/test/test-utils"

/**
 * Service-account views read their tenant scope from a context that the page
 * admits before rendering (F113). Component-level tests have no page, so they
 * provide one concrete scope here.
 */
export const testServiceAccountScope: ServiceAccountRequestScope = {
  tenantId: 1,
  signal: new AbortController().signal,
  onScopeChanged: vi.fn(),
}

export function renderWithServiceAccountScope(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper">,
) {
  return render(
    <ServiceAccountRequestScopeContext.Provider value={testServiceAccountScope}>
      {ui}
    </ServiceAccountRequestScopeContext.Provider>,
    options,
  )
}

