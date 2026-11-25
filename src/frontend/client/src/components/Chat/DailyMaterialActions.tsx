import { Button } from '@bisheng/ui';
import type { RetryMaterials } from '~/hooks/useDailyRegenerate';
import { useLocalize } from '~/hooks';

interface DailyMaterialActionsProps {
  questionId: string;
  onRegenerate: (questionId: string, materials: RetryMaterials) => void;
}

export function DailyMaterialActions({ questionId, onRegenerate }: DailyMaterialActionsProps) {
  const localize = useLocalize();
  return (
    <div className="flex flex-wrap gap-1">
      <Button color="default" variant="text" size="sm" onClick={() => onRegenerate(questionId, 'original')}>
        {localize('com_message.regenerate_original_materials')}
      </Button>
      <Button color="default" variant="text" size="sm" onClick={() => onRegenerate(questionId, 'current')}>
        {localize('com_message.ask_current_materials')}
      </Button>
    </div>
  );
}
