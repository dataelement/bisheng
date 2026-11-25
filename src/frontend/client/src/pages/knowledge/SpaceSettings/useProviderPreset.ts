import { useEffect, useState } from 'react';
import { previewProviderPreset, type ReviewedPreset } from '~/api/knowledgeProviderSettings';

export function useProviderPreset(enabled: boolean) {
  const [preset, setPreset] = useState<ReviewedPreset | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setPreset(null);
    setFailed(false);
    if (enabled) {
      void previewProviderPreset().then(
        result => { if (active) setPreset(result); },
        () => { if (active) setFailed(true); },
      );
    }
    return () => { active = false; };
  }, [enabled]);
  return { preset, failed };
}
