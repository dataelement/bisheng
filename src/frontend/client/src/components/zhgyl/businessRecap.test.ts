import { readBusinessRecap } from './recapProtocol';
const className = 'language-business-process';
const record = { version: 1, mode: 'execution_recap', scene: 'transport', nodes: [{ title: 'Synthetic step', summary: '<img src=x onerror=alert(1)>', status: 'waiting', details: ['Synthetic evidence'] }] };

test('accepts a bounded record in its advisor or a generic historical conversation', () => {
  expect(readBusinessRecap(JSON.stringify(record), 'transport', className).kind).toBe('valid');
  expect(readBusinessRecap(JSON.stringify(record), 'customs', className).kind).toBe('invalid');
  expect(readBusinessRecap(JSON.stringify(record), '', className).kind).toBe('valid');
});

test('streaming and malformed metadata never fall back to a raw JSON code block', () => {
  expect(readBusinessRecap('{"version":1,"scene":"transport",', 'transport', className).kind).toBe('pending');
  expect(readBusinessRecap(JSON.stringify({ ...record, nodes: [{ ...record.nodes[0], status: 'invented' }] }), 'transport', className).kind).toBe('invalid');
  expect(readBusinessRecap('x'.repeat(30001), 'transport', className).kind).toBe('invalid');
});

test('repairs only the established transport missing closing brace case', () => {
  const text = JSON.stringify(record);
  expect(readBusinessRecap(text.slice(0, -1), 'transport', className).kind).toBe('valid');
  expect(readBusinessRecap(text.slice(0, -1), 'customs', className).kind).toBe('pending');
});

test('legacy business alias is limited to transport recap envelopes', () => {
  expect(readBusinessRecap(JSON.stringify(record), 'transport', 'language-business').kind).toBe('valid');
  expect(readBusinessRecap('{"ordinary":"business data"}', 'transport', 'language-business').kind).toBe('other');
});

test('does not claim other fenced-code dialects', () => {
  expect(readBusinessRecap(JSON.stringify(record), 'transport', 'language-business-process-extra').kind).toBe('other');
});
