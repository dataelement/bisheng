import { useLocalize } from '~/hooks';
import { TooltipAnchor } from '~/components/ui';
import { cn } from '~/utils';

export default function NavToggle({
  onToggle,
  navVisible,
  isHovering,
  setIsHovering,
  side = 'left',
  className = '',
  translateX,
  /** 会话列表栏右边缘的视口 x（px）；传入后与 translateX 二选一，把手落在分隔线右侧的主内容侧 */
  anchorRightEdgePx,
}: {
  onToggle: () => void;
  navVisible: boolean;
  isHovering: boolean;
  setIsHovering: (isHovering: boolean) => void;
  side?: 'left' | 'right';
  className?: string;
  /** Pixel offset when sidebar is visible. Pass a number (e.g. 240) to enable, or omit/0 to disable. */
  translateX?: number;
  anchorRightEdgePx?: number;
}) {
  const localize = useLocalize();
  const useAnchor = typeof anchorRightEdgePx === 'number';
  const transition = {
    transition: 'transform 0.3s ease, opacity 0.2s ease',
  };

  const rotationDegree = 15;
  const rotation = isHovering || !navVisible ? `${rotationDegree}deg` : '0deg';
  const topBarRotation = side === 'right' ? `-${rotation}` : rotation;
  const bottomBarRotation = side === 'right' ? rotation : `-${rotation}`;

  return (
    <div
      className={cn(
        className,
        'transition-transform duration-300',
        useAnchor && 'fixed top-1/2 z-[50] -translate-y-1/2',
        useAnchor && (navVisible ? 'rotate-0' : 'rotate-180'),
        !useAnchor && !translateX && '-translate-y-1/2',
        !useAnchor && !translateX && (navVisible ? 'rotate-0' : 'rotate-180'),
      )}
      style={
        useAnchor
          ? { left: anchorRightEdgePx }
          : translateX
            ? {
                transition: 'transform 0.3s ease',
                transform: `translateX(${navVisible ? translateX : 0}px) translateY(-50%) ${navVisible ? '' : 'rotate(180deg)'}`,
              }
            : undefined
      }
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      <TooltipAnchor
        side={side === 'right' ? 'left' : 'right'}
        aria-label={side === 'left' ? localize('com_ui_chat_history') : localize('com_ui_controls')}
        aria-expanded={navVisible}
        aria-controls={side === 'left' ? 'chat-history-nav' : 'controls-nav'}
        id={`toggle-${side}-nav`}
        onClick={(e) => {
          onToggle(e);
          setIsHovering(false)
        }}
        role="button"
        description={
          navVisible ? localize('com_nav_close_sidebar') : localize('com_nav_open_sidebar')
        }
        className="flex items-center justify-center"
        tabIndex={0}
      >
        <span className="" data-state="closed">
          <div
            className="flex h-[72px] w-8 items-center justify-center"
            style={{
              ...transition,
              // Keep the expand handle clearly visible when sidebar is collapsed.
              opacity: isHovering ? 1 : 0.25,
            }}
          >
            <div
              className={cn(
                "flex h-6 w-6 flex-col items-center rounded-md"
              )}
            >
              {/* Top bar */}
              <div
                className="h-3 w-1 rounded-full bg-black dark:bg-white"
                style={{
                  ...transition,
                  transform: `translateY(0.15rem) rotate(${topBarRotation}) translateZ(0px)`,
                }}
              />
              {/* Bottom bar */}
              <div
                className="h-3 w-1 rounded-full bg-black dark:bg-white"
                style={{
                  ...transition,
                  transform: `translateY(-0.15rem) rotate(${bottomBarRotation}) translateZ(0px)`,
                }}
              />
            </div>
          </div>
        </span>
      </TooltipAnchor>
    </div>
  );
}
