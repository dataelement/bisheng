import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ComposerConfigNotice } from './ComposerConfigNotice';

jest.mock('~/hooks/useLocalize', () => ({ __esModule: true, default: () => (key: string) => key }));
jest.mock('~/api/request', () => ({ showApiError: jest.fn() }));

const failure = new Error('Invalid resource type or ID');

it('explains a failed config request and offers a retry', async () => {
  const onRetry = jest.fn();
  render(<ComposerConfigNotice error={failure} loaded={false} hasModels={false} onRetry={onRetry} />);

  expect(screen.getByRole('alert')).toHaveTextContent('dshChat.configLoadFailed');
  // The raw backend message is not what the user needs to read here.
  expect(screen.queryByText(failure.message)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'com_ui_retry' }));
  await waitFor(() => expect(onRetry).toHaveBeenCalledTimes(1));
});

it('reports a failed retry instead of dropping it', async () => {
  const { showApiError } = jest.requireMock('~/api/request');
  const again = new Error('still failing');
  render(<ComposerConfigNotice error={failure} loaded={false} hasModels={false} onRetry={() => Promise.reject(again)} />);

  fireEvent.click(screen.getByRole('button', { name: 'com_ui_retry' }));
  await waitFor(() => expect(showApiError).toHaveBeenCalledWith(again));
});

it('says no model is configured once the config has loaded without one', () => {
  render(<ComposerConfigNotice error={null} loaded hasModels={false} onRetry={jest.fn()} />);

  expect(screen.getByText('dshChat.noModelsConfigured')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'com_ui_retry' })).toBeNull();
});

it('prefers the load failure over the empty-model notice', () => {
  render(<ComposerConfigNotice error={failure} loaded hasModels={false} onRetry={jest.fn()} />);

  expect(screen.getByText('dshChat.configLoadFailed')).toBeInTheDocument();
  expect(screen.queryByText('dshChat.noModelsConfigured')).toBeNull();
});

it.each([
  ['while the config is still loading', { error: null, loaded: false, hasModels: false }],
  ['when models are available', { error: null, loaded: true, hasModels: true }],
  ['when a refresh fails but an earlier config still has models', { error: failure, loaded: true, hasModels: true }],
])('renders nothing %s', (_, props) => {
  const { container } = render(<ComposerConfigNotice {...props} onRetry={jest.fn()} />);

  expect(container).toBeEmptyDOMElement();
});
