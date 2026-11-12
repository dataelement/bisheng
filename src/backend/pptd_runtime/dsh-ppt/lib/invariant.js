//#region lib/types/invariant.js
/** Invariant companion reserving ownership for the Office PPT bundle. */
const PACKAGE_NAME = "dsh-ppt";
/** Companion plugin identity. */
const name = "dsh-ppt-invariant";
/** Required invariant registry. */
const inject = ["invariants"];
/** No runtime invariant: bounded storage and RPC checks run inside their owning services and handlers. */
const install = () => {};
/** Reserve package ownership while its composition is active. */
const apply = (ctx) => Promise.resolve(ctx.invariants.register(PACKAGE_NAME, install));
//#endregion
export { apply, inject, name };
