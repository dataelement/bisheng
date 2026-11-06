// @ts-strict-ignore
import { Tooltip as SharedTooltip } from '@bisheng/ui';
import React, { forwardRef } from 'react';
import { useWatch } from 'react-hook-form';
import type { Control } from 'react-hook-form';

import { SendIcon } from '~/components/svg';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';

type SendButtonProps = {
  disabled: boolean;
  control: Control<{ text: string }>;
};

const SubmitButton = React.memo(
  forwardRef((props: { disabled: boolean, isLingsi: boolean }, ref: React.ForwardedRef<HTMLButtonElement>) => {
    const localize = useLocalize();
    return (
      <SharedTooltip  content={localize('com_nav_send_message')}  ><button
            ref={ref}
            aria-label={localize('com_nav_send_message')}
            id="send-button"
            disabled={props.disabled}
            className={cn(
              'btn-brand-primary flex h-8 w-8 items-center justify-center rounded-full bg-primary text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:text-text-secondary disabled:opacity-10',
              props.isLingsi && 'bg-gradient-to-b from-blue-500 to-blue-200',
            )}
            data-testid="send-button"
            type="submit"
          >
            <span className="flex items-center justify-center" data-state="closed">
              <SendIcon size={18} />
            </span>
          </button></SharedTooltip>
    );
  }),
);

const SendButton = React.memo(
  forwardRef((props: SendButtonProps, ref: React.ForwardedRef<HTMLButtonElement>) => {
    const data = useWatch({ control: props.control });
    return <SubmitButton ref={ref} isLingsi={props.isLingsi || false} disabled={props.disabled || !data.text} />;
  }),
);

export default SendButton;
