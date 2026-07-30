import type { ApprovalFlowNodeApprover } from "~/api/approval";
import useLocalize from "~/hooks/useLocalize";

interface FutureApproverListProps {
  approvers: ApprovalFlowNodeApprover[];
  localize: ReturnType<typeof useLocalize>;
}

export function FutureApproverList({
  approvers,
  localize,
}: FutureApproverListProps) {
  if (approvers.length === 0) {
    return (
      <div className="mt-0.5 text-[12px] text-[#86909c]">
        {localize("com_approval_node_not_started")}
      </div>
    );
  }

  return (
    <div className="mt-2 space-y-1.5">
      {approvers.map((approver) => (
        <div
          key={approver.user_id}
          className="rounded-lg border border-[#f2f3f5] bg-[#fafbfc] px-3 py-2"
        >
          <div className="flex items-center gap-1.5">
            <span className="text-[12px] font-bold text-[#c9cdd4]">●</span>
            <span className="text-[13px] text-[#1d2129]">
              {approver.user_name || String(approver.user_id)}
            </span>
            <span className="text-[12px] text-[#86909c]">
              {localize("com_approval_node_not_started")}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
