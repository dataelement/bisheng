import DOMPurify, { type Config } from 'dompurify';

/**
 * Sanitize an untrusted HTML string before it is fed to
 * `dangerouslySetInnerHTML`, stripping scripts, inline event handlers
 * (onerror/onclick/...) and javascript: URLs while preserving normal
 * formatting markup (tables, images, emphasis, links, etc.).
 *
 * Only apply this at trust boundaries where the HTML can originate from
 * external feeds or other users' content — do NOT use it as a blanket wrapper
 * for first-party/admin-authored markup.
 */
export function sanitizeHtml(dirty: string, config?: Config): string {
  if (!dirty) return '';
  // `RETURN_TRUSTED_TYPE: false` guarantees a plain string return regardless of
  // the config passed in, so the result is always assignable to __html.
  return DOMPurify.sanitize(dirty, { ...config, RETURN_TRUSTED_TYPE: false }) as string;
}
