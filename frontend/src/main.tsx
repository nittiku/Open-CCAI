import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  applyNodeChanges,
  type NodeChange,
  type Connection,
  type NodeProps,
  type Node,
} from '@xyflow/react';
import {
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  Upload,
  BookOpen,
  Bot as BotIcon,
  Check,
  ChevronDown,
  CircleHelp,
  Code2,
  GitBranch,
  Headphones,
  Inbox,
  KeyRound,
  Layers,
  Loader2,
  LogOut,
  MessageCircle,
  MoreHorizontal,
  Plus,
  Radio,
  Rocket,
  Save,
  Send,
  Settings,
  Shield,
  Trash2,
  Users,
  Workflow,
  X,
} from 'lucide-react';
import {
  api,
  post,
  put,
  download,
  type Bot,
  type Project,
  type FullAgent,
  type User,
  type Flow,
  type FlowNode,
  type Provider,
  type Tool,
  type Collection,
  type Queue,
  type Conversation,
  type Message,
  type Trace,
} from './api';
import '@xyflow/react/dist/style.css';
import './style.css';
import { Badge, Field, Empty, Modal, useLoad, JsonField, type Notice } from './ui';
import { Chat, TracePanel } from './conversation';
import { ProjectWorkspace } from './ProjectWorkspace';
import { AgentStudio } from './AgentStudio';

type Page =
  'projects' | 'agents' | 'tools' | 'builder' | 'knowledge' | 'inbox' | 'connections' | 'team';
const icons = {
  message: MessageCircle,
  input: CircleHelp,
  condition: GitBranch,
  variable: Code2,
  tool: Code2,
  knowledge: BookOpen,
  ai: BotIcon,
  agent: BotIcon,
  handoff: Headphones,
  end: Check,
};
const labels: Record<string, string> = {
  message: 'Send a message',
  input: 'Collect input',
  condition: 'Condition',
  variable: 'Set variable',
  tool: 'HTTP tool',
  knowledge: 'Search knowledge',
  ai: 'Mini agent',
  agent: 'Agent',
  handoff: 'Human handoff',
  end: 'End conversation',
};
const human = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const ago = (t: number) => {
  const m = Math.floor((Date.now() / 1000 - t) / 60);
  return m < 1 ? 'Just now' : m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ago`;
};
function Auth({ done }: { done: (u: User) => void }) {
  const [initialized, setInitialized] = useState<boolean>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const invitation = new URLSearchParams(location.search).get('invitation');
  useEffect(() => {
    api<{ initialized: boolean }>('/auth/status')
      .then((s) => setInitialized(s.initialized))
      .catch((e) => setError(e.message));
  }, []);
  return (
    <div className="auth-screen">
      <div className="auth-story">
        <div className="brand light">
          <div className="brand-symbol">
            <Workflow />
          </div>
          open<span>ccai</span>
        </div>
        <div>
          <span className="eyebrow">YOUR INFRASTRUCTURE. YOUR AUTOMATION.</span>
          <h1>
            Conversations,
            <br />
            without constraints.
          </h1>
          <p>
            Build thoughtful customer experiences.
            <br />
            Keep control of your platform, providers, and data.
          </p>
        </div>
        <span className="auth-foot">Open source · Apache 2.0 · Built to be yours</span>
      </div>
      <div className="auth-form">
        <Badge tone="green">Open-CCAI / Console</Badge>
        <h2>
          {invitation
            ? 'Join your team'
            : initialized === false
              ? 'Make yourself at home'
              : 'Welcome back'}
        </h2>
        <p>
          {initialized === false
            ? 'Create the first administrator for this installation.'
            : 'Sign in to your contact center workspace.'}
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError('');
            const data = Object.fromEntries(new FormData(e.currentTarget));
            try {
              const u = await post<User>(
                invitation ? '/auth/accept' : initialized ? '/auth/login' : '/auth/setup',
                { ...data, ...(invitation ? { invitation_token: invitation } : {}) },
              );
              history.replaceState({}, '', '/');
              done(u);
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="Work email">
            <input
              name="email"
              type="email"
              autoComplete="username"
              required
              placeholder="you@organization.com"
            />
          </Field>
          <Field label="Password" hint="At least 12 characters.">
            <input
              name="password"
              type="password"
              minLength={12}
              maxLength={256}
              autoComplete={initialized ? 'current-password' : 'new-password'}
              required
            />
          </Field>
          {initialized === false && (
            <Field
              label="Installation setup token"
              hint="Find SETUP_TOKEN in the deployment environment."
            >
              <input name="setup_token" type="password" required />
            </Field>
          )}
          {error && (
            <div className="error-box" role="alert">
              {error}
            </div>
          )}
          <button className="primary wide" disabled={busy || initialized === undefined}>
            {busy ? <Loader2 className="spin" size={16} /> : <ArrowRight size={16} />}{' '}
            {invitation
              ? 'Accept invitation'
              : initialized === false
                ? 'Create workspace'
                : 'Sign in'}
          </button>
        </form>
        <small className="muted">Credentials stay on your installation.</small>
      </div>
    </div>
  );
}

function App() {
  const [user, setUser] = useState<User | null>();
  const [page, setPage] = useState<Page>('projects');
  const [toast, setToast] = useState<{ message: string; error: boolean }>();
  const [botId, setBotId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const notice = useCallback<Notice>((message, error = false) => setToast({ message, error }), []);
  useEffect(() => {
    api<User>('/auth/me')
      .then(setUser)
      .catch(() => setUser(null));
  }, []);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(undefined), 7000);
      return () => clearTimeout(t);
    }
  }, [toast]);
  const canBuild = user?.role === 'administrator' || user?.role === 'builder';
  const canOperate = !!user && user.role !== 'builder';
  const [bots, refreshBots] = useLoad<Bot[]>(
    () => (canBuild ? api('/bots') : Promise.resolve([])),
    [canBuild],
    notice,
  );
  const [projects, refreshProjects] = useLoad<Project[]>(
    () => (canBuild ? api('/projects') : Promise.resolve([])),
    [canBuild],
    notice,
  );
  const [agents, refreshAgents] = useLoad<FullAgent[]>(
    () => (canBuild ? api('/agents') : Promise.resolve([])),
    [canBuild],
    notice,
  );
  const project = projects?.find((p) => p.id === projectId);
  const projectBots = (bots || []).filter((b) => b.project_id === projectId);
  useEffect(() => {
    if (projects && projectId && !projects.some((p) => p.id === projectId)) setProjectId('');
  }, [projects, projectId]);
  const [providers, refreshProviders] = useLoad<Provider[]>(
    () => (canBuild ? api('/providers') : Promise.resolve([])),
    [canBuild],
    notice,
  );
  const [queues, refreshQueues] = useLoad<Queue[]>(
    () => (user ? api('/queues') : Promise.resolve([])),
    [user?.id],
    notice,
  );
  useEffect(() => {
    const available = (bots || []).filter((b) => b.project_id === projectId);
    if (!available.some((b) => b.id === botId)) setBotId(available[0]?.id || '');
  }, [bots, botId, projectId]);
  useEffect(() => {
    if (user && !canBuild && page === 'projects') setPage('inbox');
  }, [user, canBuild, page]);
  if (user === undefined)
    return (
      <div className="loading">
        <Loader2 className="spin" /> Opening workspace…
      </div>
    );
  if (!user) return <Auth done={setUser} />;
  const bot = bots?.find((b) => b.id === botId);
  const titles = {
    projects: 'Projects & orchestration',
    agents: 'Agent builder',
    tools: 'Shared tools',
    builder: 'Flow studio',
    knowledge: 'Knowledge',
    inbox: 'Agent inbox',
    connections: 'Connections',
    team: 'Team & access',
  };
  const nav: { id: Page; label: string; icon: typeof Layers; show: boolean }[] = [
    { id: 'projects', label: 'Projects', icon: GitBranch, show: canBuild },
    { id: 'agents', label: 'Agent builder', icon: BotIcon, show: canBuild },
    { id: 'tools', label: 'Shared tools', icon: Code2, show: canBuild },
    { id: 'builder', label: 'Flow studio', icon: Workflow, show: canBuild },
    { id: 'knowledge', label: 'Knowledge', icon: BookOpen, show: canBuild },
    { id: 'inbox', label: 'Agent inbox', icon: Inbox, show: canOperate },
    { id: 'connections', label: 'Connections', icon: KeyRound, show: canBuild },
    { id: 'team', label: 'Team & access', icon: Users, show: user.role === 'administrator' },
  ];
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/" onClick={(e) => e.preventDefault()}>
          <div className="brand-symbol">
            <Workflow size={23} />
          </div>
          open<span>ccai</span>
          <span className="version">α</span>
        </a>
        <div className="workspace-switch">
          <span className="workspace-letter">W</span>
          <div>
            {canBuild && projects?.length ? (
              <select
                aria-label="Current project"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
              >
                <option value="">Select a project</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            ) : (
              <strong>Your workspace</strong>
            )}
            <small>{canBuild ? 'Project workspace' : 'Self-hosted installation'}</small>
          </div>
          <ChevronDown size={15} />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {nav
            .filter((n) => n.show)
            .map((n) => (
              <button
                className={page === n.id ? 'active' : ''}
                key={n.id}
                onClick={() => setPage(n.id)}
              >
                <n.icon size={18} />
                {n.label}
                {page === n.id && <span className="nav-dot" />}
              </button>
            ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="ownership">
            <Shield size={18} />
            <div>
              <strong>Open by design</strong>
              <p>
                Your keys. Your data.
                <br />
                Your deployment.
              </p>
            </div>
          </div>
          <div className="user-menu">
            <div className="avatar">{user.email[0].toUpperCase()}</div>
            <div>
              <strong title={user.email}>{user.email}</strong>
              <small>{human(user.role)}</small>
            </div>
            <button
              className="icon-button"
              aria-label="Sign out"
              onClick={() =>
                post('/auth/logout')
                  .then(() => {
                    setUser(null);
                    setPage('projects');
                    setProjectId('');
                    setBotId('');
                  })
                  .catch((e) => notice(e.message, true))
              }
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <span className="muted">Workspace</span>
            <span className="slash">/</span>
            <strong>{titles[page]}</strong>
          </div>
          <div className="topbar-right">
            <span className="deployment">
              <i />
              Self-hosted
            </span>
            <span className="separator" />
            <span className="small">v0.1.0</span>
          </div>
        </header>
        <main className={page === 'builder' ? 'studio-main' : 'content'}>
          {page === 'projects' && (
            <ProjectWorkspace
              projects={projects || []}
              projectId={projectId}
              select={setProjectId}
              flows={bots || []}
              agents={agents || []}
              providers={providers || []}
              queues={queues || []}
              refresh={refreshProjects}
              notice={notice}
              newFlow={() => setCreating(true)}
              openFlow={(id) => {
                setBotId(id);
                setPage('builder');
              }}
              openAgents={() => setPage('agents')}
            />
          )}
          {page === 'agents' && (
            <AgentStudio
              project={project}
              projects={projects || []}
              agents={(agents || []).filter((a) => !projectId || a.project_id === projectId)}
              providers={providers || []}
              flows={bots || []}
              refresh={refreshAgents}
              notice={notice}
              openProjects={() => setPage('projects')}
              openTools={() => setPage('tools')}
            />
          )}
          {page === 'tools' && (
            <Connections
              key="shared-tools"
              toolsOnly
              providers={providers || []}
              refresh={refreshProviders}
              notice={notice}
              admin={user.role === 'administrator'}
            />
          )}
          {page === 'builder' &&
            (bot ? (
              <Builder
                key={bot.id}
                bot={bot}
                bots={projectBots}
                selectBot={setBotId}
                providers={providers || []}
                queues={queues || []}
                refresh={refreshBots}
                notice={notice}
                create={() => setCreating(true)}
                importFlow={() => setImporting(true)}
              />
            ) : (
              <Empty
                icon={Workflow}
                title="Your first conversation starts here"
                text="Create an intent, connect its steps, and enable it in your project orchestrator."
              >
                <button className="primary" onClick={() => setCreating(true)}>
                  <Plus size={16} />
                  Create intent
                </button>
                <button className="secondary" onClick={() => setImporting(true)}>
                  <Upload size={15} /> Import flow
                </button>
              </Empty>
            ))}
          {page === 'knowledge' && (
            <Knowledge bots={projectBots} providers={providers || []} notice={notice} />
          )}
          {page === 'inbox' && (
            <AgentInbox user={user} updateUser={setUser} queues={queues || []} notice={notice} />
          )}
          {page === 'connections' && (
            <Connections
              key="model-connections"
              providers={providers || []}
              refresh={refreshProviders}
              notice={notice}
              admin={user.role === 'administrator'}
            />
          )}
          {page === 'team' && (
            <Team queues={queues || []} refreshQueues={refreshQueues} notice={notice} />
          )}
        </main>
      </div>
      {toast && (
        <div className={`toast ${toast.error ? 'bad' : ''}`} role="status">
          {toast.error ? <CircleHelp size={18} /> : <Check size={18} />}
          <span>{toast.message}</span>
          <button
            className="icon-button"
            onClick={() => setToast(undefined)}
            aria-label="Dismiss notification"
          >
            <X size={16} />
          </button>
        </div>
      )}
      {importing && (
        <ImportBot
          projects={projects || []}
          projectId={projectId}
          agents={agents || []}
          providers={providers || []}
          queues={queues || []}
          notice={notice}
          close={() => setImporting(false)}
          done={async (b) => {
            await refreshBots();
            await refreshProjects();
            if (b.project_id) setProjectId(b.project_id);
            setBotId(b.id);
            setPage('builder');
            setImporting(false);
          }}
        />
      )}
      {creating && (
        <Modal title="Create an intent / flow" close={() => setCreating(false)}>
          <p className="muted">
            Start with a welcome message and a human handoff. Make it your own in Flow studio.
          </p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              try {
                const b = await post<Bot>('/bots', {
                  name: f.get('name'),
                  project_id: projectId || null,
                  description: f.get('description') || '',
                  purpose: f.get('purpose') || '',
                  origins: String(f.get('origins') || '')
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean),
                });
                await refreshBots();
                await refreshProjects();
                if (b.project_id) setProjectId(b.project_id);
                setBotId(b.id);
                setPage('builder');
                setCreating(false);
                notice('Intent created in the selected project');
              } catch (err) {
                notice((err as Error).message, true);
              }
            }}
          >
            <Field label="Intent / flow name">
              <input
                name="name"
                placeholder="Customer support"
                required
                maxLength={120}
                autoFocus
              />
            </Field>
            <Field label="Intent description">
              <textarea
                name="description"
                rows={2}
                maxLength={5000}
                placeholder="Describe what this flow does"
              />
            </Field>
            <Field label="Intent purpose">
              <textarea
                name="purpose"
                rows={2}
                maxLength={5000}
                placeholder="When should the orchestrator start it?"
              />
            </Field>
            <Field
              label="Allowed website origins"
              hint="Exact origins, separated by commas. You can add these later."
            >
              <input name="origins" placeholder="https://example.com" />
            </Field>
            <button className="primary wide">
              <Plus size={16} />
              Create intent
            </button>
          </form>
        </Modal>
      )}
    </div>
  );
}

type CanvasData = { kind: string; config: Record<string, unknown>; entry: boolean };
type CanvasNode = Node<CanvasData, 'workflow'>;
function outputBranches(kind: string) {
  if (kind === 'condition') return ['true', 'false'];
  if (['end', 'handoff'].includes(kind)) return [];
  return ['ai', 'agent', 'knowledge', 'tool'].includes(kind) ? ['next', 'error'] : ['next'];
}
function WorkflowNode({ data, selected }: NodeProps<CanvasNode>) {
  const Icon = icons[data.kind as keyof typeof icons] || Code2;
  const branches = outputBranches(data.kind);
  const preview = String(
    data.config.text ||
      data.config.instructions ||
      data.config.variable ||
      data.config.query ||
      (['ai', 'tool'].includes(data.kind)
        ? 'Configure connection'
        : data.kind === 'handoff'
          ? 'Transfer to your team'
          : data.kind === 'end'
            ? 'Close this conversation'
            : 'Configure this step'),
  );
  return (
    <div className={`flow-node ${selected ? 'selected' : ''} kind-${data.kind}`}>
      <Handle type="target" position={Position.Left} />
      <div className="flow-node-title">
        <span className="node-icon">
          <Icon size={16} />
        </span>
        <strong>{labels[data.kind]}</strong>
        {data.entry && <span className="entry-tag">START</span>}
      </div>
      <div className="flow-node-body">{preview.slice(0, 100)}</div>
      {branches.map((b, i) => (
        <Handle
          key={b}
          id={b}
          type="source"
          position={Position.Right}
          style={{
            top: branches.length > 1 ? `${60 + i * 26}%` : '65%',
            background: b === 'error' ? '#b76757' : '#407d70',
          }}
        />
      ))}
    </div>
  );
}
const nodeTypes = { workflow: WorkflowNode };
function Builder({
  bot,
  bots,
  selectBot,
  providers,
  queues,
  refresh,
  notice,
  create,
  importFlow,
}: {
  bot: Bot;
  bots: Bot[];
  selectBot: (id: string) => void;
  providers: Provider[];
  queues: Queue[];
  refresh: () => Promise<unknown>;
  notice: Notice;
  create: () => void;
  importFlow: () => void;
}) {
  const [measured, setMeasured] = useState<Record<string, { width: number; height: number }>>({});
  const [flow, setFlow] = useState<Flow>(bot.draft);
  const [selected, setSelected] = useState(flow.entry);
  const [dirty, setDirty] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [chat, setChat] = useState<{ conversation_id: string; token: string }>();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tools] = useLoad<Tool[]>(() => api('/tools'), [], notice);
  const [cols] = useLoad<Collection[]>(() => api('/collections'), [], notice);
  const [fullAgents] = useLoad<FullAgent[]>(
    () => api('/agents?project_id=' + bot.project_id),
    [bot.project_id],
    notice,
  );
  const node = flow.nodes.find((n) => n.id === selected);
  function update(next: Flow) {
    setFlow(next);
    setDirty(true);
  }
  async function save() {
    const result = await put<{ errors: string[] }>(`/bots/${bot.id}/draft`, { flow });
    setDirty(false);
    setErrors(result.errors);
    await refresh();
    return result.errors;
  }
  async function action(kind: 'save' | 'publish' | 'test') {
    setBusy(true);
    try {
      const errs = await save();
      if (kind === 'save') {
        notice(
          errs.length ? 'Draft saved; resolve validation issues before publishing' : 'Draft saved',
        );
        return;
      }
      if (errs.length) throw new Error(errs.join('; '));
      if (kind === 'publish') {
        await post(`/bots/${bot.id}/publish`);
        await refresh();
        notice('New workflow version published');
      } else {
        setChat(await post(`/bots/${bot.id}/test`));
      }
    } catch (e) {
      notice((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  }
  const canvasNodes: CanvasNode[] = flow.nodes.map((n) => ({
    id: n.id,
    type: 'workflow',
    position: n.position,
    measured: measured[n.id],
    data: { kind: n.type, config: n.config, entry: n.id === flow.entry },
    selected: n.id === selected,
  }));
  const onNodesChange = (changes: NodeChange<CanvasNode>[]) => {
    for (const c of changes) {
      if (c.type === 'dimensions' && c.dimensions) {
        const d = c.dimensions;
        setMeasured((old) =>
          old[c.id]?.width === d.width && old[c.id]?.height === d.height
            ? old
            : { ...old, [c.id]: d },
        );
      }
    }
    const updated = applyNodeChanges(changes, canvasNodes);
    if (changes.some((c) => c.type === 'position' || c.type === 'remove'))
      update({
        ...flow,
        nodes: flow.nodes
          .filter((n) => updated.some((u) => u.id === n.id))
          .map((n) => ({ ...n, position: updated.find((u) => u.id === n.id)!.position })),
        edges: flow.edges.filter(
          (e) => updated.some((n) => n.id === e.source) && updated.some((n) => n.id === e.target),
        ),
      });
  };
  function connect(c: Connection) {
    if (!c.source || !c.target) return;
    const source = flow.nodes.find((node) => node.id === c.source);
    const label = c.sourceHandle || 'next';
    if (!source || !outputBranches(source.type).includes(label)) return;
    if (!flow.nodes.some((node) => node.id === c.target)) return;
    update({
      ...flow,
      edges: [
        ...flow.edges.filter((e) => e.source !== c.source || e.label !== label),
        { id: crypto.randomUUID(), source: c.source, target: c.target, label },
      ],
    });
  }
  function add(kind: string) {
    const id = crypto.randomUUID();
    const configs: Record<string, Record<string, unknown>> = {
      message: { text: 'How can we help?' },
      input: { variable: 'question' },
      condition: { variable: 'question', equals: 'agent' },
      variable: { variable: 'value', value: '' },
      ai: {
        instructions: 'Help the customer using the available knowledge.',
        provider_id: providers.find((p) => p.purpose === 'generation')?.id || '',
        max_iterations: 4,
        collection_ids: [],
        tool_ids: [],
      },
      agent: { agent_id: fullAgents?.find((a) => a.published_id)?.id || '' },
      tool: { tool_id: tools?.[0]?.id || '', arguments: {}, variable: 'tool_result' },
      knowledge: { collection_ids: [], query: '${question}', variable: 'knowledge' },
      handoff: { queue_id: queues[0]?.id },
      end: {},
    };
    update({
      ...flow,
      nodes: [
        ...flow.nodes,
        {
          id,
          type: kind,
          config: configs[kind],
          position: {
            x: 100 + (flow.nodes.length % 3) * 280,
            y: 240 + Math.floor(flow.nodes.length / 3) * 170,
          },
        },
      ],
    });
    setSelected(id);
  }
  function cfg(key: string, value: unknown) {
    if (node)
      update({
        ...flow,
        nodes: flow.nodes.map((n) =>
          n.id === node.id ? { ...n, config: { ...n.config, [key]: value } } : n,
        ),
      });
  }
  return (
    <div className="studio">
      <div className="studio-toolbar">
        <div className="studio-title">
          <span className="bot-icon small-icon">
            <BotIcon size={19} />
          </span>
          <div>
            <select
              aria-label="Selected intent"
              value={bot.id}
              onChange={(e) => {
                if (dirty && !confirm('Discard unsaved changes?')) return;
                selectBot(e.target.value);
              }}
            >
              {bots.map((b) => (
                <option value={b.id} key={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
            <span className="small muted">
              {dirty
                ? 'Unsaved changes'
                : bot.published_id
                  ? 'Published · editing draft'
                  : 'Draft workflow'}
            </span>
          </div>
          <button className="icon-button" onClick={create} aria-label="New intent">
            <Plus size={16} />
          </button>
        </div>
        <div className="toolbar-actions">
          <button className="secondary compact" onClick={importFlow}>
            <Upload size={15} /> Import flow
          </button>
          <button className="secondary compact" onClick={() => setSettingsOpen(true)}>
            <Settings size={15} />
            Settings
          </button>
          <button className="secondary compact" disabled={busy} onClick={() => action('save')}>
            <Save size={15} />
            Save
          </button>
          <button className="secondary compact" disabled={busy} onClick={() => action('test')}>
            <MessageCircle size={15} />
            Test chat
          </button>
          <button className="primary compact" disabled={busy} onClick={() => action('publish')}>
            <Rocket size={15} />
            Publish
          </button>
        </div>
      </div>
      {errors.length > 0 && (
        <div className="validation-bar" role="alert">
          <CircleHelp size={16} />
          <details>
            <summary>{errors.length} issues to resolve before publishing</summary>
            {errors.map((e, i) => (
              <div key={i}>{e}</div>
            ))}
          </details>
        </div>
      )}
      <div className="studio-layout">
        <aside className="node-palette">
          <div className="nav-label">BUILDING BLOCKS</div>
          <p>
            Choose a step.
            <br />
            Connect the conversation.
          </p>
          {Object.entries(labels).map(([kind, label]) => {
            const Icon = icons[kind as keyof typeof icons];
            return (
              <button key={kind} onClick={() => add(kind)}>
                <span className={`palette-icon kind-${kind}`}>
                  <Icon size={17} />
                </span>
                <span>{label}</span>
                <Plus size={13} />
              </button>
            );
          })}
          <div className="palette-tip">
            <GitBranch size={18} />
            <p>Drag from a step’s output to another step’s input. Connect error branches too.</p>
          </div>
        </aside>
        <div className="canvas">
          <div className="canvas-label">
            <Workflow size={15} />
            Conversation flow <span>Draft</span>
          </div>
          <ReactFlow
            nodes={canvasNodes}
            edges={flow.edges.map((e) => ({
              id: e.id,
              source: e.source,
              target: e.target,
              sourceHandle: e.label,
              type: 'smoothstep',
              style: { stroke: e.label === 'error' ? '#c99b90' : '#8aa89e', strokeWidth: 1.5 },
            }))}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onNodeClick={(_, n) => setSelected(n.id)}
            onConnect={connect}
            onEdgesDelete={(edges) =>
              update({
                ...flow,
                edges: flow.edges.filter((e) => !edges.some((x) => x.id === e.id)),
              })
            }
            fitView
            fitViewOptions={{ padding: 0.3 }}
            minZoom={0.25}
            maxZoom={1.6}
            deleteKeyCode={['Backspace', 'Delete']}
          >
            <Background color="#cbd5cf" gap={22} size={1} />
            <Controls showInteractive={false} />
            <MiniMap nodeColor="#b8d2c5" maskColor="rgba(246,248,245,.65)" />
          </ReactFlow>
        </div>
        <aside className="inspector">
          <div className="inspector-head">
            <span>STEP SETTINGS</span>
            <MoreHorizontal size={17} />
          </div>
          {node ? (
            <>
              <div className="inspector-title">
                <h3>{labels[node.type]}</h3>
                <span className="muted small">{node.id.slice(0, 16)}</span>
              </div>
              <Field label="Entry step">
                <select
                  value={flow.entry}
                  onChange={(e) => update({ ...flow, entry: e.target.value })}
                >
                  {flow.nodes.map((n) => (
                    <option key={n.id} value={n.id}>
                      {labels[n.type]} · {n.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </Field>
              {node.type === 'message' && (
                <Field label="Message" hint="Use ${question} to insert a variable.">
                  <textarea
                    value={String(node.config.text || '')}
                    onChange={(e) => cfg('text', e.target.value)}
                    rows={5}
                  />
                </Field>
              )}
              {['input', 'variable', 'condition', 'tool', 'knowledge', 'ai'].includes(
                node.type,
              ) && (
                <Field
                  label={node.type === 'condition' ? 'Variable to compare' : 'Output variable'}
                >
                  <input
                    value={String(node.config.variable || '')}
                    onChange={(e) => cfg('variable', e.target.value)}
                    placeholder={node.type === 'input' ? 'question' : 'answer'}
                  />
                </Field>
              )}
              {['variable', 'condition'].includes(node.type) && (
                <Field label={node.type === 'condition' ? 'Equals' : 'Value'}>
                  <input
                    value={String(
                      node.config[node.type === 'condition' ? 'equals' : 'value'] || '',
                    )}
                    onChange={(e) =>
                      cfg(node.type === 'condition' ? 'equals' : 'value', e.target.value)
                    }
                  />
                </Field>
              )}
              {node.type === 'agent' && (
                <Field
                  label="Published full agent"
                  hint="Build and publish reusable agents in Agent builder. Publishing this flow pins the selected agent version."
                >
                  <select
                    value={String(node.config.agent_id || '')}
                    onChange={(e) => cfg('agent_id', e.target.value)}
                  >
                    <option value="">Select a published agent</option>
                    {fullAgents
                      ?.filter((a) => a.published_id)
                      .map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                  </select>
                </Field>
              )}
              {node.type === 'ai' && (
                <>
                  <Field label="Model connection">
                    <select
                      value={String(node.config.provider_id || '')}
                      onChange={(e) => cfg('provider_id', e.target.value)}
                    >
                      <option value="">Select a model</option>
                      {providers
                        .filter((p) => p.purpose === 'generation')
                        .map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name} · {p.model}
                          </option>
                        ))}
                    </select>
                  </Field>
                  <Field label="Instructions">
                    <textarea
                      rows={6}
                      value={String(node.config.instructions || '')}
                      onChange={(e) => cfg('instructions', e.target.value)}
                    />
                  </Field>
                  <Field label="Maximum model iterations">
                    <input
                      type="number"
                      min={1}
                      max={8}
                      value={Number(node.config.max_iterations || 4)}
                      onChange={(e) => cfg('max_iterations', Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Allowed tools">
                    <select
                      multiple
                      value={(node.config.tool_ids || []) as string[]}
                      onChange={(e) =>
                        cfg(
                          'tool_ids',
                          Array.from(e.target.selectedOptions, (o) => o.value),
                        )
                      }
                    >
                      {tools?.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                </>
              )}
              {['ai', 'knowledge'].includes(node.type) && (
                <>
                  <Field
                    label="Knowledge collections"
                    hint="Only collections belonging to this intent are available."
                  >
                    <select
                      multiple
                      value={(node.config.collection_ids || []) as string[]}
                      onChange={(e) =>
                        cfg(
                          'collection_ids',
                          Array.from(e.target.selectedOptions, (o) => o.value),
                        )
                      }
                    >
                      {cols
                        ?.filter((c) => c.bot_id === bot.id)
                        .map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                    </select>
                  </Field>
                  <Field label="Search query">
                    <input
                      value={String(node.config.query || '${question}')}
                      onChange={(e) => cfg('query', e.target.value)}
                    />
                  </Field>
                </>
              )}
              {node.type === 'tool' && (
                <>
                  <Field label="HTTP tool">
                    <select
                      value={String(node.config.tool_id || '')}
                      onChange={(e) => cfg('tool_id', e.target.value)}
                    >
                      <option value="">Select a tool</option>
                      {tools?.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <JsonField
                    label="Arguments"
                    value={node.config.arguments || {}}
                    change={(v) => cfg('arguments', v)}
                  />
                </>
              )}
              {node.type === 'handoff' && (
                <Field label="Agent queue">
                  <select
                    value={String(node.config.queue_id || '')}
                    onChange={(e) => cfg('queue_id', e.target.value)}
                  >
                    <option value="">Unassigned queue</option>
                    {queues.map((q) => (
                      <option key={q.id} value={q.id}>
                        {q.name}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
              {node.type === 'end' && (
                <p className="muted">
                  Closes the conversation. Closure is recorded separately from evidence of
                  resolution.
                </p>
              )}
              <details className="advanced">
                <summary>Advanced configuration</summary>
                <JsonField
                  key={node.id}
                  label="Step configuration (JSON)"
                  value={node.config}
                  change={(v) =>
                    update({
                      ...flow,
                      nodes: flow.nodes.map((n) =>
                        n.id === node.id ? { ...n, config: v as Record<string, unknown> } : n,
                      ),
                    })
                  }
                />
              </details>
              <button
                className="danger text-button"
                onClick={() => {
                  update({
                    ...flow,
                    nodes: flow.nodes.filter((n) => n.id !== node.id),
                    edges: flow.edges.filter((e) => e.source !== node.id && e.target !== node.id),
                  });
                  setSelected('');
                }}
              >
                <Trash2 size={15} />
                Delete step
              </button>
            </>
          ) : (
            <p className="muted">Select a step to configure it.</p>
          )}
        </aside>
      </div>
      {chat && (
        <div className="test-drawer">
          <div className="section-head">
            <div>
              <h3>Test your conversation</h3>
              <small className="muted">Immutable snapshot of this draft</small>
            </div>
            <button
              className="icon-button"
              aria-label="Close test chat"
              onClick={() => setChat(undefined)}
            >
              <X size={18} />
            </button>
          </div>
          <Chat conversationId={chat.conversation_id} token={chat.token} notice={notice} />
          <TracePanel cid={chat.conversation_id} notice={notice} />
        </div>
      )}
      {settingsOpen && (
        <Modal title="Intent settings & installation" close={() => setSettingsOpen(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              try {
                await put(`/bots/${bot.id}`, {
                  name: f.get('name'),
                  project_id: bot.project_id,
                  description: f.get('description'),
                  purpose: f.get('purpose'),
                  origins: String(f.get('origins'))
                    .split(',')
                    .map((x) => x.trim())
                    .filter(Boolean),
                });
                await refresh();
                notice(
                  'Intent settings saved; republish the project to update routing descriptions.',
                );
              } catch (err) {
                notice((err as Error).message, true);
              }
            }}
          >
            <Field label="Intent / flow name">
              <input name="name" defaultValue={bot.name} required />
            </Field>
            <Field label="Intent description">
              <textarea
                name="description"
                defaultValue={bot.description}
                maxLength={5000}
                rows={3}
              />
            </Field>
            <Field
              label="Intent purpose"
              hint="The project orchestrator uses this to decide when to start the flow."
            >
              <textarea name="purpose" defaultValue={bot.purpose} maxLength={5000} rows={3} />
            </Field>
            <Field
              label="Allowed website origins"
              hint="Exact origins, separated by commas; no wildcards."
            >
              <input name="origins" defaultValue={bot.origins.join(', ')} />
            </Field>
            <button className="primary">Save settings</button>
          </form>
          <h3>Direct flow widget</h3>
          <p className="muted">
            For project routing, use the widget in Projects. This snippet starts this intent
            directly.
          </p>
          <pre className="code-block">{`<script src="${location.origin}/widget/open-ccai.js"\n  data-api="${location.origin}"\n  data-bot="${bot.id}" defer></script>`}</pre>
          <button
            className="secondary"
            onClick={() =>
              api(`/bots/${bot.id}/export`)
                .then((v) => download(`${bot.name}.json`, v))
                .catch((e) => notice(e.message, true))
            }
          >
            <ArrowDownToLine size={16} />
            Export bot
          </button>
        </Modal>
      )}
    </div>
  );
}
function Knowledge({
  bots,
  providers,
  notice,
}: {
  bots: Bot[];
  providers: Provider[];
  notice: Notice;
}) {
  const [cols, reload] = useLoad<Collection[]>(() => api('/collections'), [], notice);
  const [selected, setSelected] = useState('');
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const col = cols?.find((c) => c.id === selected);
  useEffect(() => {
    if (cols?.length && !cols.some((c) => c.id === selected)) setSelected(cols[0].id);
  }, [cols, selected]);
  const [docs, reloadDocs] = useLoad<
    { id: string; name: string; status: string; error: string | null; created: number }[]
  >(
    () => (selected ? api(`/collections/${selected}/documents`) : Promise.resolve([])),
    [selected],
    notice,
    4000,
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">GROUNDED IN YOUR KNOWLEDGE</span>
          <h1>A source of better answers.</h1>
          <p>Give your bots the context they need, with references you can trace.</p>
        </div>
        <button
          className="primary"
          disabled={!bots.length || !providers.some((p) => p.purpose === 'embedding')}
          onClick={() => setCreating(true)}
        >
          <Plus size={16} />
          New collection
        </button>
      </div>
      {!providers.some((p) => p.purpose === 'embedding') && (
        <div className="info-bar">
          <CircleHelp size={17} />
          Add an embedding model in Connections before creating a collection.
        </div>
      )}
      <div className="knowledge-layout">
        <section className="panel collection-list">
          <div className="section-head">
            <h2>
              Collections <span className="count">{cols?.length || 0}</span>
            </h2>
          </div>
          {cols?.map((c) => (
            <button
              key={c.id}
              className={selected === c.id ? 'selected' : ''}
              onClick={() => setSelected(c.id)}
            >
              <BookOpen size={19} />
              <div>
                <strong>{c.name}</strong>
                <small>{bots.find((b) => b.id === c.bot_id)?.name || 'Bot collection'}</small>
              </div>
              <ArrowRight size={15} />
            </button>
          ))}
          {!cols?.length && <p className="muted pad">Collections belong to a specific bot.</p>}
        </section>
        <section className="panel documents-panel">
          {col ? (
            <>
              <div className="section-head">
                <div>
                  <h2>{col.name}</h2>
                  <p>
                    {providers.find((p) => p.id === col.provider_id)?.name} · Index generation{' '}
                    {col.generation}
                  </p>
                </div>
                <label className={`secondary upload-button ${uploading ? 'disabled' : ''}`}>
                  <Plus size={16} />
                  {uploading ? 'Uploading…' : 'Upload document'}
                  <input
                    type="file"
                    accept=".pdf,.md,.txt"
                    disabled={uploading}
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      setUploading(true);
                      try {
                        const form = new FormData();
                        form.append('file', file);
                        await api(`/collections/${col.id}/documents`, {
                          method: 'POST',
                          body: form,
                        });
                        await reloadDocs();
                        notice('Document queued for indexing');
                      } catch (err) {
                        notice((err as Error).message, true);
                      } finally {
                        setUploading(false);
                        e.target.value = '';
                      }
                    }}
                  />
                </label>
              </div>
              {!docs?.length ? (
                <Empty
                  icon={BookOpen}
                  title="Put your knowledge to work"
                  text="Upload a text-based PDF, Markdown, or text file. Up to 10 MB per document."
                />
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th>Status</th>
                      <th>Uploaded</th>
                      <th>
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {docs?.map((d) => (
                      <tr key={d.id}>
                        <td>
                          <div className="document-name">
                            <BookOpen size={18} />
                            <div>
                              <strong>{d.name}</strong>
                              {d.error && <small className="danger">{d.error}</small>}
                            </div>
                          </div>
                        </td>
                        <td>
                          <Badge
                            tone={
                              d.status === 'ready' ? 'green' : d.status === 'error' ? 'red' : ''
                            }
                          >
                            {human(d.status)}
                          </Badge>
                        </td>
                        <td className="muted">{ago(d.created)}</td>
                        <td>
                          <button
                            className="icon-button danger"
                            aria-label={`Delete ${d.name}`}
                            onClick={async () => {
                              if (!confirm(`Delete ${d.name} and its indexed content?`)) return;
                              try {
                                await api(`/documents/${d.id}`, { method: 'DELETE' });
                                await reloadDocs();
                              } catch (e) {
                                notice((e as Error).message, true);
                              }
                            }}
                          >
                            <Trash2 size={16} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className="panel-footer">
                <span className="muted small">
                  Changing embedding models rebuilds this collection’s index.
                </span>
                <select
                  aria-label="Embedding model for reindex"
                  value={col.provider_id}
                  onChange={async (e) => {
                    if (!confirm('Reindex all documents with this embedding model?')) return;
                    try {
                      await post(`/collections/${col.id}/reindex`, { provider_id: e.target.value });
                      await reload();
                      await reloadDocs();
                      notice('Reindex queued');
                    } catch (err) {
                      notice((err as Error).message, true);
                    }
                  }}
                >
                  {providers
                    .filter((p) => p.purpose === 'embedding')
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                </select>
                <button
                  className="text-button"
                  onClick={() =>
                    post(`/collections/${col.id}/reindex`, {})
                      .then(() => {
                        reload();
                        reloadDocs();
                        notice('Reindex queued');
                      })
                      .catch((e) => notice(e.message, true))
                  }
                >
                  Reindex
                </button>
              </div>
            </>
          ) : (
            <Empty
              title="Your knowledge, organized"
              text="Create a collection for a bot, then upload its source documents."
            />
          )}
        </section>
      </div>
      {creating && (
        <Modal title="Create knowledge collection" close={() => setCreating(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const c = await post<{ id: string }>(
                  '/collections',
                  Object.fromEntries(new FormData(e.currentTarget)),
                );
                await reload();
                setSelected(c.id);
                setCreating(false);
                notice('Collection created');
              } catch (err) {
                notice((err as Error).message, true);
              }
            }}
          >
            <Field label="Collection name">
              <input name="name" required placeholder="Support knowledge" />
            </Field>
            <Field label="Bot">
              <select name="bot_id">
                {bots.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Embedding model">
              <select name="provider_id">
                {providers
                  .filter((p) => p.purpose === 'embedding')
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
              </select>
            </Field>
            <button className="primary wide">Create collection</button>
          </form>
        </Modal>
      )}
    </>
  );
}

function AgentInbox({
  user,
  updateUser,
  queues,
  notice,
}: {
  user: User;
  updateUser: (u: User) => void;
  queues: Queue[];
  notice: Notice;
}) {
  const [conversations, reload] = useLoad<Conversation[]>(
    () => api('/conversations'),
    [],
    notice,
    4000,
  );
  const [selected, setSelected] = useState('');
  const [filter, setFilter] = useState('queued');
  const [queue, setQueue] = useState('');
  const [reply, setReply] = useState('');
  const [note, setNote] = useState(false);
  const [busy, setBusy] = useState(false);
  const [metrics] = useLoad<Record<string, unknown>>(() => api('/monitoring'), [], notice, 8000);
  const [detail, refreshDetail] = useLoad<Conversation | undefined>(
    () => (selected ? api<Conversation>(`/conversations/${selected}`) : Promise.resolve(undefined)),
    [selected],
    selected ? notice : undefined,
    selected ? 2000 : 0,
  );
  const [attempts] = useLoad<
    { id: string; tool_id: string; status: string; invocation_key: string }[]
  >(
    () => (selected ? api(`/conversations/${selected}/invocations`) : Promise.resolve([])),
    [selected],
    notice,
    selected ? 5000 : 0,
  );
  const filtered = conversations?.filter(
    (c) =>
      (filter === 'all' || (filter === 'mine' && c.agent_id === user.id) || c.status === filter) &&
      (!queue || c.queue_id === queue),
  );
  const active = detail?.id === selected ? detail : undefined;
  const pending = useRef<{ content: string; client_id: string; note: boolean } | undefined>(
    undefined,
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">THE HUMAN SIDE OF AUTOMATION</span>
          <h1>Make the connection.</h1>
          <p>Pick up where your bot left off, with the whole conversation in view.</p>
        </div>
        <button
          className={user.available ? 'availability available' : 'availability'}
          onClick={() =>
            post<User>('/users/availability', { available: !user.available })
              .then(updateUser)
              .catch((e) => notice(e.message, true))
          }
        >
          <span className="tiny-dot" />
          {user.available ? 'Available' : 'Away'}
          <ChevronDown size={15} />
        </button>
      </div>
      <div className="inbox-metrics">
        <span>
          <strong>{String(metrics?.queue_depth ?? 0)}</strong> waiting
        </span>
        <span>
          <strong>{Math.floor(Number(metrics?.longest_wait_seconds || 0) / 60)}m</strong> longest
          wait
        </span>
        <span>
          <strong>{String(metrics?.handoffs ?? 0)}</strong> total handoffs
        </span>
        <span>
          <strong>{String(metrics?.execution_errors ?? 0)}</strong> execution errors
        </span>
        <span>
          <strong>
            {Number(metrics?.input_tokens || 0) + Number(metrics?.output_tokens || 0)}
          </strong>{' '}
          tokens
        </span>
        <span>
          <strong>
            {metrics?.average_model_latency_ms == null
              ? '—'
              : Math.round(Number(metrics.average_model_latency_ms)) + 'ms'}
          </strong>{' '}
          model latency
        </span>
        {metrics?.estimated_cost != null && (
          <span>
            <strong>{Number(metrics.estimated_cost).toFixed(4)}</strong> estimated cost
          </span>
        )}
        <span className="muted small">Generation usage: latest 1,000 traces</span>
      </div>
      <section className="inbox-layout panel">
        <div className="conversation-list">
          <div className="inbox-filters">
            <select
              aria-label="Conversation filter"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="queued">Waiting</option>
              <option value="mine">Assigned to me</option>
              <option value="bot">With bot</option>
              <option value="closed">Closed</option>
              <option value="error">Errors</option>
              <option value="all">All conversations</option>
            </select>
            <select
              aria-label="Queue filter"
              value={queue}
              onChange={(e) => setQueue(e.target.value)}
            >
              <option value="">All queues</option>
              {queues.map((q) => (
                <option key={q.id} value={q.id}>
                  {q.name}
                </option>
              ))}
            </select>
          </div>
          {filtered?.map((c) => (
            <button
              key={c.id}
              className={selected === c.id ? 'conversation selected' : 'conversation'}
              onClick={() => setSelected(c.id)}
            >
              <div className="avatar customer-avatar">
                <MessageCircle size={18} />
              </div>
              <div>
                <strong>Visitor {c.id.slice(0, 6)}</strong>
                <small>
                  {queues.find((q) => q.id === c.queue_id)?.name || 'Unassigned'} ·{' '}
                  {human(c.status)}
                </small>
              </div>
              <time>{ago(c.queued_at || c.created)}</time>
            </button>
          ))}
          {!filtered?.length && (
            <Empty
              icon={Inbox}
              title="All clear here"
              text="Conversations matching this view will appear here."
            />
          )}
        </div>
        <div className="agent-conversation">
          {active ? (
            <>
              <div className="section-head">
                <div>
                  <h3>Visitor {active.id.slice(0, 6)}</h3>
                  <Badge tone={active.status === 'agent' ? 'green' : ''}>
                    {human(active.status)}
                  </Badge>
                </div>
                <div className="toolbar-actions">
                  {active.status === 'queued' && (
                    <button
                      className="primary compact"
                      disabled={!user.available}
                      onClick={() =>
                        post(`/conversations/${selected}/claim`)
                          .then(() => {
                            refreshDetail();
                            reload();
                          })
                          .catch((e) => notice(e.message, true))
                      }
                    >
                      Claim conversation
                    </button>
                  )}
                  {active.status !== 'closed' &&
                    (active.agent_id === user.id ||
                      ['administrator', 'supervisor'].includes(user.role)) && (
                      <button
                        className="secondary compact"
                        onClick={() =>
                          post(`/conversations/${selected}/close`)
                            .then(() => {
                              refreshDetail();
                              reload();
                            })
                            .catch((e) => notice(e.message, true))
                        }
                      >
                        <Check size={15} />
                        Close
                      </button>
                    )}
                  <button
                    className="icon-button"
                    aria-label="Export conversation"
                    onClick={() =>
                      api(`/conversations/${selected}/export`)
                        .then((v) => download(`conversation-${selected}.json`, v))
                        .catch((e) => notice(e.message, true))
                    }
                  >
                    <ArrowDownToLine size={17} />
                  </button>
                </div>
              </div>
              <div className="agent-transcript">
                {active.messages?.map((m) => (
                  <div className={`bubble-wrap ${m.role}`} key={m.id}>
                    <small>
                      {m.role === 'customer'
                        ? 'Customer'
                        : m.role === 'bot'
                          ? 'Bot'
                          : m.role === 'note'
                            ? 'Internal note'
                            : 'Agent'}{' '}
                      ·{' '}
                      {new Date(m.created * 1000).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </small>
                    <div className="bubble">{m.content}</div>
                    {m.sources?.length > 0 && (
                      <small>Sources: {m.sources.map((s) => s.name).join(', ')}</small>
                    )}
                  </div>
                ))}
              </div>
              {attempts?.some((a) => a.status === 'uncertain') && (
                <div className="error-box">
                  An external action has an uncertain outcome. Check the external system before
                  repeating it.
                  {attempts
                    .filter((a) => a.status === 'uncertain')
                    .map((a) => (
                      <code key={a.id} className="block">
                        {a.invocation_key}
                      </code>
                    ))}
                </div>
              )}
              <div className="agent-compose">
                <div className="reply-tabs">
                  <button className={!note ? 'active' : ''} onClick={() => setNote(false)}>
                    Reply
                  </button>
                  <button className={note ? 'active' : ''} onClick={() => setNote(true)}>
                    Internal note
                  </button>
                </div>
                <form
                  onSubmit={async (e) => {
                    e.preventDefault();
                    if (!reply.trim() || busy) return;
                    setBusy(true);
                    if (
                      !pending.current ||
                      pending.current.content !== reply ||
                      pending.current.note !== note
                    )
                      pending.current = { content: reply, client_id: crypto.randomUUID(), note };
                    try {
                      await post(
                        `/conversations/${selected}/${note ? 'notes' : 'messages'}`,
                        pending.current,
                      );
                      setReply('');
                      pending.current = undefined;
                      await refreshDetail();
                    } catch (err) {
                      notice((err as Error).message, true);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <textarea
                    aria-label={note ? 'Internal note' : 'Agent reply'}
                    placeholder={
                      note
                        ? 'Only your team can see this note…'
                        : active.agent_id === user.id
                          ? 'Write your reply…'
                          : 'Claim this conversation to reply.'
                    }
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    disabled={!note && (active.status !== 'agent' || active.agent_id !== user.id)}
                    rows={3}
                    maxLength={16000}
                  />
                  <div>
                    <span className="muted small">
                      {note ? 'Visible to your team only' : 'Sent to the customer'}
                    </span>
                    <button
                      className="primary compact"
                      disabled={
                        busy ||
                        !reply.trim() ||
                        (!note && (active.status !== 'agent' || active.agent_id !== user.id))
                      }
                    >
                      <Send size={15} />
                      {note ? 'Add note' : 'Send reply'}
                    </button>
                  </div>
                </form>
              </div>
              <TracePanel cid={selected} notice={notice} />
            </>
          ) : (
            <Empty
              icon={Headphones}
              title="Ready when they need you"
              text="Select a conversation to see its history and connect with a customer."
            />
          )}
        </div>
      </section>
      <p className="muted small">
        Closed conversations are counted as closed, not automatically resolved. The conversation
        list shows the latest 200 conversations.
      </p>
    </>
  );
}

function Connections({
  providers,
  refresh,
  notice,
  admin,
  toolsOnly = false,
}: {
  providers: Provider[];
  refresh: () => Promise<unknown>;
  notice: Notice;
  admin: boolean;
  toolsOnly?: boolean;
}) {
  const [tab, setTab] = useState(toolsOnly ? 'tools' : 'models');
  const [adding, setAdding] = useState(false);
  const [tools, reloadTools] = useLoad<Tool[]>(() => api('/tools'), [], notice);
  const [kind, setKind] = useState('openai');
  const [purpose, setPurpose] = useState('generation');
  const [busy, setBusy] = useState(false);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">
            {toolsOnly ? 'SHARED COMPONENTS' : 'BRING YOUR OWN PROVIDERS'}
          </span>
          <h1>{toolsOnly ? 'One tool library. Every agent.' : 'Your models. Your choice.'}</h1>
          <p>
            {toolsOnly
              ? 'Register tools once and enable them for full agents, Mini agents, or flow steps.'
              : 'Connect model APIs and business tools. Keep your workflows portable.'}
          </p>
        </div>
        {admin && (
          <button className="primary" onClick={() => setAdding(true)}>
            <Plus size={16} />
            {tab === 'models' ? 'Connect model' : 'Register tool'}
          </button>
        )}
      </div>
      <div className={toolsOnly ? 'hidden' : 'page-tabs'}>
        <button className={tab === 'models' ? 'active' : ''} onClick={() => setTab('models')}>
          Model connections <span>{providers.length}</span>
        </button>
        <button className={tab === 'tools' ? 'active' : ''} onClick={() => setTab('tools')}>
          HTTP tools <span>{tools?.length || 0}</span>
        </button>
        {admin && (
          <button
            className={tab === 'credentials' ? 'active' : ''}
            onClick={() => setTab('credentials')}
          >
            Credentials
          </button>
        )}
      </div>
      {tab === 'models' ? (
        <section className="panel">
          {!providers.length ? (
            <Empty
              icon={Radio}
              title="Connect your first model"
              text="Use your organization's API key for OpenAI, Anthropic, Gemini, or a compatible endpoint."
            >
              {admin && (
                <button className="primary" onClick={() => setAdding(true)}>
                  <Plus size={16} />
                  Connect model
                </button>
              )}
            </Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Connection</th>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Purpose</th>
                  <th>Capabilities</th>
                </tr>
              </thead>
              <tbody>
                {providers.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <div className="document-name">
                        <span className="bot-icon small-icon">
                          <Radio size={17} />
                        </span>
                        <strong>{p.name}</strong>
                      </div>
                    </td>
                    <td>{human(p.kind)}</td>
                    <td>
                      <code>{p.model}</code>
                    </td>
                    <td>
                      <Badge>{human(p.purpose)}</Badge>
                    </td>
                    <td>
                      <div className="capabilities">
                        {Object.entries(p.capabilities)
                          .filter(([, v]) => v)
                          .map(([k]) => (
                            <Badge tone="green" key={k}>
                              {k}
                            </Badge>
                          ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : tab === 'tools' ? (
        <section className="panel">
          {!tools?.length ? (
            <Empty
              icon={Code2}
              title="Connect to the way you work"
              text="Register external HTTPS tools with defined inputs and outputs. Your code can run in any language."
            >
              {admin && (
                <button className="secondary" onClick={() => setAdding(true)}>
                  Register HTTP tool
                  <ArrowRight size={15} />
                </button>
              )}
            </Empty>
          ) : (
            <div className="bot-grid">
              {tools.map((t) => (
                <div className="tool-card" key={t.id}>
                  <Code2 size={22} />
                  <h3>{t.name}</h3>
                  <p>{t.description || 'External HTTP tool'}</p>
                  <Badge>Schema validated</Badge>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : (
        <Credentials notice={notice} />
      )}
      <div className="info-bar">
        <Shield size={17} />
        <span>
          {toolsOnly
            ? 'Register tools once, then enable them separately for each full agent, Mini agent, or flow step.'
            : 'API keys are encrypted on your server. Model usage is billed directly by your provider. Capability settings must match your selected model.'}
        </span>
      </div>
      {adding && (
        <Modal
          title={tab === 'models' ? 'Connect a model' : 'Register HTTP tool'}
          close={() => setAdding(false)}
        >
          {tab === 'models' ? (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                const f = new FormData(e.currentTarget);
                try {
                  const credential = await post<{ id: string }>('/credentials', {
                    name: f.get('name'),
                    secret: f.get('secret'),
                  });
                  await post('/providers', {
                    name: f.get('name'),
                    kind,
                    model: f.get('model'),
                    purpose,
                    credential_id: credential.id,
                    base_url: f.get('base_url') || null,
                    capabilities:
                      purpose === 'embedding'
                        ? { embeddings: true }
                        : {
                            streaming: f.get('streaming') === 'on',
                            tools: f.get('tools') === 'on',
                            structured: f.get('structured') === 'on',
                          },
                    pricing:
                      f.get('input_price') !== '' && f.get('output_price') !== ''
                        ? {
                            input_per_million: Number(f.get('input_price')),
                            output_per_million: Number(f.get('output_price')),
                          }
                        : {},
                  });
                  await refresh();
                  setAdding(false);
                  notice('Model connected');
                } catch (err) {
                  notice((err as Error).message, true);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <Field label="Connection name">
                <input name="name" placeholder="Support model" required />
              </Field>
              <div className="form-row">
                <Field label="Provider">
                  <select value={kind} onChange={(e) => setKind(e.target.value)}>
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="gemini">Gemini</option>
                    <option value="compatible">OpenAI-compatible</option>
                  </select>
                </Field>
                <Field label="Purpose">
                  <select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
                    <option value="generation">Generation</option>
                    <option value="embedding">Embedding</option>
                  </select>
                </Field>
              </div>
              <Field
                label="Model identifier"
                hint="Enter a model available to your provider account, without a provider prefix."
              >
                <input
                  name="model"
                  required
                  placeholder={
                    purpose === 'embedding' ? 'Embedding model ID' : 'Generation model ID'
                  }
                />
              </Field>
              <Field label="API key">
                <input name="secret" type="password" autoComplete="off" required />
              </Field>
              {kind === 'compatible' && (
                <Field
                  label="API base URL"
                  hint="The deployment's PROVIDER_ALLOWED_HOSTS must include this public HTTPS host."
                >
                  <input
                    name="base_url"
                    type="url"
                    required
                    placeholder="https://api.example.com/v1"
                  />
                </Field>
              )}
              {purpose === 'generation' && (
                <fieldset className="checks">
                  <legend>Model capabilities</legend>
                  <label>
                    <input name="streaming" type="checkbox" defaultChecked />
                    Streaming
                  </label>
                  <label>
                    <input
                      key={kind + 'tools'}
                      name="tools"
                      type="checkbox"
                      defaultChecked={kind !== 'compatible'}
                    />
                    Tool calling
                  </label>
                  <label>
                    <input
                      key={kind + 'structured'}
                      name="structured"
                      type="checkbox"
                      defaultChecked={kind === 'openai'}
                    />
                    Structured output
                  </label>
                </fieldset>
              )}
              <div className="form-row">
                <Field
                  label="Input cost / 1M tokens"
                  hint="Optional estimate, in your billing currency."
                >
                  <input name="input_price" type="number" min={0} step="any" />
                </Field>
                <Field label="Output cost / 1M tokens">
                  <input name="output_price" type="number" min={0} step="any" />
                </Field>
              </div>
              <button className="primary wide" disabled={busy}>
                {busy ? <Loader2 className="spin" size={16} /> : <KeyRound size={16} />}Connect
                model
              </button>
            </form>
          ) : (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                const f = new FormData(e.currentTarget);
                try {
                  let credential_id = null;
                  if (f.get('secret'))
                    credential_id = (
                      await post<{ id: string }>('/credentials', {
                        name: f.get('name'),
                        secret: f.get('secret'),
                      })
                    ).id;
                  await post('/tools', {
                    name: f.get('name'),
                    description: f.get('description'),
                    url: f.get('url'),
                    method: f.get('method'),
                    input_schema: JSON.parse(String(f.get('input_schema'))),
                    output_schema: JSON.parse(String(f.get('output_schema'))),
                    credential_id,
                    timeout: Number(f.get('timeout')),
                    safe_retry: f.get('safe_retry') === 'on',
                  });
                  await reloadTools();
                  setAdding(false);
                  notice('Tool registered');
                } catch (err) {
                  notice((err as Error).message, true);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <Field label="Tool name">
                <input
                  name="name"
                  required
                  pattern="[a-zA-Z_][a-zA-Z0-9_]{0,63}"
                  placeholder="lookup_order"
                />
              </Field>
              <Field label="Description">
                <input name="description" placeholder="Find an order by its reference" />
              </Field>
              <Field
                label="HTTPS endpoint"
                hint="Host must be in TOOL_ALLOWED_HOSTS. Private addresses and redirects are blocked."
              >
                <input
                  name="url"
                  type="url"
                  required
                  placeholder="https://tools.example.com/orders"
                />
              </Field>
              <div className="form-row">
                <Field label="Method">
                  <select name="method">
                    <option>POST</option>
                    <option>GET</option>
                  </select>
                </Field>
                <Field label="Timeout (seconds)">
                  <input name="timeout" type="number" min={1} max={30} defaultValue={15} />
                </Field>
              </div>
              <Field label="Bearer credential (optional)">
                <input name="secret" type="password" autoComplete="off" />
              </Field>
              <Field label="Input JSON Schema">
                <textarea
                  name="input_schema"
                  className="mono"
                  rows={4}
                  defaultValue={'{"type":"object","properties":{},"additionalProperties":false}'}
                  required
                />
              </Field>
              <Field label="Output JSON Schema">
                <textarea
                  name="output_schema"
                  className="mono"
                  rows={3}
                  defaultValue={'{"type":"object"}'}
                  required
                />
              </Field>
              <label className="check-label">
                <input name="safe_retry" type="checkbox" />
                Endpoint guarantees idempotency for the Idempotency-Key header
              </label>
              <button className="primary wide" disabled={busy}>
                Register tool
              </button>
            </form>
          )}
        </Modal>
      )}
    </>
  );
}
function Credentials({ notice }: { notice: Notice }) {
  const [rows, reload] = useLoad<{ id: string; name: string }[]>(
    () => api('/credentials'),
    [],
    notice,
  );
  const [selected, setSelected] = useState<{ id: string; name: string }>();
  return (
    <section className="panel">
      <div className="section-head">
        <div>
          <h2>Encrypted credentials</h2>
          <p>Rotate a key without changing its connection or workflows.</p>
        </div>
      </div>
      {rows?.map((r) => (
        <div className="credential-row" key={r.id}>
          <KeyRound size={18} />
          <strong>{r.name}</strong>
          <Badge>Encrypted</Badge>
          <button className="secondary compact" onClick={() => setSelected(r)}>
            Rotate key
          </button>
        </div>
      ))}
      {!rows?.length && (
        <Empty
          icon={KeyRound}
          title="No credentials yet"
          text="Connecting a model or authenticated tool creates an encrypted credential."
        />
      )}
      {selected && (
        <Modal title="Rotate credential" close={() => setSelected(undefined)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const f = new FormData(e.currentTarget);
                await put(`/credentials/${selected.id}`, {
                  name: selected.name,
                  secret: f.get('secret'),
                });
                await reload();
                setSelected(undefined);
                notice('Credential rotated');
              } catch (err) {
                notice((err as Error).message, true);
              }
            }}
          >
            <Field label={`New key for ${selected.name}`}>
              <input name="secret" type="password" autoComplete="off" required />
            </Field>
            <button className="primary wide">Save new key</button>
          </form>
        </Modal>
      )}
    </section>
  );
}

function Team({
  queues,
  refreshQueues,
  notice,
}: {
  queues: Queue[];
  refreshQueues: () => Promise<unknown>;
  notice: Notice;
}) {
  const [users] = useLoad<User[]>(() => api('/users'), [], notice, 10000);
  const [inviting, setInviting] = useState(false);
  const [invitation, setInvitation] = useState('');
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">BETTER TOGETHER</span>
          <h1>A place for your whole team.</h1>
          <p>Give people the access they need to build, support, and supervise.</p>
        </div>
        <button
          className="primary"
          onClick={() => {
            setInviting(true);
            setInvitation('');
          }}
        >
          <Plus size={16} />
          Invite teammate
        </button>
      </div>
      <section className="panel">
        <div className="section-head">
          <h2>
            Workspace members <span className="count">{users?.length || 0}</span>
          </h2>
        </div>
        <table>
          <thead>
            <tr>
              <th>Member</th>
              <th>Role</th>
              <th>Availability</th>
            </tr>
          </thead>
          <tbody>
            {users?.map((u) => (
              <tr key={u.id}>
                <td>
                  <div className="document-name">
                    <div className="avatar">{u.email[0].toUpperCase()}</div>
                    <strong>{u.email}</strong>
                  </div>
                </td>
                <td>
                  <Badge>{human(u.role)}</Badge>
                </td>
                <td>
                  <span className={u.available ? 'status-dot green-text' : 'status-dot muted'}>
                    <i />
                    {u.available ? 'Available' : 'Away'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="panel queues-panel">
        <div className="section-head">
          <div>
            <h2>Agent queues</h2>
            <p>
              Route handoffs to the right place. Agents can manually claim waiting conversations.
            </p>
          </div>
        </div>
        <div className="queue-tags">
          {queues.map((q) => (
            <Badge key={q.id}>
              <Headphones size={14} />
              {q.name}
            </Badge>
          ))}
        </div>
        <form
          className="inline-form"
          onSubmit={async (e) => {
            e.preventDefault();
            const form = e.currentTarget;
            try {
              await post('/queues', Object.fromEntries(new FormData(form)));
              await refreshQueues();
              form.reset();
              notice('Queue created');
            } catch (err) {
              notice((err as Error).message, true);
            }
          }}
        >
          <input
            name="name"
            required
            placeholder="New queue name"
            aria-label="New queue name"
            maxLength={120}
          />
          <button className="secondary">
            <Plus size={16} />
            Add queue
          </button>
        </form>
      </section>
      {inviting && (
        <Modal title="Invite a teammate" close={() => setInviting(false)}>
          {invitation ? (
            <>
              <div className="info-bar">
                <Check size={18} />
                Invitation created. Share this link with your teammate.
              </div>
              <Field
                label="Invitation link"
                hint="Valid for 24 hours and usable once. Anyone with this link can accept the specified role."
              >
                <textarea readOnly value={invitation} rows={4} />
              </Field>
              <button
                className="primary wide"
                onClick={() =>
                  navigator.clipboard
                    .writeText(invitation)
                    .then(() => notice('Invitation link copied'))
                    .catch(() => notice('Copy the link from the text field', true))
                }
              >
                Copy invitation link
              </button>
            </>
          ) : (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  const result = await post<{ token: string }>(
                    '/invitations',
                    Object.fromEntries(new FormData(e.currentTarget)),
                  );
                  setInvitation(
                    `${location.origin}/?invitation=${encodeURIComponent(result.token)}`,
                  );
                } catch (err) {
                  notice((err as Error).message, true);
                }
              }}
            >
              <Field label="Email">
                <input name="email" type="email" required />
              </Field>
              <Field label="Role">
                <select name="role">
                  <option value="agent">Agent — support customers</option>
                  <option value="builder">Builder — create bots and knowledge</option>
                  <option value="supervisor">Supervisor — monitor and manage conversations</option>
                  <option value="administrator">Administrator — manage the installation</option>
                </select>
              </Field>
              <button className="primary wide">Create invitation</button>
            </form>
          )}
        </Modal>
      )}
    </>
  );
}

type BotBundle = {
  agents?: { ref: string; name: string }[];
  schema_version: number;
  name: string;
  flow: Flow;
  providers: { ref: string; name: string; purpose: string }[];
  tools: { ref: string; name: string }[];
  queues: { ref: string; name: string }[];
  collections: { ref: string; name: string }[];
};
function ImportBot({
  projects,
  projectId,
  agents,
  providers,
  queues,
  notice,
  close,
  done,
}: {
  projects: Project[];
  projectId: string;
  agents: FullAgent[];
  providers: Provider[];
  queues: Queue[];
  notice: Notice;
  close: () => void;
  done: (b: Bot) => Promise<void>;
}) {
  const [targetProject, setTargetProject] = useState(projectId);
  const [bundle, setBundle] = useState<BotBundle>();
  const [busy, setBusy] = useState(false);
  const [tools] = useLoad<Tool[]>(() => api('/tools'), [], notice);
  return (
    <Modal title="Import a portable flow" close={close}>
      <p className="muted">
        Choose a version 1 export. Bind its connections explicitly; source documents must be
        uploaded again.
      </p>
      <Field label="Flow export file">
        <input
          type="file"
          accept=".json,application/json"
          onChange={async (e) => {
            try {
              const file = e.target.files?.[0];
              if (!file) return;
              if (file.size > 500000) throw new Error('Maximum bundle size is 500 KB');
              const value = JSON.parse(await file.text());
              if (
                value.schema_version !== 1 ||
                !value.flow ||
                !Array.isArray(value.providers) ||
                !Array.isArray(value.tools) ||
                !Array.isArray(value.queues) ||
                !Array.isArray(value.collections)
              )
                throw new Error('Select a valid version 1 bot export');
              setBundle(value);
            } catch (err) {
              setBundle(undefined);
              notice((err as Error).message, true);
            }
          }}
        />
      </Field>
      {bundle && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              const form = new FormData(e.currentTarget);
              const bindings = (prefix: string) =>
                Object.fromEntries(
                  Array.from(form.entries())
                    .filter(([k]) => k.startsWith(prefix + ':'))
                    .map(([k, v]) => [k.slice(prefix.length + 1), v]),
                );
              const result = await post<{ bot: Bot; requires_document_upload: boolean }>(
                '/bots/import',
                {
                  bundle,
                  project_id: targetProject || null,
                  agent_bindings: bindings('agent'),
                  provider_bindings: bindings('provider'),
                  tool_bindings: bindings('tool'),
                  queue_bindings: bindings('queue'),
                },
              );
              await done(result.bot);
              notice(
                result.requires_document_upload
                  ? 'Bot imported. Reupload its source documents before publishing.'
                  : 'Bot imported as an unpublished draft.',
              );
            } catch (err) {
              notice((err as Error).message, true);
            } finally {
              setBusy(false);
            }
          }}
        >
          <h3>{bundle.name}</h3>
          <Field label="Destination project">
            <select value={targetProject} onChange={(e) => setTargetProject(e.target.value)}>
              <option value="">Create a project from this flow</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>
          {(bundle.agents || []).map((a) => (
            <Field key={a.ref} label={`Bind full agent: ${a.name}`}>
              <select key={targetProject} name={'agent:' + a.ref} defaultValue="" required>
                <option value="" disabled>
                  Select a published agent in this project
                </option>
                {agents
                  .filter((x) => x.project_id === targetProject && x.published_id)
                  .map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name}
                    </option>
                  ))}
              </select>
            </Field>
          ))}
          {bundle.providers.map((p) => (
            <Field key={p.ref} label={`Bind ${p.name} (${p.purpose})`}>
              <select name={'provider:' + p.ref} defaultValue="" required>
                <option value="" disabled>
                  Choose a local connection
                </option>
                {providers
                  .filter((x) => x.purpose === p.purpose)
                  .map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name}
                    </option>
                  ))}
              </select>
            </Field>
          ))}
          {bundle.tools.map((t) => (
            <Field key={t.ref} label={`Bind tool: ${t.name}`}>
              <select name={'tool:' + t.ref} defaultValue="" required>
                <option value="" disabled>
                  Choose a local tool
                </option>
                {tools?.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
              </select>
            </Field>
          ))}
          {bundle.queues.map((q) => (
            <Field key={q.ref} label={`Bind queue: ${q.name}`}>
              <select name={'queue:' + q.ref} defaultValue="" required>
                <option value="" disabled>
                  Choose a local queue
                </option>
                {queues.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
              </select>
            </Field>
          ))}
          {bundle.collections.length > 0 && (
            <div className="info-bar">
              {bundle.collections.length} knowledge collections will be recreated empty.
            </div>
          )}
          <button className="primary wide" disabled={busy}>
            Import bot
          </button>
        </form>
      )}
    </Modal>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
