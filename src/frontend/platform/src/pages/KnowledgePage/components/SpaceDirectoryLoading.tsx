import { directoryLoadingStyles } from "@bisheng/knowledge";
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
      className={`${directoryLoadingStyles.frame} ${fill ? "min-h-0 flex-1" : "py-6"}`}
    >
      <span aria-hidden="true"><LoadingIcon className={directoryLoadingStyles.icon} /></span>
      <p>{t("f118.loading_directory")}</p>
    </div>
  );
}
