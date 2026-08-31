import type { BsConfig } from '~/types/chat';
import { useLocalize } from '~/hooks';

export type WorkbenchModelOption = BsConfig['models'][number];

interface ModelAvailabilityOptionProps {
  model: WorkbenchModelOption;
  showDescription?: boolean;
}

export function ModelAvailabilityOption({
  model,
  showDescription = true,
}: ModelAvailabilityOptionProps) {
  const localize = useLocalize();
  const isBusy = model.rateLimitState === 'busy' || model.rateLimitState === 'recovering';
  const suffix = isBusy ? localize('com_message.model_busy_suffix') : '';

  return (
    <div
      className={`flex min-w-0 items-center ${isBusy ? 'text-text-3' : 'text-text-2'}`}
      aria-label={[model.displayName || model.name, suffix.trim()].filter(Boolean).join(' ')}
    >
      <span className="shrink-0 text-body-sm">
        {model.displayName || model.name}
        {suffix}
      </span>
      {showDescription && model.description ? (
        <>
          <span className="mx-1.5 h-3 w-px shrink-0 bg-fill-3" />
          <span className="min-w-0 truncate text-caption text-text-3">{model.description}</span>
        </>
      ) : null}
    </div>
  );
}
