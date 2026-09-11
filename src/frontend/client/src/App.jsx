import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DndProvider } from 'react-dnd';
import { HTML5Backend } from 'react-dnd-html5-backend';
import { RouterProvider } from 'react-router-dom';
import { RecoilRoot } from 'recoil';
import { LiveAnnouncer } from '~/a11y';
import Toast from './components/ui/Toast';
import { SystemMaintenanceOverlay } from './components/SystemMaintenanceOverlay';
import { ScreenshotProvider, ThemeProvider, useApiErrorBoundary } from './hooks';
import { ToastProvider, ConfirmProvider } from './Providers';
import { router } from './routes';

const App = () => {
  const { setError } = useApiErrorBoundary();

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
      },
    },
    queryCache: new QueryCache({
      onError: (error) => {
        if (error?.response?.status === 401) {
          setError(error);
        }
      },
    }),
  });

  return (
    <QueryClientProvider client={queryClient}>
      <RecoilRoot>
        <LiveAnnouncer>
          <ThemeProvider>
            <ConfirmProvider>
              <ToastProvider>
                <DndProvider backend={HTML5Backend}>
                  <RouterProvider router={router} />
                  {/* <ReactQueryDevtools initialIsOpen={false} position="top-right" /> */}
                  <SystemMaintenanceOverlay />
                  {/* Single toast container, always mounted — its live regions
                      have to pre-exist the messages they announce. */}
                  <Toast />
                </DndProvider>
              </ToastProvider>
            </ConfirmProvider>
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
