import React, { useState, useEffect, useCallback } from 'react';
import { Layers, X } from 'lucide-react';
export type Notice = (message: string, error?: boolean) => void;
export function ConfigSection({
  label,
  title,
  description,
  actions,
  children,
}: {
  label: string;
  title: React.ReactNode;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="panel" aria-label={label}>
      <div className="section-head">
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}
export function Badge({ children, tone = '' }: { children: React.ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function Empty({
  icon: Icon = Layers,
  title,
  text,
  children,
}: {
  icon?: typeof Layers;
  title: string;
  text: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={27} />
      </div>
      <h3>{title}</h3>
      <p>{text}</p>
      {children}
    </div>
  );
}
export function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="modal-shade" onClick={close}>
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="section-head">
          <h2>{title}</h2>
          <button className="icon-button" onClick={close} aria-label="Close">
            <X size={20} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
export function useLoad<T>(load: () => Promise<T>, deps: unknown[], notice?: Notice, interval = 0) {
  const [value, setValue] = useState<T>();
  const reload = useCallback(
    () =>
      load()
        .then(setValue)
        .catch((e) => notice?.(e.message, true)),
    deps,
  );
  useEffect(() => {
    void reload();
    if (interval) {
      const timer = setInterval(reload, interval);
      return () => clearInterval(timer);
    }
  }, [reload, interval]);
  return [value, reload] as const;
}

export function JsonField({
  label,
  value,
  change,
}: {
  label: string;
  value: unknown;
  change: (v: unknown) => void;
}) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const [err, setErr] = useState('');
  useEffect(() => {
    if (!err) setText(JSON.stringify(value, null, 2));
  }, [value]);
  return (
    <Field label={label}>
      <textarea
        className="mono"
        value={text}
        rows={6}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const v = JSON.parse(e.target.value);
            if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error();
            change(v);
            setErr('');
          } catch {
            setErr('Enter a JSON object');
          }
        }}
      />
      {err && <small className="danger">{err}</small>}
    </Field>
  );
}
