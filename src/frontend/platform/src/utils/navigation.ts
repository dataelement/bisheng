export function navigateBackOrFallback(fallbackUrl: string) {
    if (window.history.length > 1 && document.referrer) {
        window.history.back();
        return;
    }

    window.location.href = fallbackUrl;
}
