/**
 * F035 Track H (P3): queueing-state card (spec §7 last row). Shown while the
 * version sits in the Linsight worker queue (queueCount > 0, fed by the
 * existing queue-status polling). "Cancel queue" rides the terminate-execute
 * endpoint, which removes the version from the Redis queue server-side.
 */
import { Hourglass } from 'lucide-react';
import { Button } from '~/components/ui';
import { useLocalize } from '~/hooks';

export function QueueCard({ position, onCancel }: { position: number; onCancel: () => void }) {
    const localize = useLocalize();
    return (
        <div className="my-2 flex items-center gap-3 rounded-2xl border border-blue-100 bg-blue-50/60 p-4">
            <Hourglass size={18} className="shrink-0 animate-pulse text-blue-500" />
            <p className="min-w-0 flex-1 text-sm text-gray-700">
                {localize('com_linsight_queue_waiting')}
                <span className="ml-1 font-medium text-blue-600">
                    {localize('com_linsight_queue_position', { 0: String(position) })}
                </span>
            </p>
            <Button variant="outline" size="sm" className="h-7 shrink-0 px-3" onClick={onCancel}>
                {localize('com_linsight_queue_cancel')}
            </Button>
        </div>
    );
}
