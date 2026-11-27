export interface OrderLine { id: string; line: string | number; part: string; code: string; material: string; quantity: number; unit: string; price: number; amount: number; due: string | null }
export interface OrderInvoice { id: string; number: string; due: string | null; invoiceAmount: number }
export interface OrderSettlement { id: string; number: string; date: string | null; amount: number }
export interface WorkspaceOrder { id: string; number: string; supplier: string; customer: string; mock: boolean; amount: number; currency: string; lines: OrderLine[]; invoices: OrderInvoice[]; settlements: OrderSettlement[] }
export interface OrderDataset { asOf: string | null; orders: WorkspaceOrder[]; initialReminders: Record<string, Record<string, { mode: string; next?: string | null }>> }
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const safeId = (value: unknown) => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,100}$/.test(value);
const isDate = (value: unknown) => value === null || typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value));
const isText = (value: unknown) => typeof value === 'string' && value.length <= 1000;
const isNumber = (value: unknown) => typeof value === 'number' && Number.isFinite(value);

/** The legacy standalone renderer interpolates internal IDs into attributes. Validate that boundary. */
export function validateOrderDataset(raw: unknown): OrderDataset {
  if (!isRecord(raw) || !isDate(raw.asOf) || !Array.isArray(raw.orders) || raw.orders.length > 10000 || !isRecord(raw.initialReminders)) throw new Error('Invalid order dataset');
  const ids = new Set<string>();
  const numbers = new Set<string>();
  for (const order of raw.orders) {
    if (!isRecord(order) || !safeId(order.id) || !isText(order.number) || !order.number || !isText(order.supplier) || !isText(order.customer) || !isNumber(order.amount) || !isText(order.currency) || typeof order.mock !== 'boolean') throw new Error('Invalid order record');
    if (ids.has(order.id as string) || numbers.has(order.number as string)) throw new Error('Duplicate order identity');
    ids.add(order.id as string); numbers.add(order.number as string);
    for (const key of ['lines', 'invoices', 'settlements']) if (!Array.isArray(order[key]) || order[key].length > 10000) throw new Error('Invalid order rows');
    for (const line of order.lines as unknown[]) if (!isRecord(line) || !safeId(line.id) || !['string', 'number'].includes(typeof line.line) || !['part','code','material','unit'].every(key => isText(line[key])) || !['quantity','price','amount'].every(key => isNumber(line[key])) || !isDate(line.due)) throw new Error('Invalid order line');
    for (const invoice of order.invoices as unknown[]) if (!isRecord(invoice) || !safeId(invoice.id) || !isText(invoice.number) || !isNumber(invoice.invoiceAmount) || !isDate(invoice.due)) throw new Error('Invalid order invoice');
    for (const settlement of order.settlements as unknown[]) if (!isRecord(settlement) || !safeId(settlement.id) || !isText(settlement.number) || !isNumber(settlement.amount) || !isDate(settlement.date)) throw new Error('Invalid order settlement');
  }
  for (const [orderId, preferences] of Object.entries(raw.initialReminders)) {
    if (!ids.has(orderId) || !isRecord(preferences)) throw new Error('Invalid reminder owner');
    for (const [node, preference] of Object.entries(preferences)) {
      if (!['payment','delivery','settlement'].includes(node) || !isRecord(preference) || typeof preference.mode !== 'string' || !['default','7','30','off'].includes(preference.mode) || (preference.next !== undefined && !isDate(preference.next))) throw new Error('Invalid reminder preference');
    }
  }
  return raw as unknown as OrderDataset;
}

