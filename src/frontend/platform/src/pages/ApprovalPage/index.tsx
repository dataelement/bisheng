import { ApprovalPageView } from "./ApprovalPageView";
import { useApprovalController } from "./useApprovalController";
export default function ApprovalPage() {
  return <ApprovalPageView controller={useApprovalController()} />;
}
