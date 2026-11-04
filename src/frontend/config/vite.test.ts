import { EventEmitter } from 'node:events';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { createFrontendProxy, loadFrontendEnv, resolveApiTarget } from './vite';

// These cover the cross-app contract: environment precedence and authenticated WS forwarding.
describe('shared frontend environment and proxy', () => {
  it('loads workspace defaults and lets app-local values override them', () => {
    const root = mkdtempSync(path.join(os.tmpdir(), 'bisheng-env-'));
    const app = path.join(root, 'platform');
    mkdirSync(app);
    writeFileSync(
      path.join(root, '.env.development'),
      'VITE_API_PROXY_TARGET=http://workspace:7860\nVITE_SHARED=value\n',
    );
    writeFileSync(
      path.join(app, '.env.development.local'),
      'VITE_API_PROXY_TARGET=http://app:8180\n',
    );
    try {
      const env = loadFrontendEnv('development', app);
      expect(env.VITE_API_PROXY_TARGET).toBe('http://app:8180');
      expect(env.VITE_SHARED).toBe('value');
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it('supports both legacy API names and gives the common name precedence', () => {
    expect(resolveApiTarget({})).toBe('http://127.0.0.1:7860');
    expect(resolveApiTarget({ VITE_PROXY_TARGET: 'http://gateway:8180' })).toBe(
      'http://gateway:8180',
    );
    expect(
      resolveApiTarget(
        { VITE_DEV_API_TARGET: 'http://backend:7860' },
        'VITE_DEV_API_TARGET',
      ),
    ).toBe('http://backend:7860');
    expect(
      resolveApiTarget({
        VITE_API_PROXY_TARGET: 'http://common:7860',
        VITE_PROXY_TARGET: 'http://old:7860',
      }),
    ).toBe('http://common:7860');
  });

  it('strips the client base prefix and forwards the browser host for ASR sockets', () => {
    const options = createFrontendProxy('http://backend:7860', {
      rewrite: (url) => url.replace(/^\/workspace/, ''),
    });
    expect(options.rewrite?.('/workspace/api/v1/settings')).toBe(
      '/api/v1/settings',
    );
    expect(options).toMatchObject({ changeOrigin: true, xfwd: true, ws: true });
    const proxy = new EventEmitter();
    options.configure?.(proxy as never, options);
    const setHeader = vi.fn();
    proxy.emit(
      'proxyReqWs',
      { setHeader },
      { headers: { host: 'localhost:4001' } },
    );
    expect(setHeader).toHaveBeenCalledWith(
      'x-forwarded-host',
      'localhost:4001',
    );
  });
});

import cn from '../packages/ui/src/utils/cn';
import clientCn from '../client/src/utils/cn';

describe('shared semantic class merging', () => {
  it.each([
    ['shared', cn],
    ['client', clientCn],
  ] as const)('%s keeps font size and color independent', (_, merge) => {
    expect(merge('text-body text-text-1', 'text-h4 text-danger')).toBe(
      'text-h4 text-danger',
    );
    expect(
      merge('hover:text-body hover:text-text-1', 'hover:text-caption'),
    ).toBe('hover:text-text-1 hover:text-caption');
    expect(merge('w-8 h-8', 'size-4')).toBe('size-4');
  });
});

import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import postcss from 'postcss';
import tailwindcss from 'tailwindcss';

const require = createRequire(import.meta.url);
const loadTailwind =
  require('tailwindcss/loadConfig') as typeof import('tailwindcss/loadConfig');
const resolveTailwind =
  require('tailwindcss/resolveConfig') as typeof import('tailwindcss/resolveConfig');
const frontendDirectory = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
);

describe('both apps use the same design foundation', () => {
  const configs = [
    'platform/tailwind.config.js',
    'client/tailwind.config.cjs',
  ].map((file) => loadTailwind(path.join(frontendDirectory, file)));

  it('uses the shared system font stack and touch hover policy', () => {
    const [platform, client] = configs.map((config) => resolveTailwind(config));
    expect(platform.theme.fontFamily.sans).toEqual(
      client.theme.fontFamily.sans,
    );
    expect(platform.important).toBe(false);
    expect(client.important).toBe(false);
    expect(platform.future).toMatchObject({ hoverOnlyWhenSupported: true });
    expect(client.future).toMatchObject({ hoverOnlyWhenSupported: true });
  });

  it.each([0, 1])(
    'compiles semantic type/color and explicit scrollbar hiding in app %i',
    async (index) => {
      const config = configs[index];
      const result = await postcss([
        tailwindcss({
          ...config,
          content: [
            { raw: 'text-body text-danger no-scrollbar w-4 hover:bg-blue-500' },
          ],
          safelist: [],
        }),
      ]).process('@tailwind base; @tailwind components; @tailwind utilities;', {
        from: undefined,
      });
      const selectors: string[] = [];
      result.root.walkRules((rule) => {
        selectors.push(rule.selector);
      });
      expect(selectors).toContain('.text-body');
      expect(selectors).toContain('.text-danger');
      expect(
        selectors.some((selector) => selector.includes('.no-scrollbar')),
      ).toBe(true);
      const widths: boolean[] = [];
      result.root.walkRules('.w-4', (rule) => {
        rule.walkDecls('width', (decl) => {
          widths.push(Boolean(decl.important));
        });
      });
      expect(widths).toEqual([false]);
      expect(result.css).toContain('@media (hover: hover)');
    },
  );
});

import { loadConfigFromFile } from 'vite';

it('loads both real Vite configs with separate API, license and object-storage routes', async () => {
  vi.stubEnv('VITE_API_PROXY_TARGET', 'http://api.example:7860');
  vi.stubEnv('VITE_MINIO_PROXY_TARGET', 'http://objects.example:9000');
  vi.stubEnv('VITE_GATEWAY_PROXY_TARGET', 'http://gateway.example:8180');
  vi.stubEnv('VITE_APP_PROXY_TARGET', 'http://app-entry.example:3001');
  const log = vi.spyOn(console, 'log').mockImplementation(() => {});
  try {
    const platform = (await loadConfigFromFile(
      { command: 'serve', mode: 'test' },
      path.join(frontendDirectory, 'platform/vite.config.mts'),
    ))!.config;
    const client = (await loadConfigFromFile(
      { command: 'serve', mode: 'test' },
      path.join(frontendDirectory, 'client/vite.config.ts'),
    ))!.config;
    expect(platform.server).toMatchObject({ port: 3001, strictPort: true });
    expect(client.server).toMatchObject({ port: 4001, strictPort: true });
    expect(Object.keys(platform.server!.proxy!)[0]).toBe('/api/license');
    expect(platform.server!.proxy!['/api/']).toMatchObject({
      target: 'http://api.example:7860',
      ws: true,
    });
    expect(platform.server!.proxy!['/api/license']).toMatchObject({
      target: 'http://gateway.example:8180',
    });
    expect(platform.server!.proxy!['/bisheng']).toMatchObject({
      target: 'http://objects.example:9000/',
    });
    expect(platform.server!.proxy!['/apps/']).toMatchObject({
      target: 'http://app-entry.example:3001',
      changeOrigin: true,
      xfwd: true,
      ws: true,
    });
    expect(client.base).toBe('/workspace');
    expect(client.server!.proxy!['/workspace/api']).toMatchObject({
      target: 'http://api.example:7860',
      ws: true,
    });
    expect(client.server!.proxy!['/workspace/tmp-dir']).toMatchObject({
      target: 'http://objects.example:9000',
    });
  } finally {
    log.mockRestore();
    vi.unstubAllEnvs();
  }
});

import { readFileSync } from 'node:fs';
import { frontendEnvDefinitions } from './vite';

it('applies the same env precedence to browser code without exposing unprefixed secrets', () => {
  expect(
    frontendEnvDefinitions({
      VITE_FROSTED_GLASS: 'false',
      SECRET_TOKEN: 'private',
      DOMAIN_NAME: 'corp',
    }),
  ).toEqual({
    'import.meta.env.VITE_FROSTED_GLASS': '"false"',
  });
  expect(
    frontendEnvDefinitions({ DOMAIN_NAME: 'corp' }, ['VITE_', 'DOMAIN_']),
  ).toEqual({
    'import.meta.env.DOMAIN_NAME': '"corp"',
  });
});

it('emits Tailwind only once and leaves default platform scrollbars native', () => {
  let tailwindDirectives = 0;
  for (const file of ['App.css', 'style/index.css', 'style/applies.css']) {
    const css = postcss.parse(
      readFileSync(path.join(frontendDirectory, 'platform/src', file), 'utf8'),
    );
    css.walkAtRules('tailwind', () => {
      tailwindDirectives += 1;
    });
    css.walkRules((rule) => {
      expect(rule.selector).not.toMatch(
        /^(?:\.dark\s+)?(?:::-webkit-scrollbar|\*:hover::?-webkit-scrollbar)/,
      );
    });
  }
  expect(tailwindDirectives).toBe(3);
});
