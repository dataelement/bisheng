import { DSH_BROWSER_CONFIG_QUERY_KEY, shouldRetryApiError, subscribeDshBrowserConfigChanges } from '@bisheng/api-client';
import { useEffect, useState } from 'react';
import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DndProvider } from 'react-dnd';
import { HTML5Backend } from 'react-dnd-html5-backend';
import { RouterProvider } from 'react-router-dom';
import { RecoilRoot } from 'recoil';
import { LiveAnnouncer } from '~/a11y';
import Toast from './components/ui/Toast';
import Notification from './components/ui/Notification';
import { SystemMaintenanceOverlay } from './components/SystemMaintenanceOverlay';
import { ScreenshotProvider, ThemeProvider, useApiErrorBoundary } from './hooks';
import { ToastProvider, ConfirmProvider } from './Providers';
import { SessionKickListener } from './components/Auth/SessionKickListener';
import { router } from './routes';

const App = () => {
  const { setError } = useApiErrorBoundary();

  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => shouldRetryApiError(error) && failureCount < 3,
      },
    },
    queryCache: new QueryCache({
      onError: (error) => {
        if (error?.response?.status === 401) {
          setError(error);
        }
      },
    }),
  }));

  useEffect(() => subscribeDshBrowserConfigChanges(() => {
    void queryClient.invalidateQueries({ queryKey: DSH_BROWSER_CONFIG_QUERY_KEY });
  }), [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      <RecoilRoot>
        <LiveAnnouncer>
          <ThemeProvider>
            <SystemMaintenanceOverlay>
              <ConfirmProvider>
                <SessionKickListener />
                <ToastProvider>
                  <DndProvider backend={HTML5Backend}>
                    <RouterProvider router={router} />
                    {/* <ReactQueryDevtools initialIsOpen={false} position="top-right" /> */}
                    {/* Single toast container, always mounted — its live regions
                        have to pre-exist the messages they announce. */}
                    <Toast />
                    {/* Same for the top-right notification stack. */}
                    <Notification />
                  </DndProvider>
                </ToastProvider>
              </ConfirmProvider>
            </SystemMaintenanceOverlay>
          </ThemeProvider>
        </LiveAnnouncer>
      </RecoilRoot>
    </QueryClientProvider>
  );
};

export default () => (
  <ScreenshotProvider>
    <App />
  </ScreenshotProvider>
);
