import { createContext, useContext, type ReactNode } from 'react';

export interface LoadingIndicatorProps {
  className?: string;
}

export type LoadingIndicatorRenderer = (props: LoadingIndicatorProps) => ReactNode;

interface LoadingIndicatorProviderProps {
  children: ReactNode;
  renderIndicator: LoadingIndicatorRenderer;
}

const LoadingIndicatorContext = createContext<LoadingIndicatorRenderer | undefined>(undefined);

/** Optional host-specific artwork; controls retain their own loading behavior. */
export function LoadingIndicatorProvider({ children, renderIndicator }: LoadingIndicatorProviderProps) {
  return <LoadingIndicatorContext.Provider value={renderIndicator}>{children}</LoadingIndicatorContext.Provider>;
}

export function useLoadingIndicatorRenderer() {
  return useContext(LoadingIndicatorContext);
}
