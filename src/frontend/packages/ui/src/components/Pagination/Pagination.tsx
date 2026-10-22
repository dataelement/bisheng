import * as React from 'react';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import { PHONE_QUERY, useMediaQuery } from '../../utils/useMediaQuery';
import { buttonVariants } from '../Button/Button';
import type { InputSize } from '../Input/shared';
import { Select } from '../Select/Select';
import { QuickJumper } from './QuickJumper';
import { getPageItems } from './pageItems';

/**
 * Pagination — cut a long list into pages and jump between them
 * (组件-Pagination分页.md v1).
 *
 * What it pins down and a page cannot restate: the ellipsis rule (§3.1), the
 * 24/32/40 ladder matched to buttons and inputs (§4), the current page in a
 * light brand fill with brand text (§6.1), the optional total
 * on the far left (§5.1), arrows that disable rather than vanish and a pager
 * that stays even with one page or none
 * (§6.2), the jumper appearing past 10 pages and refusing out-of-range input
 * (§5.3), back to page 1 when the page size changes (§5.2), and the phone
 * switching to the simple type (§8).
 *
 * Left to the caller (it owns the list and the URL): scrolling the list back
 * to its first row after a page change, resetting to page 1 when filters
 * change, and writing the page into the address (§7).
 *
 * Not this component: browsing feeds (scroll-to-load, 组件-Loading加载.md)
 * and step-by-step flows (a step bar).
 */
export type PaginationSize = InputSize;

/** Every string the pager shows — this library holds no copy of its own. */
export interface PaginationLocale {
  /** 「共 128 条」— receives the total already grouped (`12,800`). */
  total: (total: string) => React.ReactNode;
  /** 「10 条/页」 */
  pageSize: (size: number) => string;
  /** 「跳至」 */
  jumpPrefix: React.ReactNode;
  /** 「页」 */
  jumpSuffix: React.ReactNode;
  /** 「请输入 1–13」 */
  jumpError: (totalPages: number) => string;
  /** Screen-reader names. */
  prev: string;
  next: string;
  nav: string;
  pageSizeAria?: string;
  jumpAria?: string;
}

const DEFAULT_LOCALE: PaginationLocale = {
  total: (total) => `Total ${total}`,
  pageSize: (size) => `${size} / page`,
  jumpPrefix: 'Go to',
  jumpSuffix: '',
  jumpError: (totalPages) => `Enter 1–${totalPages}`,
  prev: 'Previous page',
  next: 'Next page',
  nav: 'Pagination',
};

export interface PaginationProps {
  /** Total number of records. Pass 0 for an empty list — the pager still shows (§6.2). */
  total: number;
  current?: number;
  defaultCurrent?: number;
  pageSize?: number;
  defaultPageSize?: number;
  /**
   * Fires on every page or page-size change. A page-size change always comes
   * with `page = 1` (§5.2). Also fires once when `total` shrinks below the
   * current page (the last row of the last page was deleted, §7).
   */
  onChange?: (page: number, pageSize: number) => void;
  /** §4 — match the table's row height: compact tables take `small`. */
  size?: PaginationSize;
  /** §3 — `‹ 6 / 13 ›`. Unset = automatic on phones (< 576px), standard elsewhere. */
  simple?: boolean;
  /** §5.1 — 「共 N 条」, opt-in: turn on where the count itself helps (logs, audit records). */
  showTotal?: boolean;
  /** §5.2 — off by default; turn on where users need to see more at once. */
  showSizeChanger?: boolean;
  pageSizeOptions?: number[];
  /** §5.3 — unset = shown once there are more than 10 pages. */
  showQuickJumper?: boolean;
  /** §6.2 — the whole table is locked (e.g. a batch job is running). */
  disabled?: boolean;
  locale?: Partial<PaginationLocale>;
  /** Layout only. The row right-aligns itself (§2). */
  className?: string;
}

const DEFAULT_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

/** §5.3 — the jumper appears past this many pages. */
const JUMPER_THRESHOLD = 10;

/** §4 — page blocks are square at minimum, padded 4/6/8 once a number is wider. */
const ITEM_SIZE: Record<PaginationSize, string> = {
  small: 'min-w-6 px-1',
  medium: 'min-w-8 px-1.5',
  large: 'min-w-10 px-2',
};

/** §4 — arrows and the ellipsis follow the 14/16/18 icon ladder. */
const ICON_SIZE: Record<PaginationSize, string> = {
  small: 'size-3.5',
  medium: 'size-4',
  large: 'size-[18px]',
};

/** §2 — 16px between groups (12 on small), 4px between page blocks. */
const GROUP_GAP: Record<PaginationSize, string> = {
  small: 'gap-3',
  medium: 'gap-4',
  large: 'gap-4',
};

/** §5.2 — wide enough for 「100 条/页」 at each size. */
const SIZE_CHANGER_WIDTH: Record<PaginationSize, string> = {
  small: 'w-24',
  medium: 'w-[108px]',
  large: 'w-[120px]',
};

/**
 * §6.1 — page blocks and arrows are the default text button: no fill at rest,
 * the light gray on hover, the button's focus ring. Text is one step lighter
 * (`text-2`) than the button's own gray. Disabled drops the button's disabled
 * FILL — a text button has no chip to gray out — leaving just the faint glyph.
 */
function itemClass(size: PaginationSize, iconOnly: boolean) {
  return cn(
    buttonVariants({ color: 'default', variant: 'text', size, iconOnly }),
    !iconOnly && ITEM_SIZE[size],
    'tabular-nums text-text-2 disabled:!bg-transparent disabled:!text-text-4',
  );
}

/**
 * §6.1 — the current page: light brand fill + brand text, weight 500 — the
 * primary `filled` button's pair, so it follows the blue ⇄ green theme and the
 * dark brand ramp on its own. The gray hover of the other pages never reads as
 * "here". No pointer reaction, but it stays focusable for `aria-current`.
 * A disabled pager drops the brand color: nothing is actionable, so the
 * current page only keeps a gray fill to stay findable.
 */
const CURRENT_CLASS =
  'pointer-events-none bg-blue-50 font-medium text-blue-600 disabled:!bg-fill-2 disabled:!text-text-4';

function useControllable<T>(value: T | undefined, defaultValue: T) {
  const [inner, setInner] = React.useState(defaultValue);
  return [value ?? inner, setInner] as const;
}

export function Pagination({
  total,
  current: currentProp,
  defaultCurrent = 1,
  pageSize: pageSizeProp,
  defaultPageSize = 10,
  onChange,
  size: sizeProp = 'medium',
  simple: simpleProp,
  showTotal = false,
  showSizeChanger = false,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  showQuickJumper,
  disabled = false,
  locale: localeProp,
  className,
}: PaginationProps) {
  const locale = { ...DEFAULT_LOCALE, ...localeProp };
  const phone = useMediaQuery(PHONE_QUERY);
  const [rawCurrent, setCurrent] = useControllable(currentProp, defaultCurrent);
  const [pageSize, setPageSize] = useControllable(pageSizeProp, defaultPageSize);

  const totalPages = Math.max(1, Math.ceil(Math.max(0, total) / pageSize));
  const current = Math.min(Math.max(1, rawCurrent), totalPages);

  // §8 — a phone gets the simple type, and small grows to medium there.
  const simple = simpleProp ?? phone;
  const size: PaginationSize = phone && sizeProp === 'small' ? 'medium' : sizeProp;
  const jumperVisible = !simple && (showQuickJumper ?? totalPages > JUMPER_THRESHOLD);
  const sizeChangerVisible = !simple && showSizeChanger;

  // §7 — the last row of the last page was deleted: step back to the new last
  // page instead of sitting on a blank one. Only with data left — an empty
  // list (or one still loading) stays on page 1 by definition.
  const onChangeRef = React.useRef(onChange);
  onChangeRef.current = onChange;
  React.useEffect(() => {
    if (total > 0 && rawCurrent > totalPages) {
      setCurrent(totalPages);
      onChangeRef.current?.(totalPages, pageSize);
    }
  }, [total, rawCurrent, totalPages, pageSize, setCurrent]);

  const goTo = (page: number) => {
    if (disabled || page === current || page < 1 || page > totalPages) return;
    setCurrent(page);
    onChange?.(page, pageSize);
  };

  const handlePageSizeChange = (next: number) => {
    if (next === pageSize) return;
    // §5.2 — "page 6" under the old size is not the same records any more.
    setPageSize(next);
    setCurrent(1);
    onChange?.(1, next);
  };

  const icon = ICON_SIZE[size];
  const arrow = (direction: 'prev' | 'next') => {
    const isPrev = direction === 'prev';
    const Icon = isPrev ? Outlined.Left : Outlined.Right;
    return (
      <button
        type="button"
        aria-label={isPrev ? locale.prev : locale.next}
        // §6.1 — disabled, never hidden: a vanishing arrow shifts the row.
        disabled={disabled || (isPrev ? current <= 1 : current >= totalPages)}
        onClick={() => goTo(isPrev ? current - 1 : current + 1)}
        className={itemClass(size, true)}
      >
        <Icon className={icon} aria-hidden />
      </button>
    );
  };

  return (
    <nav
      aria-label={locale.nav}
      className={cn(
        'flex w-full flex-wrap items-center justify-end text-body',
        GROUP_GAP[size],
        className,
      )}
    >
      {showTotal && (
        // §5.1 — background information: secondary gray, number not colored.
        <span className={cn('shrink-0 whitespace-nowrap', disabled ? 'text-text-4' : 'text-text-2')}>
          {locale.total(Math.max(0, total).toLocaleString())}
        </span>
      )}

      <span className="flex shrink-0 items-center gap-1">
        {arrow('prev')}
        {simple ? (
          // §3 — display only; paging is done by the arrows.
          <span
            className={cn(
              'whitespace-nowrap px-2 tabular-nums',
              disabled ? 'text-text-4' : 'text-text-2',
            )}
          >
            {current} / {totalPages}
          </span>
        ) : (
          getPageItems(current, totalPages).map((item) =>
            typeof item === 'number' ? (
              <button
                key={item}
                type="button"
                disabled={disabled}
                aria-current={item === current ? 'page' : undefined}
                onClick={() => goTo(item)}
                className={cn(itemClass(size, false), item === current && CURRENT_CLASS)}
              >
                {item}
              </button>
            ) : (
              // §3.1 — not clickable in v1; long jumps go through the jumper.
              <span
                key={item}
                aria-hidden
                className={cn(itemClass(size, false), 'pointer-events-none text-text-3')}
              >
                <Outlined.More className={icon} />
              </span>
            ),
          )
        )}
        {arrow('next')}
      </span>

      {sizeChangerVisible && (
        <Select
          size={size}
          className={SIZE_CHANGER_WIDTH[size]}
          aria-label={locale.pageSizeAria}
          disabled={disabled}
          showSearch={false}
          value={pageSize}
          options={pageSizeOptions.map((option) => ({
            value: option,
            label: locale.pageSize(option),
          }))}
          onChange={(value) => {
            if (typeof value === 'number') handlePageSizeChange(value);
          }}
        />
      )}

      {jumperVisible && (
        <QuickJumper
          size={size}
          totalPages={totalPages}
          disabled={disabled}
          prefix={locale.jumpPrefix}
          suffix={locale.jumpSuffix}
          errorText={locale.jumpError(totalPages)}
          ariaLabel={locale.jumpAria}
          onJump={goTo}
        />
      )}
    </nav>
  );
}
