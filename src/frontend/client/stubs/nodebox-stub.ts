/**
 * Stub for @codesandbox/nodebox (Sustainable Use License — source-available,
 * commercial-redistribution restricted). The real package is only pulled in by
 * Sandpack's *node* runtime client, which this app never uses: Artifacts only
 * renders `static` / `react-ts` templates via the hosted browser bundler.
 *
 * Aliasing the import to this stub (see vite.config.ts resolve.alias) keeps the
 * SUL-licensed runtime out of the shipped bundle so the commercial edition does
 * not redistribute it. If a Node-based Sandpack template is ever introduced,
 * remove the alias and revisit the licensing implications.
 */
export const INJECT_MESSAGE_TYPE = '__nodebox_disabled_inject__';
export const PREVIEW_LOADED_MESSAGE_TYPE = '__nodebox_disabled_preview_loaded__';

export class MessageReceiver {}
export class MessageSender {}

export class Nodebox {
  constructor() {
    // Node runtime is intentionally disabled in this build.
  }
  async connect(): Promise<never> {
    throw new Error('[nodebox stub] Node Sandpack runtime is disabled in this build.');
  }
}

export default {
  Nodebox,
  MessageReceiver,
  MessageSender,
  INJECT_MESSAGE_TYPE,
  PREVIEW_LOADED_MESSAGE_TYPE,
};
