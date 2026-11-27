import { deriveOrderFocus, orderIdentityIntent } from './orderFocus';

const orders = [{ id: 'SIM-ORDER-1', number: 'DEMO-ORDER-001' }, { id: 'SIM-ORDER-2', number: 'DEMO-ORDER-002' }];
const turns = (...texts: string[]) => texts.map(text => ({ text, isCreatedByUser: true }));

it('keeps a landing seed for a first deictic question and valid follow-up', () => {
  expect(deriveOrderFocus(orders, 'SIM-ORDER-1', turns('查看这笔订单', '那交期呢？'))?.number).toBe('DEMO-ORDER-001');
});
it('invalidates stale URL focus after an unknown switch and never revives it on a pronoun', () => {
  expect(deriveOrderFocus(orders, 'DEMO-ORDER-001', turns('查看这笔订单', '切换到 DEMO-ORDER-NOT-EXISTS', '那这单几天交付？'))).toBeUndefined();
});
it('invalidates ambiguous or incomplete switches, and permits an explicit valid replacement', () => {
  expect(deriveOrderFocus(orders, 'DEMO-ORDER-001', turns('切换到另一笔订单'))).toBeUndefined();
  expect(deriveOrderFocus(orders, 'DEMO-ORDER-001', turns('DEMO-ORDER-001 和 DEMO-ORDER-002'))).toBeUndefined();
  expect(deriveOrderFocus(orders, 'DEMO-ORDER-001', turns('切换到 DEMO-ORDER-NOT-EXISTS', '查看 DEMO-ORDER-002'))?.number).toBe('DEMO-ORDER-002');
});
it('recognizes unknown explicit identities without requiring them to occur in the dataset', () => {
  expect(orderIdentityIntent('查看 DEMO-ORDER-NOT-EXISTS', orders)).toEqual({ mentioned: true, order: undefined });
});
it('matches identity boundaries rather than SIM-ORDER-1 inside SIM-ORDER-10', () => {
  const more = [...orders, { id: 'SIM-ORDER-10', number: 'DEMO-ORDER-010' }];
  expect(orderIdentityIntent('show SIM-ORDER-10', more).order?.number).toBe('DEMO-ORDER-010');
});
it.each(['show order details', 'this order delivery date', 'この注文の納期は？'])('keeps pronoun focus for %s', text => {
  expect(deriveOrderFocus(orders, 'DEMO-ORDER-001', turns(text))?.number).toBe('DEMO-ORDER-001');
  expect(deriveOrderFocus(orders, 'DEMO-ORDER-001', turns('DEMO-ORDER-NOT-EXISTS', text))).toBeUndefined();
});
it.each(['show order number DEMO-ORDER-002', 'show order no. DEMO-ORDER-002', '注文番号DEMO-ORDER-002の納期を確認'])('accepts an explicit replacement: %s', text => {
  expect(deriveOrderFocus(orders, 'DEMO-ORDER-001', turns('DEMO-ORDER-NOT-EXISTS', text))?.number).toBe('DEMO-ORDER-002');
});
it.each(['查DEMO-ORDER-002还有几天', '查看DEMO-ORDER-002的物料', '注文DEMO-ORDER-002の納期'])('accepts an identity beside Chinese or Japanese: %s', text => {
  expect(orderIdentityIntent(text, orders).order?.number).toBe('DEMO-ORDER-002');
});
it('accepts a SIM identity beside Chinese text', () => {
  expect(orderIdentityIntent('查SIM-ORDER-1还有几天', orders).order?.number).toBe('DEMO-ORDER-001');
});
it.each(['查看第一个订单详情', 'show the first order details', '一番目の注文の詳細'])('clears a stale card for a selection without an authoritative row mapping: %s', text => {
  expect(deriveOrderFocus(orders, 'DEMO-ORDER-001', turns(text))).toBeUndefined();
});
