import { useTranslation } from "react-i18next";
import { cname } from "@/components/bs-ui/utils";
import { LoadingIcon } from ".";

interface LoadingStateProps {
  size?: "page" | "panel" | "inline";
  label?: string;
  className?: string;
}

const frames = {
  page: "flex min-h-0 w-full flex-1 items-center justify-center",
  panel: "flex min-h-32 w-full items-center justify-center",
  inline: "inline-flex size-4 shrink-0 items-center justify-center align-middle",
};
const icons = { page: "size-20", panel: "size-10", inline: "size-4" };

export function LoadingState({ size = "panel", label, className }: LoadingStateProps) {
  const { t } = useTranslation("bs");
  return (
    <span
      role="status"
      aria-label={label ?? t("loading")}
      aria-busy="true"
      className={cname(frames[size], className)}
    >
      <span aria-hidden="true" className="inline-flex">
        <LoadingIcon className={`${icons[size]} max-w-none shrink-0`} />
      </span>
    </span>
  );
}
