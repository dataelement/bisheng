import { Select } from '@bisheng/ui';
import { useTranslation } from 'react-i18next';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';

/** How end users meet one workbench tool (F005). Stored as two exclusive flags. */
export type ToolUsage = 'optional' | 'default' | 'auto';

interface ToolUsageFlags {
  default_checked?: boolean;
  auto_enabled?: boolean;
}

export function toolUsageOf(tool: ToolUsageFlags): ToolUsage {
  if (tool.auto_enabled) return 'auto';
  return tool.default_checked ? 'default' : 'optional';
}

export function withToolUsage<T extends ToolUsageFlags>(tool: T, usage: ToolUsage): T {
  return { ...tool, default_checked: usage === 'default', auto_enabled: usage === 'auto' };
}

interface ToolUsageSelectProps {
  value: ToolUsage;
  toolName: string;
  onChange: (usage: ToolUsage) => void;
}

/**
 * Three exclusive options with a one-line explanation each. A Select rather than
 * radios: the selected-tools panel is a third of the page wide, and the choice is
 * saved with the form (Select spec §1).
 */
export function ToolUsageSelect({ value, toolName, onChange }: ToolUsageSelectProps) {
  const { t } = useTranslation('bs');
  const selectLabels = useSelectLabels();
  const options = (['optional', 'default', 'auto'] as const).map((usage) => ({
    value: usage,
    label: t(`bench.toolUsage.${usage}`),
    description: t(`bench.toolUsage.${usage}Desc`),
  }));

  return (
    // The row itself scrolls the tool list on click; keep the choice local.
    <div onClick={(event) => event.stopPropagation()}>
      <Select
        {...selectLabels}
        size="small"
        className="w-[112px]"
        options={options}
        value={value}
        aria-label={t('bench.toolUsage.ariaLabel', { name: toolName })}
        onChange={(next) => {
          if (next) onChange(next as ToolUsage);
        }}
      />
    </div>
  );
}
