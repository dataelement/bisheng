import { useMemo } from "react";
import type { DepartmentUserCandidateSource } from "@/components/bs-comp/selectComponent/DepartmentUsersSelect";
import {
  listServiceAccountOwnerCandidatesApi,
  type ServiceAccountRequestScope,
} from "@/controllers/API/serviceAccount";

export function useServiceAccountOwnerCandidates(
  scope: ServiceAccountRequestScope,
): DepartmentUserCandidateSource {
  return useMemo(
    () => ({
      cacheKey: `service-account-owners:${scope.tenantId}`,
      fetchPage: (keyword: string, page: number, signal: AbortSignal) =>
        listServiceAccountOwnerCandidatesApi(
          { keyword: keyword || undefined, page, page_size: 50 },
          scope,
          signal,
        ),
    }),
    [scope],
  );
}
