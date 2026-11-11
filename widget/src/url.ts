export function eventsUrl(apiBase: string, conversationId: string): string {
  const url = new URL(apiBase);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname =
    url.pathname.replace(/\/$/, '') + `/api/v1/events/${encodeURIComponent(conversationId)}`;
  url.search = '';
  url.hash = '';
  return url.toString();
}
