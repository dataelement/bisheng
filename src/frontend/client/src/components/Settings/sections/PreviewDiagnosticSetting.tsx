import { useSyncExternalStore } from 'react';
import { Switch } from '@bisheng/ui';
import { useLocalize } from '~/hooks';
import {
  getPreviewDiagnosticEnabled,
  setPreviewDiagnosticEnabled,
  subscribePreviewDiagnosticPreference,
} from '~/pages/knowledge/FilePreview/previewDiagnosticPreference';

export function PreviewDiagnosticSetting() {
  const localize = useLocalize();
  const enabled = useSyncExternalStore(
    subscribePreviewDiagnosticPreference,
    getPreviewDiagnosticEnabled,
    () => false,
  );
  return (
    <div className="flex min-h-11 items-center justify-between gap-4">
      <label htmlFor="preview-diagnostic-setting" className="text-body text-text-1">
        {localize('preview_diagnostics.setting')}
        <span id="preview-diagnostic-description" className="mt-1 block text-caption text-text-3">
          {localize('preview_diagnostics.setting_hint')}
        </span>
      </label>
      <Switch id="preview-diagnostic-setting" checked={enabled}
        aria-describedby="preview-diagnostic-description"
        onCheckedChange={setPreviewDiagnosticEnabled} />
    </div>
  );
}
