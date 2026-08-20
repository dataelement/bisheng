import { useLocalize } from '~/hooks';
import { Button } from '~/components/ui/Button';
import { cn } from '~/utils';

export type LoginHandoffState = 'pending' | 'blocked';

interface LoginHandoffProps {
  /**
   * `pending` — we are handing the browser to the login page and will bring it
   * back. `blocked` — it already came back and is still not authenticated, so
   * stop and hand control to the user.
   */
  state: LoginHandoffState;
  onLogin: () => void;
}

/**
 * The screen a share recipient sees when they open a share link without being
 * logged in.
 *
 * Deliberately NOT styled as an error: the link is fine, the viewer just has
 * not identified themselves yet, and they will be returned here afterwards.
 * Hence no lock illustration and no danger red — a lock says "denied", which is
 * the wrong thing to tell someone who has not been asked yet.
 *
 * The one expressive element is the return trace underneath: a dot that runs
 * the rule and comes BACK. It encodes the actual mechanic (login is a round
 * trip), which is why `animation-direction: alternate` matters and a plain
 * looping spinner would say the wrong thing.
 */
export function LoginHandoff({ state, onLogin }: LoginHandoffProps) {
  const localize = useLocalize();
  const blocked = state === 'blocked';

  // Brand palette so the screen follows the blue ⇄ green theme switch. The
  // blocked state drops to the muted brand accent rather than danger red.
  const traceColor = blocked ? 'rgb(var(--brand-muted))' : 'rgb(var(--brand-500))';
  const trackColor = blocked
    ? 'rgb(var(--brand-muted) / 0.18)'
    : 'rgb(var(--brand-500) / 0.18)';

  return (
    <div className="flex min-h-[100dvh] w-full items-center justify-center bg-background px-6 py-10">
      <div className="w-full max-w-[420px]">
        <p className="text-[11px] tracking-[0.08em] text-muted-foreground">
          {localize('com_share.gate_eyebrow')}
        </p>

        <h1
          className="mt-3 text-[17px] font-medium leading-7 tracking-[-0.01em] text-foreground"
          role="status"
          aria-live="polite"
        >
          {localize(blocked ? 'com_share.gate_blocked_title' : 'com_share.gate_title')}
        </h1>

        <p className="mt-2 text-[13px] leading-[20px] text-muted-foreground">
          {localize(blocked ? 'com_share.gate_blocked_desc' : 'com_share.gate_desc')}
        </p>

        <Button className="mt-6" onClick={onLogin}>
          {localize(blocked ? 'com_share.gate_blocked_action' : 'com_share.gate_action')}
        </Button>

        {/* Return trace. `aria-hidden` — the state is already announced by the
            heading above; a second live region would double-speak it. */}
        <div
          className="relative mt-10 h-px w-full"
          style={{ backgroundColor: trackColor }}
          aria-hidden="true"
        >
          {blocked ? (
            <TraceDot color={traceColor} className="left-1/2" />
          ) : (
            <>
              {/* Moving dot — hidden when the viewer asked for less motion. */}
              <TraceDot
                color={traceColor}
                className="animate-return-trace motion-reduce:hidden"
              />
              {/* Reduced-motion fallback: both endpoints marked, so the
                  round-trip relationship still reads without movement. */}
              <TraceDot color={traceColor} className="hidden left-0 motion-reduce:block" />
              <TraceDot color={traceColor} className="hidden left-full motion-reduce:block" />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function TraceDot({ color, className }: { color: string; className?: string }) {
  return (
    <span
      className={cn(
        'absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full',
        className,
      )}
      style={{ backgroundColor: color }}
    />
  );
}
