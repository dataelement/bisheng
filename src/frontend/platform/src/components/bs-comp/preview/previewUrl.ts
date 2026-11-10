/** Preserve the platform gateway's existing file proxy routing. */
export function checkSassUrl(url: string): string {
  return url.replace(/https?:\/\/[^/]+/, __APP_ENV__.BASE_URL);
}
