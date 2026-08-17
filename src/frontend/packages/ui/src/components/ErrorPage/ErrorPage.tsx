import { QRCodeSVG } from 'qrcode.react';
import * as React from 'react';
import { Button } from '../Button/Button';
import cn from '../../utils/cn';
import {
  buildCopyText,
  buildLogFile,
  buildLogFileName,
  buildQrPayload,
  type ErrorDiagnostics,
} from './diagnostics';

/**
 * Every string the page shows. The component looks none of these up — the
 * package carries no i18n keys (README contract), and the two apps translate
 * through different machinery anyway.
 */
export interface ErrorPageLabels {
  title: string;
  /** Reassurance plus what to do: screenshot this page and send it on. */
  description: string;
  /** Split around the copy link so a translation can put the link where it reads best. */
  copyBefore: string;
  copyLink: string;
  copyAfter: string;
  refresh: string;
  download: string;
  /** Sits on the card's top edge — the card is the part worth screenshotting. */
  screenshotHint: string;
  traceId: string;
  errorCode: string;
  time: string;
  version: string;
  route: string;
  user: string;
}

export interface ErrorPageProps {
  diagnostics: ErrorDiagnostics;
  labels: ErrorPageLabels;
  /** Brand artwork stays with the apps; the package holds no illustrations. */
  illustration?: React.ReactNode;
  /** Defaults to a full reload, which is what the button promises. */
  onRefresh?: () => void;
  /**
   * Fired once the diagnostics text is on the clipboard. The link's own label
   * never changes — the app confirms through whatever it already uses for
   * transient feedback (a toast), which the package cannot reach itself.
   */
  onCopied?: () => void;
  className?: string;
}

function DiagnosticRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2 text-body-sm">
      <span className="w-20 shrink-0 font-medium text-text-1/80">{label}</span>
      {/* Selectable on purpose: scanning is the happy path, retyping is the fallback. */}
      <span className="min-w-0 select-text break-all font-mono text-text-3">{value}</span>
    </div>
  );
}

/**
 * The screen a user lands on when the app has crashed, built so the fastest
 * possible support round trip is "screenshot this and send it".
 *
 * That is what the boxed card is for: it carries the identifiers, and the QR
 * beside it carries the same ones plus the error signature, so an engineer can
 * read the incident straight out of the image without asking the user to find
 * and describe anything. Everything the QR could not fit is in the downloadable
 * log.
 */
export function ErrorPage({
  diagnostics,
  labels,
  illustration,
  onRefresh,
  onCopied,
  className,
}: ErrorPageProps) {
  const rows = [
    { label: labels.traceId, value: diagnostics.traceId },
    { label: labels.errorCode, value: diagnostics.errorCode },
    { label: labels.time, value: diagnostics.timestamp },
    { label: labels.version, value: diagnostics.version },
    { label: labels.route, value: diagnostics.route },
    ...(diagnostics.user ? [{ label: labels.user, value: diagnostics.user }] : []),
  ];

  const handleCopy = async () => {
    const text = buildCopyText(diagnostics, {
      traceId: labels.traceId,
      errorCode: labels.errorCode,
      time: labels.time,
      version: labels.version,
      route: labels.route,
      user: labels.user,
    });
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard access is refused often enough in embedded browsers that the
      // textarea route is the actual path on some of them, not a rarity.
      const area = document.createElement('textarea');
      area.value = text;
      area.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
      document.body.appendChild(area);
      area.select();
      document.execCommand('copy');
      area.remove();
    }
    onCopied?.();
  };

  const handleDownload = () => {
    const blob = new Blob([buildLogFile(diagnostics)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = buildLogFileName(diagnostics);
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      role="alert"
      className={cn('flex min-h-full flex-col items-center justify-center gap-16 bg-white px-4 pt-4', className)}
    >
      <div className="flex flex-col items-center gap-4">
        {illustration}
        <p className="text-body-sm font-medium text-text-1/80">{labels.title}</p>
        <div className="max-w-[600px] text-center text-body-sm text-text-3">
          <p>{labels.description}</p>
          <p>
            {labels.copyBefore}
            {/* No underline, in either state: the line is one sentence of
                instructions, and a rule under part of it reads as emphasis the
                sentence does not want. The brand colour already marks it. */}
            <button type="button" onClick={handleCopy} className="text-blue-500 no-underline">
              {labels.copyLink}
            </button>
            {labels.copyAfter}
          </p>
        </div>
        <div className="flex items-start justify-center gap-4">
          <Button variant="outlined" color="default" onClick={onRefresh ?? (() => window.location.reload())}>
            {labels.refresh}
          </Button>
          <Button onClick={handleDownload}>{labels.download}</Button>
        </div>
      </div>

      <div className="relative flex w-full max-w-[600px] flex-col gap-4 rounded-xl border border-border-base p-4">
        {/* Straddles the border so the card reads as one region to screenshot. */}
        <span className="absolute -top-4 left-1/2 -translate-x-1/2 rounded-[32px] border border-border-base bg-white px-3 py-1 text-caption text-text-1/80">
          {labels.screenshotHint}
        </span>
        {/* Room for the code plus its inset, so a long value never runs under it. */}
        <div className="flex flex-col gap-4 pr-32">
          {rows.map((row) => (
            <DiagnosticRow key={row.label} label={row.label} value={row.value} />
          ))}
        </div>
        {/* Lowest error correction on purpose: the payload is already trimmed to
            stay legible at this size, and fewer modules survive a screenshot of
            a screenshot better than more redundancy at a smaller module size.

            The brand tint is applied in CSS rather than through `fgColor`: the
            colour is a CSS variable and SVG presentation attributes do not
            resolve var(). A rule beats the attribute, so this recolours the
            code and follows the theme with it. Only the second path is touched
            — the first is the light backing plate behind the modules. */}
        <QRCodeSVG
          value={buildQrPayload(diagnostics)}
          size={80}
          level="L"
          className="absolute right-4 top-4 [&>path:last-of-type]:fill-blue-500"
        />
      </div>
    </div>
  );
}
