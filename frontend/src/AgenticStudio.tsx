import { useEffect, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
  applyNodeChanges,
  type NodeChange,
  type Connection,
  type NodeProps,
  type Node,
  type Edge,
} from '@xyflow/react';
import {
  Bot as BotIcon,
  ChevronLeft,
  GitBranch,
  Headphones,
  Layers,
  MessageCircle,
  MoreHorizontal,
  Plus,
  Radio,
  Rocket,
  Save,
  Shield,
  Trash2,
  Users,
  Workflow,
} from 'lucide-react';
import {
  api,
  post,
  type FullAgent,
  type Provider,
  type Queue,
  type TestSession,
  type Tool,
} from './api';
import { Badge, Empty, Field, JsonField, Modal, useLoad, type Notice } from './ui';
import { ConversationTest } from './conversation';

export type AgenticNodeKind =
  | 'router_agent'
  | 'supervisor_agent'
  | 'agent'
  | 'sub_agent'
  | 'critic_agent'
  | 'aggregator'
  | 'pubsub_topic'
  | 'human_handoff';

export type AgenticConnectionKind =
  | 'DELEGATE'
  | 'HAND-OFF'
  | 'FAN-OUT'
  | 'REFLECTION'
  | 'PUB/SUB'
  | 'FALLBACK';

export type AgenticFlowNode = {
  id: string;
  type: AgenticNodeKind;
  name: string;
  position: { x: number; y: number };
  config: Record<string, unknown>;
};

export type AgenticFlowEdge = {
  id: string;
  source: string;
  target: string;
  relation: AgenticConnectionKind;
  condition?: string;
  context_mode?: 'full' | 'summary' | 'structured';
};

export type AgenticWorkflow = {
  id: string;
  project_id: string;
  name: string;
  description: string;
  published: boolean;
  entry: string;
  nodes: AgenticFlowNode[];
  edges: AgenticFlowEdge[];
};

const NODE_LABELS: Record<AgenticNodeKind, string> = {
  router_agent: 'Router agent',
  supervisor_agent: 'Supervisor agent',
  agent: 'Agent',
  sub_agent: 'Sub-agent',
  critic_agent: 'Critic / reflection',
  aggregator: 'Fan-in aggregator',
  pubsub_topic: 'Pub/Sub topic',
  human_handoff: 'Human escalation',
};

const NODE_ICONS: Record<AgenticNodeKind, typeof Layers> = {
  router_agent: GitBranch,
  supervisor_agent: Users,
  agent: BotIcon,
  sub_agent: Workflow,
  critic_agent: Shield,
  aggregator: Layers,
  pubsub_topic: Radio,
  human_handoff: Headphones,
};

const CONNECTION_META: Record<
  AgenticConnectionKind,
  { color: string; bg: string; dash?: string; animated?: boolean; description: string }
> = {
  DELEGATE: {
    color: '#25634f',
    bg: '#e6f2ec',
    description: 'Synchronous task delegation; caller awaits child agent output.',
  },
  'HAND-OFF': {
    color: '#3b6ea8',
    bg: '#e8f0fa',
    description: 'Transfers full conversation ownership to the target agent.',
  },
  'FAN-OUT': {
    color: '#7658a8',
    bg: '#efeaf9',
    dash: '6 4',
    animated: true,
    description: 'Broadcasts task in parallel across multiple agents or sub-agents.',
  },
  REFLECTION: {
    color: '#b87d28',
    bg: '#fcf3e3',
    dash: '4 3',
    animated: true,
    description: 'Iterative critique and verification loop before final output.',
  },
  'PUB/SUB': {
    color: '#2b828c',
    bg: '#e5f5f7',
    dash: '5 4',
    animated: true,
    description: 'Asynchronous event publish/subscribe via topic channels.',
  },
  FALLBACK: {
    color: '#b55648',
    bg: '#faeae7',
    dash: '4 4',
    description: 'Triggered when the source agent encounters an error or low confidence.',
  },
};

const CONNECTION_KINDS = Object.keys(CONNECTION_META) as AgenticConnectionKind[];

type AgenticCanvasData = {
  kind: AgenticNodeKind;
  name: string;
  config: Record<string, unknown>;
  entry: boolean;
};
type AgenticCanvasNode = Node<AgenticCanvasData, 'agentic'>;

function AgenticNodeCard({ data, selected }: NodeProps<AgenticCanvasNode>) {
  const Icon = NODE_ICONS[data.kind] || BotIcon;
  const subtitle = String(
    data.config.instructions ||
      data.config.topic ||
      data.config.strategy ||
      (data.kind === 'router_agent'
        ? 'Classifies & routes across agents'
        : data.kind === 'supervisor_agent'
          ? 'Coordinates multi-agent workflow'
          : data.kind === 'sub_agent'
            ? 'Scoped worker sub-agent'
            : data.kind === 'critic_agent'
              ? 'Evaluates & critiques outputs'
              : data.kind === 'pubsub_topic'
                ? 'Event bus pub/sub channel'
                : data.kind === 'aggregator'
                  ? 'Synthesizes parallel fan-out outputs'
                  : 'Autonomous agent node'),
  );
  return (
    <div className={`flow-node agentic-node ${selected ? 'selected' : ''} kind-${data.kind}`}>
      <Handle type="target" position={Position.Top} />
      <div className="flow-node-title">
        <span className={`node-icon kind-${data.kind}`}>
          <Icon size={16} />
        </span>
        <div className="agentic-node-heading">
          <strong>{data.name || NODE_LABELS[data.kind]}</strong>
          <small>{NODE_LABELS[data.kind]}</small>
        </div>
        {data.entry && <span className="entry-tag">ENTRY</span>}
      </div>
      <div className="flow-node-body">{subtitle.slice(0, 95)}</div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const agenticNodeTypes = { agentic: AgenticNodeCard };

function defaultSampleWorkflow(
  projectId: string,
  agents: FullAgent[],
  providers: Provider[],
  queues: Queue[],
): AgenticWorkflow {
  const genId = providers.find((p) => p.purpose === 'generation')?.id || '';
  const linkedAgentId = agents[0]?.id || '';
  const queueId = queues[0]?.id || '';
  return {
    id: `agentic-default-${projectId || 'global'}`,
    project_id: projectId,
    name: 'Multi-Agent Order & Returns Mesh',
    description:
      'Router agent dispatches to specialist agents, parallel sub-agents (FAN-OUT), reflection critic, and pub/sub audit bus.',
    published: true,
    entry: 'router-1',
    nodes: [
      {
        id: 'router-1',
        type: 'router_agent',
        name: 'Triage Router Agent',
        position: { x: 340, y: 40 },
        config: {
          provider_id: genId,
          strategy: 'semantic_intent_and_confidence',
          instructions:
            'Classify customer request and route via DELEGATE, FAN-OUT, or HAND-OFF to specialist agents.',
        },
      },
      {
        id: 'supervisor-1',
        type: 'supervisor_agent',
        name: 'Resolution Supervisor',
        position: { x: 80, y: 220 },
        config: {
          provider_id: genId,
          instructions:
            'Coordinate order lookup and policy verification sub-agents in parallel, then reflect before replying.',
          max_iterations: 6,
        },
      },
      {
        id: 'agent-orders',
        type: 'agent',
        name: agents[0]?.name || 'Order Tracking Agent',
        position: { x: 360, y: 220 },
        config: {
          agent_id: linkedAgentId,
          provider_id: genId,
          instructions: 'Execute order lookup tool and return structured shipping status.',
        },
      },
      {
        id: 'topic-events',
        type: 'pubsub_topic',
        name: 'order.events.bus',
        position: { x: 640, y: 220 },
        config: {
          topic: 'order.events.bus',
          retention: '24h',
          instructions: 'Pub/Sub topic broadcasting order and return state changes to subscribers.',
        },
      },
      {
        id: 'sub-inventory',
        type: 'sub_agent',
        name: 'Inventory Sub-Agent',
        position: { x: 20, y: 410 },
        config: {
          parent_agent: 'supervisor-1',
          provider_id: genId,
          instructions: 'Check warehouse restock eligibility and return label generation.',
        },
      },
      {
        id: 'sub-policy',
        type: 'sub_agent',
        name: 'Refund Policy Sub-Agent',
        position: { x: 240, y: 410 },
        config: {
          parent_agent: 'supervisor-1',
          provider_id: genId,
          instructions: 'Verify 30-day return window and proof-of-purchase compliance.',
        },
      },
      {
        id: 'critic-1',
        type: 'critic_agent',
        name: 'Policy & Tone Critic',
        position: { x: 470, y: 410 },
        config: {
          provider_id: genId,
          criteria: 'Ensure no hallucinated order IDs and verify policy citations.',
          instructions: 'Critique draft response; approve or send REFLECTION feedback.',
        },
      },
      {
        id: 'handoff-1',
        type: 'human_handoff',
        name: 'VIP Human Escalation',
        position: { x: 680, y: 410 },
        config: {
          queue_id: queueId,
          instructions: 'Hand off high-value exceptions to human support queue.',
        },
      },
    ],
    edges: [
      {
        id: 'e-router-sup',
        source: 'router-1',
        target: 'supervisor-1',
        relation: 'DELEGATE',
        condition: 'intent == "complex_return"',
        context_mode: 'full',
      },
      {
        id: 'e-router-agent',
        source: 'router-1',
        target: 'agent-orders',
        relation: 'HAND-OFF',
        condition: 'intent == "track_order"',
        context_mode: 'full',
      },
      {
        id: 'e-router-pubsub',
        source: 'router-1',
        target: 'topic-events',
        relation: 'PUB/SUB',
        condition: 'event:session.routed',
        context_mode: 'structured',
      },
      {
        id: 'e-sup-sub1',
        source: 'supervisor-1',
        target: 'sub-inventory',
        relation: 'FAN-OUT',
        condition: 'parallel_branch_1',
        context_mode: 'summary',
      },
      {
        id: 'e-sup-sub2',
        source: 'supervisor-1',
        target: 'sub-policy',
        relation: 'FAN-OUT',
        condition: 'parallel_branch_2',
        context_mode: 'summary',
      },
      {
        id: 'e-agent-critic',
        source: 'agent-orders',
        target: 'critic-1',
        relation: 'REFLECTION',
        condition: 'verify_Before_send',
        context_mode: 'full',
      },
      {
        id: 'e-pubsub-handoff',
        source: 'topic-events',
        target: 'handoff-1',
        relation: 'FALLBACK',
        condition: 'on_exception_or_vip',
        context_mode: 'full',
      },
    ],
  };
}

function loadWorkflows(
  projectId: string,
  agents: FullAgent[],
  providers: Provider[],
  queues: Queue[],
): AgenticWorkflow[] {
  const key = `ccai_agentic_workflows_${projectId || 'default'}`;
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const parsed = JSON.parse(raw) as AgenticWorkflow[];
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch {
    /* ignore storage errors */
  }
  const initial = [defaultSampleWorkflow(projectId, agents, providers, queues)];
  try {
    localStorage.setItem(key, JSON.stringify(initial));
  } catch {
    /* ignore */
  }
  return initial;
}

function saveWorkflows(projectId: string, workflows: AgenticWorkflow[]) {
  const key = `ccai_agentic_workflows_${projectId || 'default'}`;
  try {
    localStorage.setItem(key, JSON.stringify(workflows));
  } catch {
    /* ignore */
  }
}

export function AgenticStudio({
  projectId,
  activeId,
  onSelectActive,
  agents,
  providers,
  queues,
  notice,
  studioTabBar,
}: {
  projectId: string;
  activeId: string;
  onSelectActive: (id: string) => void;
  agents: FullAgent[];
  providers: Provider[];
  queues: Queue[];
  notice: Notice;
  studioTabBar: React.ReactNode;
}) {
  const [workflows, setWorkflows] = useState<AgenticWorkflow[]>(() =>
    loadWorkflows(projectId, agents, providers, queues),
  );
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const loaded = loadWorkflows(projectId, agents, providers, queues);
    setWorkflows(loaded);
  }, [projectId, agents.length, providers.length, queues.length]);

  const active = workflows.find((w) => w.id === activeId);

  function updateWorkflow(updated: AgenticWorkflow) {
    const next = workflows.map((w) => (w.id === updated.id ? updated : w));
    setWorkflows(next);
    saveWorkflows(projectId, next);
  }

  if (active) {
    return (
      <AgenticCanvasBuilder
        key={active.id}
        workflow={active}
        workflows={workflows}
        selectWorkflow={onSelectActive}
        onUpdate={updateWorkflow}
        onCreatedWorkflow={(created) => {
          const next = [...workflows, created];
          setWorkflows(next);
          saveWorkflows(projectId, next);
          onSelectActive(created.id);
          notice('Agentic workflow created');
        }}
        agents={agents}
        providers={providers}
        queues={queues}
        notice={notice}
        studioTabBar={studioTabBar}
      />
    );
  }

  return (
    <>
      <div className="page-heading">
        <div className="studio-heading-left">
          <h1>Flow studio</h1>
          {studioTabBar}
        </div>
        <div className="toolbar-actions">
          <button className="primary" onClick={() => setCreating(true)}>
            <Plus size={16} />
            New agentic workflow
          </button>
        </div>
      </div>
      <div className="project-layout list-only">
        <section className="panel project-list">
          <div className="section-head">
            <h2>
              Agentic workflows <span className="count">{workflows.length}</span>
            </h2>
          </div>
          {!workflows.length && (
            <Empty
              icon={GitBranch}
              title="Design multi-agent topologies"
              text="Connect router agents, full agents, and sub-agents using DELEGATE, HAND-OFF, FAN-OUT, REFLECTION, and PUB/SUB links."
            />
          )}
          {workflows.map((w) => (
            <button key={w.id} onClick={() => onSelectActive(w.id)}>
              <span className="bot-icon small-icon">
                <GitBranch size={18} />
              </span>
              <div>
                <strong>{w.name}</strong>
                <small>
                  {w.published ? 'Published mesh' : 'Draft mesh'} · {w.nodes.length} agents ·{' '}
                  {w.edges.length} links
                </small>
              </div>
            </button>
          ))}
        </section>
      </div>
      {creating && (
        <CreateAgenticModal
          projectId={projectId}
          providers={providers}
          close={() => setCreating(false)}
          onCreated={(created) => {
            const next = [...workflows, created];
            setWorkflows(next);
            saveWorkflows(projectId, next);
            setCreating(false);
            onSelectActive(created.id);
            notice('Agentic workflow created');
          }}
        />
      )}
    </>
  );
}

function CreateAgenticModal({
  projectId,
  providers,
  close,
  onCreated,
}: {
  projectId: string;
  providers: Provider[];
  close: () => void;
  onCreated: (w: AgenticWorkflow) => void;
}) {
  const genId = providers.find((p) => p.purpose === 'generation')?.id || '';
  return (
    <Modal title="Create an agentic workflow" close={close}>
      <p className="muted">
        Build a multi-agent graph with router agents, specialist agents, sub-agents, and typed
        protocols (DELEGATE, HAND-OFF, FAN-OUT, REFLECTION, PUB/SUB).
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          const name = String(f.get('name') || 'Agentic Workflow');
          const description = String(f.get('description') || '');
          const created: AgenticWorkflow = {
            id: crypto.randomUUID(),
            project_id: projectId,
            name,
            description,
            published: false,
            entry: 'router-entry',
            nodes: [
              {
                id: 'router-entry',
                type: 'router_agent',
                name: 'Router Agent',
                position: { x: 260, y: 60 },
                config: {
                  provider_id: genId,
                  strategy: 'semantic_routing',
                  instructions: 'Route incoming tasks across specialist agents and sub-agents.',
                },
              },
              {
                id: 'specialist-1',
                type: 'agent',
                name: 'Specialist Agent',
                position: { x: 120, y: 250 },
                config: {
                  provider_id: genId,
                  instructions: 'Handle primary domain tasks and delegate subtasks.',
                },
              },
              {
                id: 'subagent-1',
                type: 'sub_agent',
                name: 'Worker Sub-Agent',
                position: { x: 400, y: 250 },
                config: {
                  parent_agent: 'specialist-1',
                  provider_id: genId,
                  instructions: 'Execute focused verification or tool retrieval.',
                },
              },
            ],
            edges: [
              {
                id: crypto.randomUUID(),
                source: 'router-entry',
                target: 'specialist-1',
                relation: 'DELEGATE',
                condition: 'primary_task',
                context_mode: 'full',
              },
              {
                id: crypto.randomUUID(),
                source: 'router-entry',
                target: 'subagent-1',
                relation: 'FAN-OUT',
                condition: 'parallel_subtask',
                context_mode: 'summary',
              },
            ],
          };
          onCreated(created);
        }}
      >
        <Field label="Workflow name">
          <input
            name="name"
            required
            maxLength={120}
            placeholder="Multi-agent customer resolution"
            autoFocus
          />
        </Field>
        <Field label="Description">
          <textarea
            name="description"
            rows={3}
            maxLength={5000}
            placeholder="How do the agents collaborate in this workflow?"
          />
        </Field>
        <button className="primary wide">
          <Plus size={16} />
          Create agentic workflow
        </button>
      </form>
    </Modal>
  );
}

function AgenticCanvasBuilder({
  workflow,
  workflows,
  selectWorkflow,
  onUpdate,
  onCreatedWorkflow,
  agents,
  providers,
  queues,
  notice,
  studioTabBar,
}: {
  workflow: AgenticWorkflow;
  workflows: AgenticWorkflow[];
  selectWorkflow: (id: string) => void;
  onUpdate: (w: AgenticWorkflow) => void;
  onCreatedWorkflow: (w: AgenticWorkflow) => void;
  agents: FullAgent[];
  providers: Provider[];
  queues: Queue[];
  notice: Notice;
  studioTabBar: React.ReactNode;
}) {
  const [measured, setMeasured] = useState<Record<string, { width: number; height: number }>>({});
  const [draft, setDraft] = useState<AgenticWorkflow>(workflow);
  const [selectedNodeId, setSelectedNodeId] = useState<string>(workflow.entry);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string>('');
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string>('');
  const [activeRelation, setActiveRelation] = useState<AgenticConnectionKind>('DELEGATE');
  const [dirty, setDirty] = useState(false);
  const [creatingModal, setCreatingModal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<TestSession>();
  const [tools] = useLoad<Tool[]>(() => api('/tools'), [], notice);

  const selectedNode = draft.nodes.find((n) => n.id === selectedNodeId);
  const selectedEdge = draft.edges.find((e) => e.id === selectedEdgeId);

  function update(next: AgenticWorkflow) {
    setDraft(next);
    setDirty(true);
  }

  const canvasNodes: AgenticCanvasNode[] = draft.nodes.map((n) => ({
    id: n.id,
    type: 'agentic',
    position: n.position,
    measured: measured[n.id],
    data: {
      kind: n.type,
      name: n.name,
      config: n.config,
      entry: n.id === draft.entry,
    },
    selected: n.id === selectedNodeId && !selectedEdgeId,
  }));

  const canvasEdges: Edge[] = draft.edges.map((e) => {
    const meta = CONNECTION_META[e.relation] || CONNECTION_META.DELEGATE;
    const isSelected = e.id === selectedEdgeId;
    const isHovered = e.id === hoveredEdgeId;
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      label: isHovered ? (e.condition ? `${e.relation} · ${e.condition}` : e.relation) : undefined,
      interactionWidth: 28,
      type: 'smoothstep',
      animated: !!meta.animated,
      selected: isSelected,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: meta.color,
        width: 18,
        height: 18,
      },
      style: {
        stroke: meta.color,
        strokeWidth: isSelected || isHovered ? 2.8 : 2.1,
        strokeDasharray: meta.dash,
      },
      labelStyle: {
        fill: meta.color,
        fontWeight: 700,
        fontSize: 10,
        letterSpacing: '0.5px',
      },
      labelBgStyle: {
        fill: meta.bg,
        stroke: meta.color,
        strokeWidth: 1.2,
      },
      labelBgPadding: [7, 4] as [number, number],
      labelBgBorderRadius: 5,
    };
  });

  const onNodesChange = (changes: NodeChange<AgenticCanvasNode>[]) => {
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
    if (changes.some((c) => c.type === 'position' || c.type === 'remove')) {
      update({
        ...draft,
        nodes: draft.nodes
          .filter((n) => updated.some((u) => u.id === n.id))
          .map((n) => ({ ...n, position: updated.find((u) => u.id === n.id)!.position })),
        edges: draft.edges.filter(
          (e) => updated.some((n) => n.id === e.source) && updated.some((n) => n.id === e.target),
        ),
      });
    }
  };

  function connect(c: Connection) {
    if (!c.source || !c.target || c.source === c.target) return;
    const newEdge: AgenticFlowEdge = {
      id: crypto.randomUUID(),
      source: c.source,
      target: c.target,
      relation: activeRelation,
      condition: '',
      context_mode: activeRelation === 'FAN-OUT' ? 'summary' : 'full',
    };
    update({
      ...draft,
      edges: [...draft.edges, newEdge],
    });
    setSelectedEdgeId(newEdge.id);
    setSelectedNodeId('');
  }

  function addNode(kind: AgenticNodeKind) {
    const id = crypto.randomUUID();
    const genId = providers.find((p) => p.purpose === 'generation')?.id || '';
    const defaultConfigs: Record<AgenticNodeKind, Record<string, unknown>> = {
      router_agent: {
        provider_id: genId,
        strategy: 'semantic_intent_and_confidence',
        instructions: 'Route requests across agents and sub-agents.',
      },
      supervisor_agent: {
        provider_id: genId,
        max_iterations: 6,
        instructions: 'Decompose complex tasks, delegate to sub-agents, and synthesize output.',
      },
      agent: {
        agent_id: agents[0]?.id || '',
        provider_id: genId,
        instructions: 'Autonomous domain specialist agent.',
        tool_ids: [],
      },
      sub_agent: {
        parent_agent: selectedNode?.id || '',
        provider_id: genId,
        instructions: 'Focused sub-agent for a single subtask or tool call.',
        tool_ids: [],
      },
      critic_agent: {
        provider_id: genId,
        criteria: 'Accuracy, policy compliance, and tone verification.',
        instructions: 'Review agent output and trigger REFLECTION loop if revisions are needed.',
      },
      aggregator: {
        strategy: 'consensus_merge',
        instructions: 'Combine parallel FAN-OUT branch outputs into one unified response.',
      },
      pubsub_topic: {
        topic: 'agent.events',
        retention: '24h',
        instructions: 'Event bus channel for asynchronous PUB/SUB agent communication.',
      },
      human_handoff: {
        queue_id: queues[0]?.id || '',
        instructions: 'Transfer control to a human operator queue.',
      },
    };
    const anchorX =
      selectedNode?.position.x ?? draft.nodes[draft.nodes.length - 1]?.position.x ?? 260;
    const maxY = draft.nodes.length ? Math.max(...draft.nodes.map((n) => n.position.y)) : -80;
    const nextNode: AgenticFlowNode = {
      id,
      type: kind,
      name: NODE_LABELS[kind],
      position: { x: anchorX, y: maxY + 160 },
      config: defaultConfigs[kind],
    };
    update({
      ...draft,
      nodes: [...draft.nodes, nextNode],
    });
    setSelectedNodeId(id);
    setSelectedEdgeId('');
  }

  function updateNodeConfig(key: string, value: unknown) {
    if (!selectedNode) return;
    update({
      ...draft,
      nodes: draft.nodes.map((n) =>
        n.id === selectedNode.id ? { ...n, config: { ...n.config, [key]: value } } : n,
      ),
    });
  }

  function updateEdge(patch: Partial<AgenticFlowEdge>) {
    if (!selectedEdge) return;
    update({
      ...draft,
      edges: draft.edges.map((e) => (e.id === selectedEdge.id ? { ...e, ...patch } : e)),
    });
  }

  return (
    <div className="studio">
      <div className="studio-toolbar">
        <div className="studio-title">
          <button
            className="icon-button"
            aria-label="All agentic workflows"
            title="All agentic workflows"
            onClick={() => selectWorkflow('')}
          >
            <ChevronLeft size={17} />
          </button>
          <span className="bot-icon small-icon">
            <GitBranch size={19} />
          </span>
          <div>
            <select
              aria-label="Selected agentic workflow"
              value={draft.id}
              onChange={(e) => selectWorkflow(e.target.value)}
            >
              {workflows.map((w) => (
                <option value={w.id} key={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
            <span className="small muted">
              {dirty
                ? 'Unsaved changes'
                : draft.published
                  ? 'Published · multi-agent mesh'
                  : 'Draft · multi-agent mesh'}
            </span>
          </div>
          <button
            className="icon-button"
            onClick={() => setCreatingModal(true)}
            aria-label="New agentic workflow"
            title="New agentic workflow"
          >
            <Plus size={16} />
          </button>
        </div>
        {studioTabBar}
        <div className="toolbar-actions">
          <button
            className="secondary compact"
            onClick={() => {
              onUpdate(draft);
              setDirty(false);
              notice('Agentic workflow saved');
            }}
          >
            <Save size={15} />
            Save
          </button>
          <button
            className="secondary compact"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                onUpdate(draft);
                setDirty(false);
                setTest(
                  await post<TestSession>(`/projects/${draft.project_id}/agentic/test`, {
                    workflow: draft,
                  }),
                );
              } catch (e) {
                notice((e as Error).message, true);
              } finally {
                setBusy(false);
              }
            }}
          >
            <MessageCircle size={15} />
            Test chat
          </button>
          <button
            className="primary compact"
            onClick={() => {
              const pub = { ...draft, published: true };
              setDraft(pub);
              onUpdate(pub);
              setDirty(false);
              notice('Agentic workflow published');
            }}
          >
            <Rocket size={15} />
            Publish
          </button>
        </div>
      </div>
      <div className="studio-layout">
        <aside className="node-palette">
          <div className="nav-label">AGENTIC COMPONENTS</div>
          <p>
            Add router agents, full agents, and sub-agents.
          </p>
          {(Object.entries(NODE_LABELS) as [AgenticNodeKind, string][]).map(([kind, label]) => {
            const Icon = NODE_ICONS[kind];
            return (
              <button key={kind} onClick={() => addNode(kind)}>
                <span className={`palette-icon kind-${kind}`}>
                  <Icon size={17} />
                </span>
                <span>{label}</span>
                <Plus size={13} />
              </button>
            );
          })}
          <div className="palette-tip agentic-protocol-picker">
            <div className="nav-label">CONNECTION TYPE</div>
            <p>Select protocol before dragging a link between agents:</p>
            <div className="connection-type-pills">
              {CONNECTION_KINDS.map((rel) => {
                const meta = CONNECTION_META[rel];
                const active = activeRelation === rel;
                return (
                  <button
                    key={rel}
                    type="button"
                    className={`connection-pill ${active ? 'active' : ''}`}
                    style={
                      active
                        ? {
                            borderColor: meta.color,
                            background: meta.bg,
                            color: meta.color,
                          }
                        : undefined
                    }
                    onClick={() => {
                      setActiveRelation(rel);
                      if (selectedEdge) updateEdge({ relation: rel });
                    }}
                  >
                    <span
                      className="connection-dot"
                      style={{ background: meta.color }}
                    />
                    {rel}
                  </button>
                );
              })}
            </div>
            <small className="muted block">
              {CONNECTION_META[activeRelation].description}
            </small>
          </div>
        </aside>
        <div className="canvas">
          <div className="canvas-label">
            <GitBranch size={15} />
            Agentic workflow <span>Active link: {activeRelation}</span>
          </div>
          <ReactFlow
            nodes={canvasNodes}
            edges={canvasEdges}
            nodeTypes={agenticNodeTypes}
            onNodesChange={onNodesChange}
            onNodeClick={(_, n) => {
              setSelectedNodeId(n.id);
              setSelectedEdgeId('');
            }}
            onEdgeClick={(_, e) => {
              setSelectedEdgeId(e.id);
              setSelectedNodeId('');
            }}
            onEdgeMouseEnter={(_, e) => setHoveredEdgeId(e.id)}
            onEdgeMouseLeave={() => setHoveredEdgeId('')}
            onConnect={connect}
            onEdgesDelete={(deleted) =>
              update({
                ...draft,
                edges: draft.edges.filter((e) => !deleted.some((x) => x.id === e.id)),
              })
            }
            fitView
            fitViewOptions={{ padding: 0.25 }}
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
            <span>{selectedEdge ? 'CONNECTION SETTINGS' : 'AGENT NODE SETTINGS'}</span>
            <MoreHorizontal size={17} />
          </div>
          {selectedEdge ? (
            <>
              <div className="inspector-title">
                <h3>{selectedEdge.relation} Connection</h3>
                <span className="muted small">
                  {draft.nodes.find((n) => n.id === selectedEdge.source)?.name || 'Source'} →{' '}
                  {draft.nodes.find((n) => n.id === selectedEdge.target)?.name || 'Target'}
                </span>
              </div>
              <Field
                label="Connection type"
                hint={CONNECTION_META[selectedEdge.relation]?.description}
              >
                <select
                  value={selectedEdge.relation}
                  onChange={(e) =>
                    updateEdge({ relation: e.target.value as AgenticConnectionKind })
                  }
                >
                  {CONNECTION_KINDS.map((rel) => (
                    <option key={rel} value={rel}>
                      {rel}
                    </option>
                  ))}
                </select>
              </Field>
              <Field
                label="Routing condition / event topic"
                hint="Optional guard expression, intent match, or pub/sub event key."
              >
                <input
                  value={selectedEdge.condition || ''}
                  onChange={(e) => updateEdge({ condition: e.target.value })}
                  placeholder="e.g. intent == 'refund' or event:order.updated"
                />
              </Field>
              <Field label="Context payload mode">
                <select
                  value={selectedEdge.context_mode || 'full'}
                  onChange={(e) =>
                    updateEdge({
                      context_mode: e.target.value as 'full' | 'summary' | 'structured',
                    })
                  }
                >
                  <option value="full">Full conversation context</option>
                  <option value="summary">Task summary only</option>
                  <option value="structured">Structured JSON payload</option>
                </select>
              </Field>
              <button
                className="danger text-button"
                onClick={() => {
                  update({
                    ...draft,
                    edges: draft.edges.filter((e) => e.id !== selectedEdge.id),
                  });
                  setSelectedEdgeId('');
                }}
              >
                <Trash2 size={15} />
                Delete connection
              </button>
            </>
          ) : selectedNode ? (
            <>
              <div className="inspector-title">
                <h3>{NODE_LABELS[selectedNode.type]}</h3>
                <span className="muted small">{selectedNode.id.slice(0, 16)}</span>
              </div>
              <Field label="Component name">
                <input
                  value={selectedNode.name}
                  onChange={(e) =>
                    update({
                      ...draft,
                      nodes: draft.nodes.map((n) =>
                        n.id === selectedNode.id ? { ...n, name: e.target.value } : n,
                      ),
                    })
                  }
                />
              </Field>
              <Field label="Entry component">
                <select
                  value={draft.entry}
                  onChange={(e) => update({ ...draft, entry: e.target.value })}
                >
                  {draft.nodes.map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.name} ({NODE_LABELS[n.type]})
                    </option>
                  ))}
                </select>
              </Field>
              {selectedNode.type === 'agent' && (
                <Field
                  label="Bind published full agent"
                  hint="Optional: link to a reusable full agent from Agent builder."
                >
                  <select
                    value={String(selectedNode.config.agent_id || '')}
                    onChange={(e) => updateNodeConfig('agent_id', e.target.value)}
                  >
                    <option value="">Inline agent definition</option>
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} {a.published_id ? '(Published)' : '(Draft)'}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
              {selectedNode.type === 'sub_agent' && (
                <Field label="Parent supervisor / agent">
                  <select
                    value={String(selectedNode.config.parent_agent || '')}
                    onChange={(e) => updateNodeConfig('parent_agent', e.target.value)}
                  >
                    <option value="">Select parent agent</option>
                    {draft.nodes
                      .filter((n) => n.id !== selectedNode.id)
                      .map((n) => (
                        <option key={n.id} value={n.id}>
                          {n.name}
                        </option>
                      ))}
                  </select>
                </Field>
              )}
              {[
                'router_agent',
                'supervisor_agent',
                'agent',
                'sub_agent',
                'critic_agent',
              ].includes(selectedNode.type) && (
                <Field label="Model connection">
                  <select
                    value={String(selectedNode.config.provider_id || '')}
                    onChange={(e) => updateNodeConfig('provider_id', e.target.value)}
                  >
                    <option value="">Select a generation model</option>
                    {providers
                      .filter((p) => p.purpose === 'generation')
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} · {p.model}
                        </option>
                      ))}
                  </select>
                </Field>
              )}
              {selectedNode.type === 'router_agent' && (
                <Field label="Routing strategy">
                  <select
                    value={String(selectedNode.config.strategy || 'semantic_intent_and_confidence')}
                    onChange={(e) => updateNodeConfig('strategy', e.target.value)}
                  >
                    <option value="semantic_intent_and_confidence">
                      Semantic intent &amp; confidence
                    </option>
                    <option value="llm_tool_dispatch">LLM function/tool dispatch</option>
                    <option value="round_robin_fanout">Parallel fan-out broadcast</option>
                    <option value="hierarchical_supervisor">Hierarchical delegation</option>
                  </select>
                </Field>
              )}
              {selectedNode.type === 'pubsub_topic' && (
                <Field label="Event topic channel">
                  <input
                    value={String(selectedNode.config.topic || '')}
                    onChange={(e) => updateNodeConfig('topic', e.target.value)}
                    placeholder="order.events.bus"
                  />
                </Field>
              )}
              {selectedNode.type === 'human_handoff' && (
                <Field label="Escalation queue">
                  <select
                    value={String(selectedNode.config.queue_id || '')}
                    onChange={(e) => updateNodeConfig('queue_id', e.target.value)}
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
              {['agent', 'sub_agent'].includes(selectedNode.type) && (
                <Field label="Allowed shared tools">
                  <select
                    multiple
                    value={(selectedNode.config.tool_ids || []) as string[]}
                    onChange={(e) =>
                      updateNodeConfig(
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
              )}
              <Field label="Instructions / behavior">
                <textarea
                  rows={5}
                  value={String(selectedNode.config.instructions || '')}
                  onChange={(e) => updateNodeConfig('instructions', e.target.value)}
                />
              </Field>
              <Field
                label="Outgoing agent connections"
                hint="Click any edge on the canvas or below to edit its connection type."
              >
                <div className="agentic-edge-list">
                  {draft.edges
                    .filter((e) => e.source === selectedNode.id)
                    .map((e) => {
                      const target = draft.nodes.find((n) => n.id === e.target);
                      return (
                        <button
                          key={e.id}
                          type="button"
                          className="agentic-edge-item"
                          onClick={() => {
                            setSelectedEdgeId(e.id);
                            setSelectedNodeId('');
                          }}
                        >
                          <Badge tone="green">{e.relation}</Badge>
                          <span>→ {target?.name || 'Agent'}</span>
                        </button>
                      );
                    })}
                  {!draft.edges.some((e) => e.source === selectedNode.id) && (
                    <small className="muted">
                      Drag from this node’s bottom handle to another node to connect.
                    </small>
                  )}
                </div>
              </Field>
              <details className="advanced">
                <summary>Advanced configuration</summary>
                <JsonField
                  key={selectedNode.id}
                  label="Node configuration (JSON)"
                  value={selectedNode.config}
                  change={(v) =>
                    update({
                      ...draft,
                      nodes: draft.nodes.map((n) =>
                        n.id === selectedNode.id
                          ? { ...n, config: v as Record<string, unknown> }
                          : n,
                      ),
                    })
                  }
                />
              </details>
              <button
                className="danger text-button"
                onClick={() => {
                  update({
                    ...draft,
                    nodes: draft.nodes.filter((n) => n.id !== selectedNode.id),
                    edges: draft.edges.filter(
                      (e) => e.source !== selectedNode.id && e.target !== selectedNode.id,
                    ),
                  });
                  setSelectedNodeId('');
                }}
              >
                <Trash2 size={15} />
                Delete component
              </button>
            </>
          ) : (
            <p className="muted">
              Select an agent node or connection edge on the canvas to configure it.
            </p>
          )}
        </aside>
      </div>
      {creatingModal && (
        <CreateAgenticModal
          projectId={draft.project_id}
          providers={providers}
          close={() => setCreatingModal(false)}
          onCreated={(created) => {
            setCreatingModal(false);
            onCreatedWorkflow(created);
          }}
        />
      )}
      {test && (
        <ConversationTest
          title={`Test · ${draft.name}`}
          session={test}
          close={() => setTest(undefined)}
          notice={notice}
        />
      )}
    </div>
  );
}
