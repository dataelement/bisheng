import { advisorScene, advisorSearch, orderNavigation } from './scenes';

test('preserves only registered advisor and order context on conversation promotion', () => {
  expect(advisorScene('?agent=transport')).toBe('transport');
  expect(advisorScene('?agent=unknown')).toBe('');
  expect(advisorSearch('?agent=orders&order=SYNTHETIC-1&token=excluded')).toBe('?agent=orders&order=SYNTHETIC-1');
});

test('the iframe bridge rejects external, malformed and unrestricted destinations', () => {
  const origin = 'https://synthetic.example';
  expect(orderNavigation('https://other.example/workspace/c/new?agent=orders', origin)).toBeNull();
  expect(orderNavigation('http://[', origin)).toBeNull();
  expect(orderNavigation('/workspace/c/new?agent=transport', origin)).toBeNull();
  expect(orderNavigation('/workspace/c/new?agent=orders&redirect=/admin', origin)).toBeNull();
});
