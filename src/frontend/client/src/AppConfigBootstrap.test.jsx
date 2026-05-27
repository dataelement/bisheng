import { render, screen, waitFor } from '@testing-library/react';
import App from './App';
import { ApiErrorBoundaryProvider } from './hooks/ApiErrorBoundaryContext';

const mockGetBysConfigApi = jest.fn();

jest.mock('~/api/apps', () => ({
  getBysConfigApi: () => mockGetBysConfigApi(),
}));

jest.mock('./routes', () => ({
  router: {},
}));

jest.mock('react-router-dom', () => ({
  RouterProvider: () => {
    const { useVersionManagementEnabled } = require('~/hooks');
    return (
      <div data-testid="version-management-enabled">
        {String(useVersionManagementEnabled())}
      </div>
    );
  },
}));

describe('App config bootstrap', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.matchMedia = jest.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      addListener: jest.fn(),
      removeListener: jest.fn(),
    }));
    mockGetBysConfigApi.mockResolvedValue({
      data: {
        knowledges: {
          version_management: {
            enabled: true,
            simhash_similarity_threshold: 0.85,
          },
        },
      },
    });
  });

  test('loads Bisheng env config before standalone routes read feature flags', async () => {
    render(
      <ApiErrorBoundaryProvider>
        <App />
      </ApiErrorBoundaryProvider>,
    );

    await waitFor(() => expect(mockGetBysConfigApi).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      expect(screen.getByTestId('version-management-enabled')).toHaveTextContent('true');
    });
  });
});
