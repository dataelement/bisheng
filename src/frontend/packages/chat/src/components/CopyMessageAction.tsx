import { Button, Tooltip } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useEffect, useState } from 'react';
export interface CopyMessageActionProps {
  label: string;
  copiedLabel: string;
  onCopy: () => void | Promise<unknown>;
  onError?: (error: unknown) => void;
  showLabel?: boolean;
}
export function CopyMessageAction({ label, copiedLabel, onCopy, onError, showLabel = false }: CopyMessageActionProps) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 3000);
    return () => clearTimeout(timer);
  }, [copied]);
  const handleCopy = async () => {
    try { await onCopy(); setCopied(true); } catch (error) { onError?.(error); }
  };
  return <Tooltip content={copied ? copiedLabel : label}>
    <Button size="small" variant="text" color="default" iconOnly={!showLabel} aria-label={copied ? copiedLabel : label} onClick={() => void handleCopy()}>
      {copied ? <Outlined.Copied size={14} className="text-primary" /> : <Outlined.Copy size={14} />}
      {showLabel && (copied ? copiedLabel : label)}
    </Button>
  </Tooltip>;
}
