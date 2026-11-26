import type { ReactNode } from "react";
import { LoadingIndicatorProvider } from "@bisheng/ui";
import { PreviewLoadingProvider, type PreviewLoadingOptions } from "@bisheng/file-viewers/loading";
import { cname } from "@/components/bs-ui/utils";
import { LoadingIcon } from ".";
import { LoadingState } from "./LoadingState";

interface PlatformLoadingProviderProps {
  children: ReactNode;
}

const renderIndicator = ({ className }: { className?: string }) => (
  <LoadingIcon className={cname("size-4 max-w-none shrink-0 text-current", className)} />
);
const renderPreviewLoading = (options: PreviewLoadingOptions) => (
  <LoadingState {...options} className="h-full" />
);

export function PlatformLoadingProvider({ children }: PlatformLoadingProviderProps) {
  return (
    <LoadingIndicatorProvider renderIndicator={renderIndicator}>
      <PreviewLoadingProvider renderLoading={renderPreviewLoading}>
        {children}
      </PreviewLoadingProvider>
    </LoadingIndicatorProvider>
  );
}
