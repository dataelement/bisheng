import assert from 'node:assert/strict';
import { test } from 'node:test';
import cn from '../src/utils/cn.ts';

test('Tooltip keeps white text alongside its semantic body size', () => {
  const classes = cn(
    'bg-tooltip text-white z-tooltip max-w-[250px] break-words rounded-md px-3 py-1.5 text-body shadow-popup',
  ).split(' ');

  assert.ok(classes.includes('text-white'));
  assert.ok(classes.includes('text-body'));
  assert.ok(classes.includes('bg-tooltip'));
});

test('every semantic size preserves text colors in either order', () => {
  const sizes = ['caption-sm', 'caption', 'body-sm', 'body', 'h1', 'h2', 'h3', 'h4', 'display', 'metric'];
  for (const size of sizes) {
    assert.equal(cn(`text-${size}`, 'text-text-1'), `text-${size} text-text-1`);
    assert.equal(cn('text-white', `text-${size}`), `text-white text-${size}`);
  }
});

test('size and color overrides still merge independently', () => {
  assert.equal(cn('text-white text-body', 'text-caption'), 'text-white text-caption');
  assert.equal(cn('text-body text-white', 'text-text-2'), 'text-body text-text-2');
  assert.equal(cn('text-sm text-body', 'text-lg'), 'text-lg');
  assert.equal(cn('px-3', false, null, undefined, 'px-4'), 'px-4');
});
