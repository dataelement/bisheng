import { useEffect, useMemo, useState } from 'react';
import { useLocalize } from '~/hooks';
import { Button } from '~/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/Dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/Select';
import {
  ModelAvailabilityOption,
  type WorkbenchModelOption,
} from './Chat/ModelAvailabilityOption';
import {
  getRecoveryModelCandidates,
  isRecoveryConfirmationAccepted,
} from './modelRateLimitRecoveryDialogHelpers';

interface ModelRateLimitRecoveryDialogProps {
  open: boolean;
  models: WorkbenchModelOption[];
  currentModelId: string | number;
  pending?: boolean;
  isCompatible?: (model: WorkbenchModelOption) => boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (targetModelId: string) => Promise<unknown> | unknown;
  onLater: () => void;
}

export function ModelRateLimitRecoveryDialog({
  open,
  models,
  currentModelId,
  pending = false,
  isCompatible,
  onOpenChange,
  onConfirm,
  onLater,
}: ModelRateLimitRecoveryDialogProps) {
  const localize = useLocalize();
  const candidates = useMemo(
    () => getRecoveryModelCandidates(models, currentModelId, isCompatible),
    [currentModelId, isCompatible, models],
  );
  const [selectedModelId, setSelectedModelId] = useState('');
  const [confirmFailed, setConfirmFailed] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSelectedModelId((previous) => (
      candidates.some((model) => String(model.id) === previous)
        ? previous
        : String(candidates[0]?.id ?? '')
    ));
    setConfirmFailed(false);
  }, [candidates, open]);

  const handleConfirm = async () => {
    if (!selectedModelId || pending) return;
    setConfirmFailed(false);
    try {
      const result = await onConfirm(selectedModelId);
      if (!isRecoveryConfirmationAccepted(result)) setConfirmFailed(true);
    } catch {
      // Keep the original execution and the chooser open. The server is the
      // authority for permissions, capabilities, and current busy state.
      setConfirmFailed(true);
    }
  };

  const handleLater = () => {
    if (pending) return;
    onLater();
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => {
      if (!pending) onOpenChange(nextOpen);
    }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{localize('com_message.still_busy_title')}</DialogTitle>
          <DialogDescription>
            {localize('com_message.still_busy_desc')}
          </DialogDescription>
        </DialogHeader>

        <Select value={selectedModelId} onValueChange={setSelectedModelId} disabled={pending}>
          <SelectTrigger aria-label={localize('com_message.choose_model')}>
            <SelectValue placeholder={localize('com_message.choose_model')} />
          </SelectTrigger>
          <SelectContent>
            {candidates.map((model) => (
              <SelectItem
                key={String(model.id)}
                value={String(model.id)}
                textValue={model.displayName || model.name}
              >
                <ModelAvailabilityOption model={model} />
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {confirmFailed ? (
          <p role="alert" className="text-sm text-error">
            {localize('com_message.switch_rejected')}
          </p>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" disabled={pending} onClick={handleLater}>
            {localize('com_message.try_later')}
          </Button>
          <Button
            color="primary"
            variant="solid"
            disabled={pending || !selectedModelId}
            onClick={handleConfirm}
          >
            {localize('com_message.switch_model')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
