import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { PreviewDiagnostics } from '~/pages/knowledge/FilePreview/PreviewDiagnostics';
import { setPreviewDiagnosticEnabled } from '~/pages/knowledge/FilePreview/previewDiagnosticPreference';
import { PreviewDiagnosticSetting } from './PreviewDiagnosticSetting';

// Localization only: the preference, switch and collector remain real.
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));

describe('preview diagnostic settings entry', () => {
  beforeEach(() => setPreviewDiagnosticEnabled(false));
  afterEach(() => setPreviewDiagnosticEnabled(false));

  it('enables the mounted collector through settings and keeps both stop controls synchronized', () => {
    render(
      <MemoryRouter>
        <PreviewDiagnosticSetting />
        <PreviewDiagnostics open={false} fileId={null} spaceId="space-1" />
      </MemoryRouter>,
    );
    expect(screen.queryByText('preview_diagnostics.active')).toBeNull();
    const toggle = screen.getByRole('switch', { name: /preview_diagnostics.setting/ });
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    expect(screen.getByText('preview_diagnostics.active')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'preview_diagnostics.stop' }));
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    expect(screen.queryByText('preview_diagnostics.active')).toBeNull();
  });
});
