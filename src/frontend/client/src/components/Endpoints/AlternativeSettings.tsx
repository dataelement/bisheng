import { useRecoilValue } from 'recoil';
import { SettingsViews } from '~/types/chat';
import type { TSettingsProps } from '~/common';
import { Advanced } from './Settings';
import { cn } from '~/utils';
import store from '~/store';

export default function AlternativeSettings({
  conversation,
  setOption,
  isPreset = false,
  className = '',
}: TSettingsProps) {
  const currentSettingsView = useRecoilValue(store.currentSettingsView);
  if (!conversation?.endpoint || currentSettingsView === SettingsViews.default) {
    return null;
  }

  return (
    <div className={cn('hide-scrollbar h-[500px] overflow-y-auto touch-desktop:mb-2 touch-desktop:h-[350px]', className)}>
      <Advanced conversation={conversation} setOption={setOption} isPreset={isPreset} />
    </div>
  );
}
