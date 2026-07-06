import React, { useState, useCallback, useEffect } from 'react';
import { Label, Button } from '~/components';
import { useConfirm } from '~/Providers';
import { useLocalize } from '~/hooks';

export const DeleteCache = ({ disabled = false }: { disabled?: boolean }) => {
  const localize = useLocalize();
  const confirm = useConfirm();
  const [isCacheEmpty, setIsCacheEmpty] = useState(true);

  const checkCache = useCallback(async () => {
    const cache = await caches.open('tts-responses');
    const keys = await cache.keys();
    setIsCacheEmpty(keys.length === 0);
  }, []);

  useEffect(() => {
    checkCache();
  }, [checkCache]);

  const clearCache = useCallback(async () => {
    const cache = await caches.open('tts-responses');
    await cache.keys().then((keys) => Promise.all(keys.map((key) => cache.delete(key))));
    await checkCache();
  }, [checkCache]);

  const handleClear = async () => {
    const ok = await confirm({
      variant: 'destructive',
      title: localize('com_nav_confirm_clear'),
      description: localize('com_nav_clear_cache_confirm_message'),
      confirmText: localize('com_ui_delete'),
    });
    if (!ok) {
      return;
    }
    await clearCache();
  };

  return (
    <div className="flex items-center justify-between">
      <Label className="font-light">{localize('com_nav_delete_cache_storage')}</Label>
      <Button
        variant="destructive"
        className="flex items-center justify-center rounded-lg transition-colors duration-200"
        onClick={handleClear}
        disabled={disabled || isCacheEmpty}
      >
        {localize('com_ui_delete')}
      </Button>
    </div>
  );
};
