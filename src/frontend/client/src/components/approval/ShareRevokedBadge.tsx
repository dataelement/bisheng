import useLocalize from "~/hooks/useLocalize";

export function ShareRevokedBadge({ revoked }: { revoked?: boolean }) {
  const localize = useLocalize();
  return revoked ? (
    <span className="rounded-full bg-[#f7f8fa] px-2 py-0.5 text-[12px] font-medium text-[#86909c]">
      {localize("com_approval_status_withdrawn")}
    </span>
  ) : null;
}
