import { forwardRef, ReactNode, Ref } from 'react';
import { cva } from 'class-variance-authority';
import {
  OGDialogTitle,
  OGDialogClose,
  OGDialogFooter,
  OGDialogHeader,
  OGDialogContent,
  OGDialogDescription,
} from './OriginalDialog';
import { useLocalize } from '~/hooks';
import { Spinner } from '../svg';
import { cn } from '~/utils/';

type SelectVariant = 'danger' | 'primary';

/**
 * Confirm-button variants aligned with the useConfirm dialog (ConfirmContext.tsx),
 * the convergence target for all confirm dialogs. `danger` uses the semantic red
 * (not themed); `primary` follows the blue⇄green brand theme.
 */
const selectButtonVariants = cva(
  'flex h-auto items-center justify-center rounded-md border-none px-4 py-[5px] text-sm text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-80 max-sm:order-first max-sm:w-full sm:order-none',
  {
    variants: {
      variant: {
        danger: 'bg-[#f53f3f] hover:bg-[#f53f3f]/90',
        primary: 'btn-brand-primary bg-primary hover:bg-primary/90',
      },
    },
  },
);

/**
 * Fold the legacy per-page `selectClasses` zoo (9 historical color recipes) onto
 * the two standard variants so every existing call site unifies without being
 * edited. Class strings that match neither family pass through untouched — the
 * one-off escape hatch. New/migrated code should pass `selectVariant` instead.
 */
function resolveSelectVariant(selectClasses?: string): SelectVariant | undefined {
  if (!selectClasses) return 'primary';
  if (/red-|destructive/.test(selectClasses)) return 'danger';
  if (/green-|btn-primary|surface-submit/.test(selectClasses)) return 'primary';
  return undefined;
}

type SelectionProps = {
  selectHandler?: () => void;
  selectVariant?: SelectVariant;
  selectClasses?: string;
  selectText?: string | ReactNode;
  isLoading?: boolean;
};

type DialogTemplateProps = {
  title: string;
  description?: string;
  main?: ReactNode;
  buttons?: ReactNode;
  leftButtons?: ReactNode;
  selection?: SelectionProps;
  className?: string;
  overlayClassName?: string;
  headerClassName?: string;
  mainClassName?: string;
  footerClassName?: string;
  showCloseButton?: boolean;
  showCancelButton?: boolean;
  onClose?: () => void;
};

const OGDialogTemplate = forwardRef((props: DialogTemplateProps, ref: Ref<HTMLDivElement>) => {
  const localize = useLocalize();
  const {
    title,
    main,
    buttons,
    selection,
    className,
    leftButtons,
    description = '',
    mainClassName,
    headerClassName,
    footerClassName,
    showCloseButton,
    overlayClassName,
    showCancelButton = true,
  } = props;
  const { selectHandler, selectVariant, selectClasses, selectText, isLoading } = selection || {};
  const Cancel = localize('com_ui_cancel');

  const variant = selectVariant ?? resolveSelectVariant(selectClasses);

  return (
    <OGDialogContent
      overlayClassName={overlayClassName}
      showCloseButton={showCloseButton}
      ref={ref}
      className={cn('w-11/12 border-none bg-background text-foreground', className ?? '')}
      onClick={(e) => e.stopPropagation()}
    >
      <OGDialogHeader className={cn(headerClassName ?? '')}>
        {/* Danger confirms get the red title, mirroring the useConfirm destructive look. */}
        <OGDialogTitle className={variant === 'danger' ? 'text-[#f53f3f]' : undefined}>
          {title}
        </OGDialogTitle>
        {description && (
          <OGDialogDescription className="items-center justify-center">
            {description}
          </OGDialogDescription>
        )}
      </OGDialogHeader>
      <div className={cn('px-0 py-2', mainClassName)}>{main != null ? main : null}</div>
      <OGDialogFooter className={footerClassName}>
        <div>
          {leftButtons != null ? (
            <div className="mt-3 flex h-auto gap-2 max-sm:w-full max-sm:flex-col sm:mt-0 sm:flex-row">
              {leftButtons}
            </div>
          ) : null}
        </div>
        <div className="flex h-auto gap-2 max-sm:w-full max-sm:flex-col sm:flex-row">
          {buttons != null ? buttons : null}
          {showCancelButton && (
            <OGDialogClose className="flex h-auto items-center justify-center rounded-md border border-[#ebecf0] bg-white/50 px-4 py-[5px] text-sm font-normal text-[#070038] backdrop-blur-[4px] transition-colors hover:bg-[#f7f8fa] focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400 focus-visible:ring-offset-2 dark:border-gray-600 dark:bg-transparent dark:text-gray-100 dark:hover:bg-gray-700 max-sm:order-last max-sm:w-full sm:order-first">
              {Cancel}
            </OGDialogClose>
          )}
          {selection ? (
            <OGDialogClose
              onClick={selectHandler}
              disabled={isLoading}
              className={cn(
                selectButtonVariants({ variant: variant ?? null }),
                variant ? '' : selectClasses,
              )}
            >
              {isLoading === true ? <Spinner className="size-4 text-white" /> : selectText}
            </OGDialogClose>
          ) : null}
        </div>
      </OGDialogFooter>
    </OGDialogContent>
  );
});

export default OGDialogTemplate;
