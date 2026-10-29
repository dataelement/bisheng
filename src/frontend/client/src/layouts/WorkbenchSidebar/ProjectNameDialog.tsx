import { Button, Input } from '@bisheng/ui';
import type { FormEvent } from 'react';
import { useEffect, useState } from 'react';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '~/components/ui/Dialog';
import { useLocalize } from '~/hooks';
import { PROJECT_NAME_MAX_LENGTH } from './projectsStore';

interface ProjectNameDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Present when renaming; absent when creating. */
  initialName?: string;
  onSubmit: (name: string) => void;
}

/** 新建项目 / 重命名项目 — one name field, shared by both. */
export function ProjectNameDialog({ open, onOpenChange, initialName, onSubmit }: ProjectNameDialogProps) {
  const localize = useLocalize();
  const [name, setName] = useState('');
  const renaming = initialName !== undefined;

  // Start from a clean draft on every open.
  useEffect(() => {
    if (open) setName(initialName ?? '');
  }, [open, initialName]);

  const trimmed = name.trim();
  // The Input's limit is soft (it lets the user type past it and turns the counter red),
  // so the submit is what enforces it.
  const valid = trimmed.length > 0 && trimmed.length <= PROJECT_NAME_MAX_LENGTH;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!valid) return;
    onSubmit(trimmed);
    onOpenChange(false);
  };

  return (
    // @bisheng/ui Modal is still `status: draft`, so this follows the client Dialog family.
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[calc(100%-40px)] max-w-[400px] rounded-2xl sm:rounded-2xl">
        <form onSubmit={handleSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle className="font-medium text-text-1">
              {localize(renaming ? 'com_workbench_sidebar.project_rename' : 'com_workbench_sidebar.project_new')}
            </DialogTitle>
          </DialogHeader>
          <Input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={localize('com_workbench_sidebar.project_name_placeholder')}
            aria-label={localize('com_workbench_sidebar.project_name_placeholder')}
            maxLength={PROJECT_NAME_MAX_LENGTH}
            showCount
          />
          <DialogFooter className="gap-2 sm:space-x-0">
            <Button type="button" color="default" variant="outlined" onClick={() => onOpenChange(false)}>
              {localize('com_ui_cancel')}
            </Button>
            <Button type="submit" disabled={!valid}>
              {localize(renaming ? 'com_ui_save' : 'com_ui_create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
