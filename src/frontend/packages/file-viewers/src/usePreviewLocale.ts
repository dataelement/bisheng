import { useTranslation } from 'react-i18next';
import type { PreviewLocale } from './viewerTypes';
export function usePreviewLocale(): PreviewLocale {
  const { t } = useTranslation('shared', { keyPrefix: 'knowledge.preview' });
  return {
    fileExpired: t('fileExpired'),
    loading: t('loading'),
    docLoading: t('docLoading'),
    failed: t('failed'),
    imageAlt: t('imageAlt'),
    htmlTitle: t('htmlTitle'),
    recognizedText: t('recognizedText'),
    entryText: t('entryText'),
    empty: t('empty'),
    unsupported: t('unsupported'),
    media: {
      download: t('media.download'),
      exit_fullscreen: t('media.exit_fullscreen'),
      fullscreen: t('media.fullscreen'),
      more: t('media.more'),
      mute: t('media.mute'),
      pause: t('media.pause'),
      picture_in_picture: t('media.picture_in_picture'),
      play: t('media.play'),
      playback_speed: t('media.playback_speed'),
      progress: t('media.progress'),
      unmute: t('media.unmute'),
      volume: t('media.volume'),
    },
    select: {
      emptyText: t('select.emptyText'),
      noMatchText: t('select.noMatchText'),
      loadingText: t('select.loadingText'),
      clearLabel: t('select.clearLabel'),
      removeLabel: t('select.removeLabel'),
    },
  };
}
