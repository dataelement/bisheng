/**
 * May this viewer read a channel's articles?
 *
 * The article endpoint gates on the F048 `visible` action, and the channel
 * detail reports the same decision in `actions` — so the client can tell in
 * advance whether a request would be refused, and show the intro-and-apply
 * view instead of asking. Asking anyway returns 403, and the global 403
 * handler navigates the viewer off the square entirely.
 *
 * Creator and subscriber are fallbacks, not independent rules: both hold
 * `visible`, but a detail response that omits `actions` should degrade to
 * showing the content rather than hiding it from someone who is plainly in.
 *
 * The predicate this replaced looked for a `view_channel` id inside a
 * `permission_ids` array. F048 retired both, so the array was always empty and
 * everyone who held a channel through a Grant rather than a subscription — a
 * department grant, say — was treated as having no access at all.
 */
export function canReadChannelContent(params: {
    actions?: readonly string[] | null;
    isSubscribed?: boolean;
    isCreatorView?: boolean;
}): boolean {
    const { actions, isSubscribed, isCreatorView } = params;
    // `actions` present — even empty — is the server's answer, so believe it.
    // A subscription row and a Grant are written by two different steps, and a
    // failure between them leaves a channel the square calls 已订阅 that the
    // viewer cannot actually read. Treating "subscribed" as access there meant
    // asking for the articles anyway, taking the 403, and losing the whole page
    // to the global redirect. Falling back only when the field is missing keeps
    // an older response shape working.
    if (Array.isArray(actions)) return actions.includes("visible");
    return Boolean(isSubscribed || isCreatorView);
}
