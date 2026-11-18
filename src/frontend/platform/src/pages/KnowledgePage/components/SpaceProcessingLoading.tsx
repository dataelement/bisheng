import { useTranslation } from "react-i18next";
import { LoadingState } from "@/components/bs-icons/loading/LoadingState";

interface SpaceProcessingLoadingProps {
  className?: string;
}

export function SpaceProcessingLoading({ className }: SpaceProcessingLoadingProps) {
  const { t } = useTranslation("bs");
  return (
    <LoadingState label={t("loading")} className={className} />
  );
}
