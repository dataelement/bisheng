/** The URL supplies a landing seed; explicit user switches own the later focus. */
type OrderIdentity = { id: string; number: string };
type UserTurn = { isCreatedByUser?: boolean; text?: string };

export function orderIdentityIntent(text: string, orders: OrderIdentity[]) {
  const numbered = text.match(/(?<![A-Za-z0-9_/-])(?:DEMO-ORDER-[A-Z0-9-]+|SIM-ORDER-\d+|26DMAC\/ZDA\d{3}(?:US|CH|HK))(?![A-Za-z0-9_/-])/gi) ?? [];
  const labelled = [...text.matchAll(/(?:订单(?:号)?|\border\s+(?:number\b|no\.?(?=\s|[:：#]))|注文番号)\s*[:：#]?\s*([A-Z0-9][A-Z0-9/_-]{2,79})/gi)].map(match => match[1]);
  const hasIdentity = (identity: string) => {
    const escaped = identity.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`(^|[^A-Za-z0-9_/-])${escaped}(?=$|[^A-Za-z0-9_/-])`, 'i').test(text);
  };
  const known = orders.filter(order => hasIdentity(order.number) || hasIdentity(order.id));
  const keys = new Set([...numbered, ...labelled, ...known.map(order => order.number)].map(key => {
    const match = orders.find(order => order.number.toLowerCase() === key.toLowerCase() || order.id.toLowerCase() === key.toLowerCase());
    return (match?.number ?? key).toLowerCase();
  }));
  const ordinal = /第[一二三四五六七八九十0-9]+(?:个|笔|项|条)|\b(?:first|second|third)\s+(?:order|one|item)|(?:最初|[一二三四五六七八九十0-9]+番目)の?(?:注文|項目)/i.test(text);
  const mentioned = keys.size > 0 || ordinal || /切换|换到|改查|另(?:一|外).*订单|switch\s+(?:to|order)|切り替|別の注文/i.test(text);
  const matches = orders.filter(order => [...keys].some(key => key === order.id.toLowerCase() || key === order.number.toLowerCase()));
  return { mentioned, order: mentioned && keys.size === 1 && matches.length === 1 ? matches[0] : undefined };
}

export function deriveOrderFocus(orders: OrderIdentity[], seed: string | null, messages: UserTurn[]) {
  let current = orders.find(order => order.number === seed || order.id === seed);
  for (const message of messages) {
    if (!message.isCreatedByUser) continue;
    const intent = orderIdentityIntent(message.text ?? '', orders);
    if (intent.mentioned) current = intent.order;
  }
  return current;
}
