import { useTranslation } from "react-i18next";
import { LoadingState } from "@/components/bs-icons/loading/LoadingState";

interface SpaceDirectoryLoadingProps {
  fill: boolean;
}

export function SpaceDirectoryLoading({ fill }: SpaceDirectoryLoadingProps) {
  const { t } = useTranslation("knowledge");
  return (
    <LoadingState
      size="page"
      label={t("f118.loading_directory")}
      className={fill ? "min-h-0 flex-1" : "py-6"}
    />
  );
}
