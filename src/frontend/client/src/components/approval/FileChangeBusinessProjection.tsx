import type { ApprovalInstanceDetail, ApprovalTaskDetail } from "~/api/approval";
import { useLocalize } from "~/hooks";

import { parseFileChangeBusinessProjection } from "./approvalCenterFileChangeUtils";

interface FileChangeBusinessProjectionProps {
  detail: ApprovalTaskDetail | ApprovalInstanceDetail;
  localize: ReturnType<typeof useLocalize>;
}

export function FileChangeBusinessProjection({
  detail,
  localize,
}: FileChangeBusinessProjectionProps) {
  const projection = parseFileChangeBusinessProjection(
    detail.scenario_code,
    detail.business_status_projection,
  );
  if (!projection) return null;

  return (
    <div>
      <div className="mb-2 text-[14px] font-medium text-text-primary">
        {localize("com_knowledge.file_change_business_status")}
      </div>
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-[#f2f3f5] bg-[#f2f3f5]">
        <div className="bg-white px-3 py-2">
          <div className="text-[12px] text-[#86909c]">
            {localize("com_knowledge.file_change_status")}
          </div>
          <div className="mt-1 text-[14px] font-medium text-text-primary break-all">
            {localize(`com_knowledge.file_change_status_${projection.status}`)}
          </div>
        </div>
        {projection.failureReason ? (
          <div className="bg-white px-3 py-2">
            <div className="text-[12px] text-[#86909c]">
              {localize("com_knowledge.file_change_failure_reason")}
            </div>
            <div className="mt-1 text-[14px] font-medium text-text-primary break-all">
              {projection.failureReason}
            </div>
          </div>
        ) : <div className="bg-white" />}
      </div>
    </div>
  );
}
