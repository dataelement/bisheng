// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ExcelPreview } from './ExcelPreview';
import { PreviewLoadingProvider, type PreviewLoadingOptions } from './PreviewLoading';
import { VersionDiffView } from './VersionDiffView';
import { PdfViewer } from './pdf/PdfViewer';
import { PreviewState } from './viewers/PreviewState';
import { MediaTranscriptTabs } from './viewers/MediaTranscriptTabs';
import { TextViewer } from './viewers/TextViewer';
import type { PreviewLocale } from './viewerTypes';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const locale: PreviewLocale = {
  fileExpired: 'Expired', loading: 'Loading preview', docLoading: 'Loading document', failed: 'Preview failed',
  empty: 'Empty', imageAlt: 'Image', htmlTitle: 'HTML', unsupported: 'Unsupported',
  recognizedText: 'Recognized', entryText: 'Entry',
  media: {
    download: 'Download', exit_fullscreen: 'Exit', fullscreen: 'Fullscreen', more: 'More', mute: 'Mute',
    pause: 'Pause', picture_in_picture: 'Picture in picture', play: 'Play', playback_speed: 'Speed',
    progress: 'Progress', unmute: 'Unmute', volume: 'Volume',
  },
  select: { emptyText: 'Empty', noMatchText: 'No match', loadingText: 'Loading', clearLabel: 'Clear', removeLabel: 'Remove' },
};

const renderLoading = ({ label, size }: PreviewLoadingOptions) => (
  <span role="status" aria-label={label} data-size={size} data-testid="configured-loading" />
);

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('scopes the configured indicator to its host and preserves default copy and failures', () => {
  render(<>
    <PreviewLoadingProvider renderLoading={renderLoading}>
      <PreviewState loading locale={locale} />
      <PreviewState loading={false} locale={locale} />
    </PreviewLoadingProvider>
    <PreviewState loading locale={locale} />
  </>);
  expect(screen.getByTestId('configured-loading').getAttribute('aria-label')).toBe(locale.loading);
  expect(screen.getAllByText(locale.loading)).toHaveLength(1);
  expect(screen.getByRole('alert').textContent).toBe(locale.failed);
});

it('uses the host indicator only while a text resource is loading', async () => {
  let finish!: (response: { ok: boolean; text: () => Promise<string> }) => void;
  vi.stubGlobal('fetch', vi.fn(() => new Promise((resolve) => { finish = resolve; })));
  render(<PreviewLoadingProvider renderLoading={renderLoading}>
    <TextViewer resource={{ originalUrl: '/text-loading', previewUrl: '/text-loading' }} locale={locale} />
  </PreviewLoadingProvider>);
  expect(screen.queryByText(locale.loading)).toBeNull();
  expect(screen.getByTestId('configured-loading')).toBeTruthy();
  await act(async () => finish({ ok: true, text: async () => 'Loaded file contents' }));
  expect(await screen.findByText('Loaded file contents')).toBeTruthy();
  expect(screen.queryByTestId('configured-loading')).toBeNull();
});

it('applies host indicators to PDF, workbook, transcript and version comparison loading branches', () => {
  vi.stubGlobal('fetch', vi.fn(() => new Promise(() => undefined)));
  render(<PreviewLoadingProvider renderLoading={renderLoading}>
    <PdfViewer pdfDoc={null} loadingText="Loading PDF" zoomLevel={1} targetPage={null} onCurrentPageChange={vi.fn()} />
    <ExcelPreview filePath="/workbook-loading.xlsx" />
    <MediaTranscriptTabs resource={{ originalUrl: '/clip', previewUrl: '/transcript-loading' }} locale={locale} />
    <VersionDiffView summary={null} files={[]} patches={[]} loading />
  </PreviewLoadingProvider>);
  expect(screen.getAllByTestId('configured-loading').map((node) => node.getAttribute('data-size'))).toEqual(['page', 'page', 'panel', 'panel']);
  expect(screen.queryByText('Loading PDF')).toBeNull();
  expect(screen.queryByText('loading')).toBeNull();
  expect(screen.queryByText('supportedFormats')).toBeNull();
});
