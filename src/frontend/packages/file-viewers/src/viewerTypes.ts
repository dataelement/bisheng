import type { PreviewResource } from './types';
export interface PreviewLocale {
  fileExpired: string; loading: string; docLoading: string; failed: string; empty: string;
  media: MediaPlayerLabels; select: MediaSelectLabels;
  imageAlt: string; htmlTitle: string; unsupported: string; recognizedText: string; entryText: string;
}
export interface PreviewViewerProps {
  resource: PreviewResource;
  zoomLevel?: number;
  locale: PreviewLocale;
  onError?: (error: unknown) => void;
}

export interface MediaPlayerLabels {
  download: string;
  exit_fullscreen: string;
  fullscreen: string;
  more: string;
  mute: string;
  pause: string;
  picture_in_picture: string;
  play: string;
  playback_speed: string;
  progress: string;
  unmute: string;
  volume: string;
}
export interface MediaSelectLabels { emptyText: string; noMatchText: string; loadingText: string; clearLabel: string; removeLabel: string }
