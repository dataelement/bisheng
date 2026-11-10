export function getCitationAccessScope(): string {
  return JSON.stringify([location.pathname,localStorage.getItem('ws_token'),localStorage.getItem('bs:auth-state'),document.cookie]);
}
