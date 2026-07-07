import { Trash2 } from 'lucide-react';
import type { MouseEvent } from 'react';
import { Button } from '~/components/ui';
import { useConfirm } from '~/Providers';
import { useLocalize } from '~/hooks';

const DeleteVersion = ({
  name,
  disabled,
  selectHandler,
}: {
  name: string;
  disabled?: boolean;
  selectHandler: () => void;
}) => {
  const localize = useLocalize();
  const confirm = useConfirm();

  const handleClick = async (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    const ok = await confirm({
      variant: 'destructive',
      title: localize('com_ui_delete_prompt'),
      description: localize('com_ui_delete_confirm_prompt_version_var', { 0: name }),
      confirmText: localize('com_ui_delete'),
    });
    if (!ok) {
      return;
    }
    selectHandler();
  };

  return (
    <Button
      variant="destructive"
      size="sm"
      aria-label="Delete version"
      className="h-10 w-10 p-0.5"
      disabled={disabled}
      onClick={handleClick}
    >
      <Trash2 className="size-5 cursor-pointer text-white" />
    </Button>
  );
};

export default DeleteVersion;
