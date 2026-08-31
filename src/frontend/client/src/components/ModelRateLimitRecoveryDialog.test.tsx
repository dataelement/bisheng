/** @jest-environment node */

import { renderToStaticMarkup } from 'react-dom/server';
import type { WorkbenchModelOption } from './Chat/ModelAvailabilityOption';
import {
  getRecoveryModelCandidates,
  isRecoveryConfirmationAccepted,
} from './modelRateLimitRecoveryDialogHelpers';
import { ModelRateLimitRecoveryDialog } from './ModelRateLimitRecoveryDialog';

jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => ({
    'com_message.still_busy_title': 'The current model has not recovered',
    'com_message.still_busy_desc': 'Switch models to continue. Your input and progress are preserved.',
    'com_message.switch_model': 'Switch model',
    'com_message.try_later': 'Try later',
    'com_message.choose_model': 'Choose a model',
    'com_message.model_busy_suffix': ' · Service busy',
  })[key] ?? key,
}));

jest.mock('~/components/ui/Dialog', () => ({
  Dialog: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
  DialogContent: ({ children }: React.PropsWithChildren) => <section>{children}</section>,
  DialogDescription: ({ children }: React.PropsWithChildren) => <p>{children}</p>,
  DialogFooter: ({ children }: React.PropsWithChildren) => <footer>{children}</footer>,
  DialogHeader: ({ children }: React.PropsWithChildren) => <header>{children}</header>,
  DialogTitle: ({ children }: React.PropsWithChildren) => <h2>{children}</h2>,
}));

jest.mock('~/components/ui/Select', () => ({
  Select: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
  SelectContent: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
  SelectItem: ({ children, value }: React.PropsWithChildren<{ value: string }>) => (
    <div data-value={value}>{children}</div>
  ),
  SelectTrigger: ({ children }: React.PropsWithChildren) => <button>{children}</button>,
  SelectValue: ({ placeholder }: { placeholder: string }) => <span>{placeholder}</span>,
}));

jest.mock('~/components/ui/Button', () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
}));

function model(
  id: string,
  values: Partial<WorkbenchModelOption> = {},
): WorkbenchModelOption {
  return {
    key: 'model',
    id,
    name: `model-${id}`,
    displayName: `Model ${id}`,
    ...values,
  };
}

describe('ModelRateLimitRecoveryDialog', () => {
  it('filters current, busy, duplicate, and incompatible candidates', () => {
    const candidates = getRecoveryModelCandidates(
      [
        model('1'),
        model('2', { rateLimitState: 'busy' }),
        model('3'),
        model('4'),
        model('4'),
        model('5'),
      ],
      '1',
      (candidate) => candidate.id !== '5',
    );
    expect(candidates.map((candidate) => candidate.id)).toEqual(['3', '4']);
  });

  it('renders the exact third-rate-limit message and two actions', () => {
    const markup = renderToStaticMarkup(
      <ModelRateLimitRecoveryDialog
        open
        models={[model('1'), model('2')]}
        currentModelId="1"
        onOpenChange={() => undefined}
        onConfirm={() => Promise.resolve()}
        onLater={() => undefined}
      />,
    );
    expect(markup).toContain('The current model has not recovered');
    expect(markup).toContain('Switch models to continue. Your input and progress are preserved.');
    expect(markup).toContain('Switch model');
    expect(markup).toContain('Try later');
    expect(markup).toContain('data-value="2"');
  });

  it('treats an explicit server rejection as a failed confirmation', () => {
    expect(isRecoveryConfirmationAccepted({ accepted: false })).toBe(false);
    expect(isRecoveryConfirmationAccepted(false)).toBe(false);
    expect(isRecoveryConfirmationAccepted({ accepted: true })).toBe(true);
    expect(isRecoveryConfirmationAccepted(undefined)).toBe(true);
  });
});
