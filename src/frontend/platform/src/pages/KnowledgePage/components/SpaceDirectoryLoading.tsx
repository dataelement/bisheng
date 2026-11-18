import { useTranslation } from "react-i18next";
import { LoadingIcon } from "@/components/bs-icons/loading";

interface SpaceDirectoryLoadingProps {
  fill: boolean;
}

export function SpaceDirectoryLoading({ fill }: SpaceDirectoryLoadingProps) {
  const { t } = useTranslation("knowledge");
  return (
    <div
      role="status"
      aria-busy="true"
      className={`flex flex-col items-center justify-center gap-4 px-4 text-center text-body text-text-3 ${fill ? "min-h-0 flex-1" : "py-6"}`}
    >
      <span aria-hidden="true"><LoadingIcon className="size-20 max-w-none shrink-0" /></span>
      <p>{t("f118.loading_directory")}</p>
    </div>
  );
}
