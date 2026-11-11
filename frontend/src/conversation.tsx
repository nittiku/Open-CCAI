import React, { useState, useEffect, useRef } from 'react';
import { Bot as BotIcon, Send, Headphones, X } from 'lucide-react';
import { api, type Message, type Trace } from './api';
import { Badge, useLoad, type Notice } from './ui';
const human = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
export function Chat({
  conversationId,
  token,
  notice,
}: {
  conversationId: string;
  token: string;
  notice: Notice;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState('bot');
  const [stream, setStream] = useState('');
  const [text, setText] = useState('');
  const [connection, setConnection] = useState('Connecting');
  const [sending, setSending] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const pending = useRef<{ content: string; client_id: string } | undefined>(undefined);
  useEffect(() => {
    let stopped = false;
    let ws: WebSocket;
    let timer: ReturnType<typeof setTimeout>;
    let delay = 500;
    let response = '';
    function connect() {
      ws = new WebSocket(
        `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/events/${conversationId}`,
      );
      ws.onopen = () => {
        delay = 500;
        setConnection('Connected');
        ws.send(JSON.stringify({ token }));
      };
      ws.onmessage = (e) => {
        const event = JSON.parse(e.data);
        const p = event.payload;
        if (event.kind === 'snapshot') {
          setMessages(p.messages);
          setStatus(p.status);
          setStream('');
        }
        if (event.kind === 'message') {
          setMessages((old) => (old.some((m) => m.id === p.id) ? old : [...old, p]));
          setStream('');
        }
        if (event.kind === 'chunk') {
          if (response !== p.response_id) {
            response = p.response_id;
            setStream(p.text);
          } else setStream((s) => s + p.text);
        }
        if (event.kind === 'step') setStream('');
        if (event.kind === 'state') {
          setStatus(p.status);
          setStream('');
        }
      };
      ws.onclose = () => {
        if (!stopped) {
          setConnection('Reconnecting');
          timer = setTimeout(connect, delay);
          delay = Math.min(delay * 2, 15000);
        }
      };
    }
    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [conversationId, token]);
  useEffect(() => {
    scroll.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, stream]);
  const headers = { Authorization: `Bearer ${token}` };
  return (
    <div className="chat">
      <div className="chat-status">
        <i className={connection === 'Connected' ? 'online' : ''} />
        {connection}
        <Badge tone={status === 'agent' ? 'green' : ''}>{human(status)}</Badge>
      </div>
      <div className="chat-messages">
        {!messages.length && (
          <div className="chat-start">
            <BotIcon size={28} />
            <p>Starting your conversation…</p>
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`bubble-wrap ${m.role}`}>
            <small>
              {m.role === 'customer' ? 'You' : m.role === 'agent' ? 'Support agent' : 'Assistant'}
            </small>
            <div className="bubble">{m.content}</div>
            {m.sources?.length > 0 && (
              <small>Sources: {m.sources.map((s) => s.name).join(', ')}</small>
            )}
          </div>
        ))}
        {stream && (
          <div className="bubble-wrap bot">
            <small>Assistant · typing</small>
            <div className="bubble">
              {stream}
              <span className="typing-cursor" />
            </div>
          </div>
        )}
        <div ref={scroll} />
      </div>
      {['bot', 'queued', 'agent'].includes(status) ? (
        <form
          className="chat-compose"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!text.trim() || sending) return;
            setSending(true);
            if (!pending.current || pending.current.content !== text)
              pending.current = { content: text, client_id: crypto.randomUUID() };
            try {
              await api(`/widget/conversations/${conversationId}/messages`, {
                method: 'POST',
                headers,
                body: JSON.stringify(pending.current),
              });
              setText('');
              pending.current = undefined;
            } catch (err) {
              notice((err as Error).message, true);
            } finally {
              setSending(false);
            }
          }}
        >
          <input
            aria-label="Your message"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Write a message…"
            maxLength={16000}
          />
          <button
            className="primary icon-button"
            aria-label="Send message"
            disabled={sending || !text.trim()}
          >
            <Send size={17} />
          </button>
        </form>
      ) : (
        <p className="chat-ended">
          {status === 'error'
            ? 'This conversation encountered an error. Review the execution trace.'
            : 'This conversation has ended.'}
        </p>
      )}
      {status === 'bot' && (
        <button
          className="text-button chat-handoff"
          onClick={() =>
            api(`/widget/conversations/${conversationId}/handoff`, {
              method: 'POST',
              headers,
            }).catch((e) => notice(e.message, true))
          }
        >
          <Headphones size={14} />
          Talk to a person
        </button>
      )}
    </div>
  );
}
export function TracePanel({ cid, notice }: { cid: string; notice: Notice }) {
  const [rows] = useLoad<Trace[]>(() => api(`/conversations/${cid}/traces`), [cid], notice, 2500);
  return (
    <details className="trace-panel">
      <summary>
        Execution trace <span className="count">{rows?.length || 0}</span>
      </summary>
      {rows?.map((t) => (
        <div className="trace-row" key={t.id}>
          <Badge tone={t.status === 'error' ? 'red' : 'green'}>{t.status}</Badge>
          <code>{t.node_id.slice(0, 16)}</code>
          {t.detail.code && <small>{t.detail.code}</small>}
          {t.detail.route && (
            <small>
              Routed to {t.detail.route.target_type === 'flow' ? 'intent' : 'agent'}:{' '}
              {t.detail.route.name || t.detail.route.target_id.slice(0, 8)}
            </small>
          )}
          {t.detail.usage?.map((u, i) => (
            <small key={i}>
              {u.input_tokens + u.output_tokens} tokens · {Math.round(u.latency_ms)} ms
            </small>
          ))}
        </div>
      ))}
    </details>
  );
}

export function ConversationTest({
  session,
  title,
  close,
  notice,
}: {
  session: { conversation_id: string; token: string };
  title: string;
  close: () => void;
  notice: Notice;
}) {
  return (
    <div className="test-drawer global-test">
      <div className="section-head">
        <div>
          <h3>{title}</h3>
          <small className="muted">Test snapshot · changes require a new test</small>
        </div>
        <button className="icon-button" aria-label="Close test chat" onClick={close}>
          <X size={18} />
        </button>
      </div>
      <Chat conversationId={session.conversation_id} token={session.token} notice={notice} />
      <TracePanel cid={session.conversation_id} notice={notice} />
    </div>
  );
}
