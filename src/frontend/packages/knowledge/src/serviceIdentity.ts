const identities = new WeakMap<object, number>();
let nextIdentity = 0;

export function serviceIdentity(services: object): number {
  let identity = identities.get(services);
  if (identity === undefined) {
    identity = ++nextIdentity;
    identities.set(services, identity);
  }
  return identity;
}
