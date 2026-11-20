import { createContext, useContext, type ReactNode } from 'react';

export interface PreviewLoadingOptions {
  size?: 'page' | 'panel' | 'inline';
  label?: string;
}

export type PreviewLoadingRenderer = (options: PreviewLoadingOptions) => ReactNode;

interface PreviewLoadingProviderProps {
  children: ReactNode;
  renderLoading: PreviewLoadingRenderer;
}

const PreviewLoadingContext = createContext<PreviewLoadingRenderer | undefined>(undefined);

/** Hosts can supply their configured indicator without changing other apps. */
export function PreviewLoadingProvider({ children, renderLoading }: PreviewLoadingProviderProps) {
  return <PreviewLoadingContext.Provider value={renderLoading}>{children}</PreviewLoadingContext.Provider>;
}

export function usePreviewLoadingRenderer() {
  return useContext(PreviewLoadingContext);
}
