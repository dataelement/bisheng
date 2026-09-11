/**
 * F035 Track H (P3): queueing-state card (spec §7 last row). Shown while the
 * version sits in the Linsight worker queue (queueCount > 0, fed by the
 * existing queue-status polling). "Cancel queue" rides the terminate-execute
 * endpoint, which removes the version from the Redis queue server-side.
 */
import { Button } from '~/components/ui';
import { useLocalize } from '~/hooks';

/**
 * Animated balance/seesaw icon (designer-supplied SVG, SMIL animation baked
 * in): the beam tilts side to side while the ball rolls across — the visual
 * for "waiting for a slot". Strokes use currentColor so the brand text color
 * on the host (blue⇄green theme) drives it.
 */
function QueueBalanceIcon({ size = 16, className }: { size?: number; className?: string }) {
    return (
        <svg
            width={size}
            height={size}
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
            className={className}
        >
            {/* The stand stays fixed while the beam and ball move together. */}
            <path d="M12 16L15 22H9L12 16Z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
            <g>
                <animateTransform
                    attributeName="transform"
                    type="rotate"
                    values="-30 12 14.5; -30 12 14.5; 30 12 14.5; 30 12 14.5; -30 12 14.5; -30 12 14.5"
                    keyTimes="0; 0.08; 0.43; 0.57; 0.92; 1"
                    calcMode="spline"
                    keySplines="0 0 1 1; 0.45 0 0.55 1; 0 0 1 1; 0.45 0 0.55 1; 0 0 1 1"
                    dur="3.2s"
                    repeatCount="indefinite"
                />
                <rect x="2" y="12" width="20" height="3" rx="1.5" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
                <circle cx="6" cy="9" r="3" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
                    <animate
                        attributeName="cx"
                        values="6; 6; 18; 18; 6; 6"
                        keyTimes="0; 0.27; 0.46; 0.77; 0.96; 1"
                        calcMode="spline"
                        keySplines="0 0 1 1; 0.55 0.05 0.85 0.35; 0 0 1 1; 0.55 0.05 0.85 0.35; 0 0 1 1"
                        dur="3.2s"
                        repeatCount="indefinite"
                    />
                </circle>
            </g>
        </svg>
    );
}

export function QueueCard({ position, onCancel }: { position: number; onCancel: () => void }) {
    const localize = useLocalize();
    return (
        <div className="my-2 flex items-center gap-3 rounded-2xl border border-blue-100 bg-blue-50/60 p-4">
            <QueueBalanceIcon size={16} className="shrink-0 text-blue-500" />
            <p className="min-w-0 flex-1 text-sm text-gray-700">
                {localize('com_linsight_queue_waiting')}
                <span className="ml-1 font-medium text-blue-600">
                    {localize('com_linsight_queue_position', { 0: String(position) })}
                </span>
            </p>
            <Button
                color="default"
                variant="outlined"
                size="small"
                className="shrink-0"
                onClick={onCancel}
            >
                {localize('com_linsight_queue_cancel')}
            </Button>
        </div>
    );
}
