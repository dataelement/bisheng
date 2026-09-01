/**
 * URLs handed to the OnlyOffice Document Server.
 *
 * The document server fetches the template and POSTs the save callback ITSELF,
 * server-side — so every URL we pass it must resolve from *its* network, not the
 * browser's. In local dev `location.origin` is `http://localhost:3001`, which the
 * (remote) document server resolves to its own container: the editor then hangs on
 * "loading" (template download fails) and saves never come back (callback fails).
 * The dev proxy does not help — it only covers browser → backend, not the reverse.
 *
 * Set `VITE_OFFICE_PUBLIC_ORIGIN` to an origin the document server can reach (your
 * LAN IP, or a tunnel) to override it. Unset in production, where the document
 * server and the app are reachable under the same origin.
 */
export function getOfficeReachableUrl(path = '/') {
    const override = String(
        (__APP_ENV__ as { OFFICE_PUBLIC_ORIGIN?: string }).OFFICE_PUBLIC_ORIGIN || '',
    ).replace(/\/$/, '');
    const origin = override || location.origin;
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return `${origin}${__APP_ENV__.BASE_URL || ''}${normalizedPath}`;
}
