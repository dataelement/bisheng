import { validateOrderDataset } from './orderContracts';
const order = { id:'SYNTHETIC-1',number:'SYNTHETIC-ORDER-001',supplier:'Synthetic supplier',customer:'Synthetic customer',mock:true,amount:100,currency:'CNY',lines:[{id:'line1',line:1,part:'SYNTH-PART',code:'SYNTH',material:'Synthetic material',quantity:2,unit:'EA',price:50,amount:100,due:'2026-11-26'}],invoices:[],settlements:[] };
const dataset = () => ({ asOf:'2026-11-26',orders:[structuredClone(order)],initialReminders:{} });
test('accepts the published runtime order contract and its empty state', () => {
  expect(validateOrderDataset(dataset()).orders).toHaveLength(1);
  expect(validateOrderDataset({asOf:null,orders:[],initialReminders:{}}).orders).toHaveLength(0);
});
test('rejects unsafe IDs before the legacy standalone view interpolates them', () => {
  const value = dataset(); value.orders[0].id = '" onmouseover="alert(1)';
  expect(() => validateOrderDataset(value)).toThrow('Invalid order record');
});
test('rejects duplicate identity and unregistered reminder owners', () => {
  const value = dataset();value.orders.push(structuredClone(order));
  expect(() => validateOrderDataset(value)).toThrow('Duplicate order identity');
  expect(() => validateOrderDataset({...dataset(),initialReminders:{other:{delivery:{mode:'off'}}}})).toThrow('Invalid reminder owner');
});
