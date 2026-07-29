/**
 * design-token SSOT has moved to the shared component library —
 * packages/ui/design-token.cjs (`@bisheng/ui/design-token`).
 *
 * This shim keeps every existing consumer working unchanged
 * (tailwind.docs.config.cjs `require('./src/design-token.cjs')`,
 * mdx pages `import tokens from '~/design-token'`).
 * New code should import '@bisheng/ui/design-token' directly.
 */
module.exports = require('@bisheng/ui/design-token');
