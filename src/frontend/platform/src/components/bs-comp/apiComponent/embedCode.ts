export type EmbedStyle = 'iframe' | 'script';

interface BuildEmbedCodeOptions {
  style: EmbedStyle;
  /** Chat page the embed opens, already including the deployment base path. */
  chatUrl: string;
  /** Browser origin, e.g. https://bisheng.example.com */
  origin: string;
  /** Platform base path (__APP_ENV__.BASE_URL): '' at the root, '/custom' under a sub-path. */
  baseUrl: string;
}

/**
 * Build the snippet a third-party site pastes to embed an app.
 * The script and icons are static files under platform/public, so they live
 * under the same base path as the chat link.
 */
export function buildEmbedCode({ style, chatUrl, origin, baseUrl }: BuildEmbedCodeOptions): string {
  const publicRoot = `${origin}${baseUrl}`;

  if (style === 'script') {
    return `<script
  src="${publicRoot}/iframe.js"
  id="chatbot-iframe-script"
  data-bot-src="${chatUrl}"
  data-drag="true"
  data-open-icon="${publicRoot}/assets/user.png"
  data-close-icon="${publicRoot}/assets/bisheng/logo-small-dark.png"
  defer
></script>
<script>console.log("chat ready")</script>
`;
  }

  return `<iframe
  src="${chatUrl}"
  style="width: 100%; height: 100%; min-height: 700px"
  frameborder="0"
  allow="fullscreen;clipboard-write">
</iframe>`;
}
