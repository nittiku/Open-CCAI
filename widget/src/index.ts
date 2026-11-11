import { eventsUrl } from './url';
/** Zero-dependency, isolated website channel. Tokens never enter URLs or logs. */
const script = document.currentScript as HTMLScriptElement | null;
const bot = script?.dataset.bot;
const project = script?.dataset.project;
const resource = project || bot;
const apiBase = (
  script?.dataset.api || (script ? new URL(script.src).origin : location.origin)
).replace(/\/$/, '');
const title = script?.dataset.title || 'How can we help?';
const style = `
:host{all:initial;font-family:system-ui,sans-serif;color:#244333;font-size:14px;line-height:1.5}*{box-sizing:border-box}button,input{font:inherit}button{cursor:pointer}button:disabled{opacity:.5;cursor:not-allowed}button:focus-visible,input:focus-visible{outline:2px solid #83b895;outline-offset:3px}.launcher{position:fixed;bottom:24px;right:24px;border:0;border-radius:50%;background:#24634f;color:white;width:58px;height:58px;box-shadow:0 4px 24px #174b3b30;font-size:24px}.panel{position:fixed;right:24px;bottom:94px;width:min(370px,calc(100vw - 32px));height:min(570px,calc(100dvh - 125px));border:1px solid #dce6d8;border-radius:15px;overflow:hidden;background:#fff;box-shadow:0 8px 48px #24433326;display:flex;flex-direction:column}.panel[hidden]{display:none}.head{background:#24634f;color:#fff;padding:20px;display:flex;align-items:center;justify-content:space-between}.head strong{font-size:16px}.close{border:0;background:transparent;color:inherit;padding:3px 7px;font-size:22px}.status{padding:9px 18px;font-size:11px;color:#8a9e7e;border-bottom:1px solid #e7eddf}.messages{flex:1;overflow:auto;background:#f9fbf6;padding:18px}.message{max-width:88%;margin:0 0 17px}.message small{display:block;color:#929f85;font-size:10px;margin:0 0 5px}.message p{margin:0;background:#fff;border:1px solid #e2ead8;border-radius:0 10px 10px 10px;padding:11px 13px;color:#546d43;font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere}.message.customer{margin-left:auto}.message.customer p{background:#edf4e6;border-radius:10px 0 10px 10px}.message.customer small{text-align:right}.sources{padding-top:4px;font-size:9px}.compose{display:flex;gap:8px;padding:14px;border-top:1px solid #e7eddf}.compose input{min-width:0;flex:1;border:0;background:transparent;padding:7px 3px;color:#3d5e33;font-size:13px}.compose button{border:0;background:#24634f;color:white;border-radius:6px;padding:8px 12px;font-size:13px}.handoff,.restart{background:none;color:#7c966b;border:0;font-size:11px;padding:7px;margin:0 auto 8px;display:block}.error{padding:9px 15px;background:#fff0e9;color:#995a41;font-size:11px}.error:empty{display:none}.footer{text-align:center;font-size:9px;color:#b4beac;padding:0 0 9px}.footer a{color:inherit}.ended{display:none}.hidden{display:none}@media(max-width:450px){.launcher{right:16px;bottom:16px}.panel{right:16px;bottom:85px}}
`;
type Message = { id: string; role: string; content: string; sources?: { name: string }[] };
type Session = { conversation_id: string; token: string };
function mount(botId: string) {
  const host = document.createElement('div');
  host.id = `open-ccai-${botId}`;
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: 'open' });
  const css = document.createElement('style');
  css.textContent = style;
  root.appendChild(css);
  const template = document.createElement('template');
  template.innerHTML = `<section class="panel" hidden role="dialog" aria-label="Customer support"><div class="head"><strong></strong><button class="close" aria-label="Close chat">×</button></div><div class="status">Start a conversation</div><div class="messages" role="log" aria-live="polite"></div><div class="error" role="alert"></div><form class="compose"><input aria-label="Your message" placeholder="Write a message…" maxlength="16000" autocomplete="off"/><button type="submit">Send</button></form><button class="handoff" type="button">Talk to a person</button><button class="restart hidden" type="button">Start a new conversation</button><div class="footer">Powered by Open-CCAI</div></section><button class="launcher" aria-label="Open support chat" aria-expanded="false">✦</button>`;
  root.appendChild(template.content.cloneNode(true));
  const q = <T extends HTMLElement>(selector: string) => root.querySelector<T>(selector)!;
  q('strong').textContent = title;
  const panel = q<HTMLElement>('.panel'),
    launcher = q<HTMLButtonElement>('.launcher'),
    messages = q<HTMLDivElement>('.messages'),
    error = q<HTMLDivElement>('.error'),
    statusLabel = q<HTMLDivElement>('.status'),
    input = q<HTMLInputElement>('input'),
    send = q<HTMLButtonElement>('.compose button'),
    handoff = q<HTMLButtonElement>('.handoff'),
    restart = q<HTMLButtonElement>('.restart');
  let session: Session | undefined,
    socket: WebSocket | undefined,
    retry: ReturnType<typeof setTimeout> | undefined,
    generation = 0,
    stopped = false,
    starting = false,
    sending = false;
  let rows: Message[] = [],
    stream = '',
    responseId = '',
    status = 'bot',
    pending: { content: string; client_id: string } | undefined;
  const storageKey = `open-ccai:${apiBase}:${project ? 'project:' : ''}${botId}`;
  try {
    session = JSON.parse(sessionStorage.getItem(storageKey) || 'null') || undefined;
  } catch {
    /* Storage may be disabled by website policy. */
  }
  async function request<T>(path: string, body?: unknown): Promise<T> {
    const r = await fetch(apiBase + '/api/v1' + path, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'omit',
      headers: {
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(session ? { Authorization: `Bearer ${session.token}` } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!r.ok) {
      if (r.status === 401) {
        restart.classList.remove('hidden');
        stopped = true;
        socket?.close();
      }
      const b = await r.json().catch(() => ({}));
      throw new Error(typeof b.detail === 'string' ? b.detail : `Request failed (${r.status})`);
    }
    return r.json();
  }
  function draw() {
    messages.replaceChildren();
    for (const m of [
      ...rows,
      ...(stream ? [{ id: 'stream', role: 'bot', content: stream }] : []),
    ]) {
      const div = document.createElement('div');
      div.className = `message ${m.role === 'customer' ? 'customer' : 'assistant'}`;
      const label = document.createElement('small');
      label.textContent =
        m.role === 'customer' ? 'You' : m.role === 'agent' ? 'Support agent' : 'Assistant';
      const text = document.createElement('p');
      text.textContent = m.content;
      div.append(label, text);
      if ('sources' in m && m.sources?.length) {
        const sources = document.createElement('small');
        sources.className = 'sources';
        sources.textContent = 'Sources: ' + m.sources.map((s) => s.name).join(', ');
        div.append(sources);
      }
      messages.appendChild(div);
    }
    messages.scrollTop = messages.scrollHeight;
    const active = ['bot', 'queued', 'agent'].includes(status);
    input.disabled = !active;
    send.disabled = !active || sending;
    handoff.classList.toggle('hidden', status !== 'bot');
    restart.classList.toggle('hidden', active);
    statusLabel.textContent =
      status === 'queued'
        ? 'Waiting for a support agent'
        : status === 'agent'
          ? 'Connected to a support agent'
          : status === 'closed'
            ? 'Conversation ended'
            : status === 'error'
              ? 'Conversation needs attention'
              : 'Connected to your assistant';
  }
  function connect() {
    if (!session || stopped) return;
    const ownGeneration = generation;
    socket = new WebSocket(eventsUrl(apiBase, session.conversation_id));
    const connection = socket;
    const ownToken = session.token;
    socket.onopen = () => connection.send(JSON.stringify({ token: ownToken }));
    socket.onmessage = (e) => {
      if (ownGeneration !== generation) return;
      const event = JSON.parse(e.data),
        p = event.payload;
      if (event.kind === 'snapshot') {
        rows = p.messages;
        status = p.status;
        stream = '';
        error.textContent = '';
      }
      if (event.kind === 'message') {
        if (!rows.some((m) => m.id === p.id)) rows.push(p);
        stream = '';
      }
      if (event.kind === 'state') {
        status = p.status;
        stream = '';
      }
      if (event.kind === 'chunk') {
        if (responseId !== p.response_id) {
          responseId = p.response_id;
          stream = '';
        }
        stream += p.text;
      }
      if (event.kind === 'step') stream = '';
      if (event.kind !== 'heartbeat') draw();
    };
    socket.onclose = () => {
      if (!stopped && ownGeneration === generation) {
        statusLabel.textContent = 'Reconnecting…';
        retry = setTimeout(async () => {
          try {
            await request(`/widget/conversations/${session!.conversation_id}/history`, {});
            if (!stopped && ownGeneration === generation) connect();
          } catch (e) {
            error.textContent = (e as Error).message;
            // An offline history probe must not permanently stop reconnecting.
            if (!stopped && ownGeneration === generation) retry = setTimeout(connect, 2000);
          }
        }, 2000);
      }
    };
  }
  async function start(fresh = false) {
    if (starting) return;
    starting = true;
    error.textContent = '';
    statusLabel.textContent = 'Connecting…';
    try {
      if (fresh) {
        generation++;
        stopped = true;
        socket?.close();
        clearTimeout(retry);
        session = undefined;
        rows = [];
        stream = '';
        pending = undefined;
        try {
          sessionStorage.removeItem(storageKey);
        } catch {}
      }
      if (session) {
        const history = await request<{ messages: Message[]; status: string }>(
          `/widget/conversations/${session.conversation_id}/history`,
          {},
        );
        rows = history.messages;
        status = history.status;
      } else {
        session = await request<Session>(
          `/widget/${project ? 'projects' : 'bots'}/${botId}/conversations`,
          {},
        );
        try {
          sessionStorage.setItem(storageKey, JSON.stringify(session));
        } catch {}
        status = 'bot';
      }
      stopped = false;
      draw();
      connect();
    } catch (e) {
      error.textContent = (e as Error).message;
      statusLabel.textContent = 'Unable to connect';
      restart.classList.remove('hidden');
    } finally {
      starting = false;
    }
  }
  launcher.onclick = () => {
    panel.hidden = !panel.hidden;
    launcher.setAttribute('aria-expanded', String(!panel.hidden));
    if (!panel.hidden) {
      if (!socket && !starting) void start();
      input.focus();
    }
  };
  q<HTMLButtonElement>('.close').onclick = () => {
    panel.hidden = true;
    launcher.setAttribute('aria-expanded', 'false');
    launcher.focus();
  };
  q<HTMLFormElement>('form').onsubmit = async (e) => {
    e.preventDefault();
    if (!input.value.trim() || !session || sending) return;
    sending = true;
    send.disabled = true;
    error.textContent = '';
    if (!pending || pending.content !== input.value)
      pending = { content: input.value, client_id: crypto.randomUUID() };
    try {
      await request(`/widget/conversations/${session.conversation_id}/messages`, pending);
      input.value = '';
      pending = undefined;
    } catch (err) {
      error.textContent = (err as Error).message;
    } finally {
      sending = false;
      send.disabled = false;
    }
  };
  handoff.onclick = async () => {
    if (!session) return;
    try {
      await request(`/widget/conversations/${session.conversation_id}/handoff`, {});
    } catch (e) {
      error.textContent = (e as Error).message;
    }
  };
  restart.onclick = () => void start(true);
  panel.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      panel.hidden = true;
      launcher.setAttribute('aria-expanded', 'false');
      launcher.focus();
    }
  });
  window.addEventListener('pagehide', () => {
    stopped = true;
    clearTimeout(retry);
    socket?.close();
  });
  window.addEventListener('pageshow', (event) => {
    if (event.persisted && session) {
      stopped = false;
      connect();
    }
  });
}
if (resource) {
  if (document.body) mount(resource);
  else document.addEventListener('DOMContentLoaded', () => mount(resource), { once: true });
}
