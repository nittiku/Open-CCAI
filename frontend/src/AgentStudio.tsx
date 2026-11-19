import { useState, useEffect } from 'react';
import {
  Bot as BotIcon,
  Plus,
  Save,
  Rocket,
  MessageCircle,
  Code2,
  BookOpen,
  Eye,
  ArrowRight,
  Trash2,
} from 'lucide-react';
import {
  api,
  del,
  post,
  put,
  type Project,
  type FullAgent,
  type AgentDefinition,
  type Provider,
  type Tool,
  type Collection,
  type DocumentDetail,
  type Bot as Flow,
  type TestSession,
} from './api';
import { Badge, Field, Empty, Modal, JsonField, useLoad, ConfigSection, type Notice } from './ui';
import { ConversationTest } from './conversation';

const initial: AgentDefinition = {
  provider_id: null,
  instructions: '',
  tool_ids: [],
  collection_ids: [],
  sub_agent_ids: [],
  delegate_agent_ids: [],
  parallel_agent_ids: [],
  max_iterations: 8,
  output_schema: null,
};
export function AgentStudio({
  project,
  projects,
  agents,
  providers,
  flows,
  refresh,
  notice,
  openProjects,
  openTools,
}: {
  project: Project | undefined;
  projects: Project[];
  agents: FullAgent[];
  providers: Provider[];
  flows: Flow[];
  refresh: () => Promise<unknown>;
  notice: Notice;
  openProjects: () => void;
  openTools: () => void;
}) {
  const [selected, setSelected] = useState('');
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    setSelected('');
  }, [project?.id]);
  const current = agents.find((a) => a.id === selected);
  const [tools] = useLoad<Tool[]>(() => api('/tools'), [], notice);
  const [collections] = useLoad<Collection[]>(() => api('/collections'), [], notice);
  return (
    <>
      <div className="page-heading">
        <h1>Agents</h1>
        <button
          className="primary"
          onClick={() => (projects.length ? setCreating(true) : openProjects())}
        >
          <Plus size={16} />
          New agent
        </button>
      </div>
      <div className={`project-layout ${current ? '' : 'list-only'}`}>
        <section className="panel project-list">
          <div className="section-head">
            <h2>
              Agents <span className="count">{agents.length}</span>
            </h2>
          </div>
          {!agents.length && (
            <Empty
              icon={BotIcon}
              title="No agents yet"
              text="Create an agent, then select it to configure its instructions, tools, and knowledge."
            />
          )}
          {agents.map((a) => (
            <button
              key={a.id}
              className={a.id === current?.id ? 'selected' : ''}
              aria-expanded={a.id === current?.id}
              onClick={() => setSelected(current?.id === a.id ? '' : a.id)}
            >
              <span className="bot-icon small-icon">
                <BotIcon size={18} />
              </span>
              <div>
                <strong>{a.name}</strong>
                <small>
                  {!project &&
                    `${
                      a.project_id
                        ? projects.find((p) => p.id === a.project_id)?.name || 'Project'
                        : 'Unassigned'
                    } · `}
                  {a.published_id ? 'Published' : 'Draft'}
                </small>
              </div>
            </button>
          ))}
        </section>
        {current ? (
          <AgentEditor
            key={current.id}
            agent={current}
            agents={agents}
            providers={providers}
            tools={tools || []}
            collections={(collections || []).filter((c) =>
              flows.some((f) => f.id === c.bot_id && f.project_id === current.project_id),
            )}
            refresh={refresh}
            notice={notice}
            openTools={openTools}
          />
        ) : null}
      </div>
      {creating && (
        <Modal title="Create a full agent" close={() => setCreating(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              try {
                await post<FullAgent>('/agents', {
                  project_id: f.get('project_id'),
                  name: f.get('name'),
                  description: f.get('description'),
                  purpose: f.get('purpose'),
                  definition: initial,
                });
                await refresh();
                setSelected('');
                setCreating(false);
                notice('Agent draft created');
              } catch (err) {
                notice((err as Error).message, true);
              }
            }}
          >
            <Field label="Project">
              <select name="project_id" required defaultValue={project?.id || ''}>
                <option value="" disabled>
                  Select a project
                </option>
                {(project ? [project] : projects).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Agent name">
              <input name="name" required maxLength={120} placeholder="Order support specialist" />
            </Field>
            <Field label="Description">
              <textarea
                name="description"
                rows={3}
                maxLength={5000}
                placeholder="Describe this agent’s expertise"
              />
            </Field>
            <Field label="Purpose">
              <textarea
                name="purpose"
                rows={3}
                maxLength={5000}
                placeholder="When should the orchestrator route to this agent?"
              />
            </Field>
            <button className="primary wide">Create agent</button>
          </form>
        </Modal>
      )}
    </>
  );
}
function AgentEditor({
  agent,
  agents,
  providers,
  tools,
  collections,
  refresh,
  notice,
  openTools,
}: {
  agent: FullAgent;
  agents: FullAgent[];
  providers: Provider[];
  tools: Tool[];
  collections: Collection[];
  refresh: () => Promise<unknown>;
  notice: Notice;
  openTools: () => void;
}) {
  const [draft, setDraft] = useState(agent);
  const [definition, setDefinition] = useState({ ...initial, ...agent.draft });
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [test, setTest] = useState<TestSession>();
  const [viewingCollection, setViewingCollection] = useState<{
    collection: Collection;
    documents: DocumentDetail[];
  }>();
  const set = (key: keyof AgentDefinition, value: unknown) =>
    setDefinition((d) => ({ ...d, [key]: value }));
  const toggle = (
    key:
      | 'tool_ids'
      | 'collection_ids'
      | 'sub_agent_ids'
      | 'delegate_agent_ids'
      | 'parallel_agent_ids',
    id: string,
  ) => {
    const current = definition[key] || [];
    set(key, current.includes(id) ? current.filter((x) => x !== id) : [...current, id]);
  };
  async function action(kind: 'save' | 'publish' | 'test') {
    setBusy(true);
    try {
      const saved = await put<{ errors: string[] }>(`/agents/${agent.id}`, {
        name: draft.name,
        description: draft.description,
        purpose: draft.purpose,
        project_id: agent.project_id,
        definition,
      });
      if (kind === 'publish') await post(`/agents/${agent.id}/publish`);
      if (kind === 'test') setTest(await post(`/agents/${agent.id}/test`));
      await refresh();
      notice(
        kind === 'publish'
          ? 'Agent version published. Republish the project or flow to use it in new sessions.'
          : kind === 'test'
            ? 'Agent test started'
            : saved.errors.length
              ? 'Draft saved; configure the remaining fields before publishing.'
              : 'Agent draft saved',
      );
    } catch (e) {
      notice((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="project-editor">
      <ConfigSection
        label="Agent configuration"
        title={
          <>
            {agent.name}{' '}
            <Badge tone={agent.published_id ? 'green' : ''}>
              {agent.published_id ? 'Published' : 'Draft'}
            </Badge>
          </>
        }
        description={
          'Available to the project orchestrator and reusable Agent steps in Flow studio.'
        }
        actions={
          <div className="toolbar-actions">
            <button
              className="secondary compact"
              disabled={busy}
              onClick={() => setConfirmDelete(true)}
              aria-label="Delete agent"
              title="Delete agent"
            >
              <Trash2 size={15} />
              Delete
            </button>
            <button className="secondary compact" disabled={busy} onClick={() => action('save')}>
              <Save size={15} />
              Save
            </button>
            <button className="secondary compact" disabled={busy} onClick={() => action('test')}>
              <MessageCircle size={15} />
              Test
            </button>
            <button className="primary compact" disabled={busy} onClick={() => action('publish')}>
              <Rocket size={15} />
              Publish
            </button>
          </div>
        }
      >
        <div className="editor-fields">
          <Field label="Agent name">
            <input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              maxLength={120}
            />
          </Field>
          <div className="form-row">
            <Field label="Description">
              <textarea
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                rows={3}
                maxLength={5000}
              />
            </Field>
            <Field label="Purpose">
              <textarea
                value={draft.purpose}
                onChange={(e) => setDraft({ ...draft, purpose: e.target.value })}
                rows={3}
                maxLength={5000}
              />
            </Field>
          </div>
          <div className="form-row">
            <Field label="Generation model">
              <select
                value={definition.provider_id || ''}
                onChange={(e) => set('provider_id', e.target.value || null)}
              >
                <option value="">Select a model connection</option>
                {providers
                  .filter((p) => p.purpose === 'generation')
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {p.model}
                    </option>
                  ))}
              </select>
            </Field>
            <Field
              label="Maximum model iterations"
              hint="Each turn has a bounded execution budget."
            >
              <input
                type="number"
                min={1}
                max={16}
                value={definition.max_iterations}
                onChange={(e) => set('max_iterations', Number(e.target.value))}
              />
            </Field>
          </div>
          <Field
            label="Agent instructions"
            hint="Describe its role, behavior, limits, and how to use its enabled tools."
          >
            <textarea
              rows={9}
              value={definition.instructions}
              onChange={(e) => set('instructions', e.target.value)}
              maxLength={20000}
              placeholder="You help customers track their orders. Use lookup_order for order status. Ask for the order reference when it is missing…"
            />
          </Field>
          <label className="check-label">
            <input
              type="checkbox"
              checked={!!definition.output_schema}
              onChange={(e) =>
                set(
                  'output_schema',
                  e.target.checked
                    ? {
                        type: 'object',
                        properties: { answer: { type: 'string' } },
                        required: ['answer'],
                        additionalProperties: false,
                      }
                    : null,
                )
              }
            />
            Require structured output
          </label>
          {definition.output_schema && (
            <JsonField
              label="Output JSON Schema"
              value={definition.output_schema}
              change={(v) => set('output_schema', v)}
            />
          )}
        </div>
      </ConfigSection>
      <ConfigSection
        label="Tools"
        title={
          <>
            <Code2 size={18} /> Tools
          </>
        }
        description={
          'The same registered tools are available to full agents, Mini agents, and HTTP tool steps.'
        }
        actions={
          <button className="text-button" onClick={openTools}>
            Open tool library
            <ArrowRight size={15} />
          </button>
        }
      >
        <div className="target-list">
          {tools.map((t) => (
            <label className="target-row" key={t.id}>
              <input
                type="checkbox"
                checked={definition.tool_ids.includes(t.id)}
                onChange={() => toggle('tool_ids', t.id)}
              />
              <Code2 size={18} />
              <div>
                <strong>{t.name}</strong>
                <p>{t.description || 'Registered HTTP tool'}</p>
              </div>
            </label>
          ))}
          {!tools.length && (
            <p className="pad muted">
              Register a tool in the shared library, then enable it for this agent.
            </p>
          )}
        </div>
      </ConfigSection>
      <ConfigSection
        label="Multi-agent composition (ADK)"
        title={
          <>
            <BotIcon size={18} /> Agent handoff, delegation & fan-out
          </>
        }
        description="Compose other published agents in this project using Google ADK sub_agents, AgentTool delegation, or ParallelAgent fan-out."
      >
        {(() => {
          const peers = agents.filter(
            (a) => a.project_id === agent.project_id && a.id !== agent.id && a.published_id,
          );
          if (!peers.length) {
            return (
              <p className="pad muted">
                Publish another agent in this project to enable handoff, delegation, or fan-out.
              </p>
            );
          }
          const groups: Array<{
            key: 'sub_agent_ids' | 'delegate_agent_ids' | 'parallel_agent_ids';
            title: string;
            hint: string;
          }> = [
            {
              key: 'sub_agent_ids',
              title: 'Handoff sub-agents (ADK transfer_to_agent)',
              hint: 'Agent can transfer control to these specialists.',
            },
            {
              key: 'delegate_agent_ids',
              title: 'Delegate tools (ADK AgentTool)',
              hint: 'Agent can call these specialists like tools and keep control.',
            },
            {
              key: 'parallel_agent_ids',
              title: 'Parallel fan-out (ADK ParallelAgent)',
              hint: 'Run these specialists concurrently first, then synthesize with this agent.',
            },
          ];
          return (
            <div className="stack">
              {groups.map((g) => (
                <Field key={g.key} label={g.title} hint={g.hint}>
                  <div className="target-list">
                    {peers.map((p) => (
                      <label className="target-row" key={`${g.key}:${p.id}`}>
                        <input
                          type="checkbox"
                          checked={(definition[g.key] || []).includes(p.id)}
                          onChange={() => toggle(g.key, p.id)}
                        />
                        <BotIcon size={18} />
                        <div>
                          <strong>{p.name}</strong>
                          <p>{p.purpose || p.description || 'Published project agent'}</p>
                        </div>
                      </label>
                    ))}
                  </div>
                </Field>
              ))}
            </div>
          );
        })()}
      </ConfigSection>
      <ConfigSection
        label="Project knowledge"
        title={
          <>
            <BookOpen size={18} /> Project knowledge
          </>
        }
        description={"Select collections owned by this project's intents."}
      >
        <div className="target-list">
          {collections.map((c) => (
            <div className="target-row" key={c.id}>
              <input
                type="checkbox"
                aria-label={`Enable ${c.name}`}
                checked={definition.collection_ids.includes(c.id)}
                onChange={() => toggle('collection_ids', c.id)}
              />
              <BookOpen size={18} />
              <div>
                <strong>{c.name}</strong>
                <p>Collection generation {c.generation}</p>
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label={`View ${c.name}`}
                title={`View ${c.name}`}
                onClick={async () => {
                  try {
                    const list = await api<{ id: string }[]>(`/collections/${c.id}/documents`);
                    const documents = await Promise.all(
                      list.map((d) => api<DocumentDetail>(`/documents/${d.id}`)),
                    );
                    setViewingCollection({ collection: c, documents });
                  } catch (e) {
                    notice((e as Error).message, true);
                  }
                }}
              >
                <Eye size={16} />
              </button>
            </div>
          ))}
          {!collections.length && (
            <p className="pad muted">
              Create a knowledge collection for an intent in this project to make it available here.
            </p>
          )}
        </div>
      </ConfigSection>
      {viewingCollection && (
        <Modal
          title={viewingCollection.collection.name}
          close={() => setViewingCollection(undefined)}
        >
          {viewingCollection.documents.length ? (
            <div className="kb-chunks">
              {viewingCollection.documents.map((doc) => (
                <div key={doc.id} className="kb-chunk-card">
                  <div className="kb-chunk-head">
                    <strong>{doc.name}</strong>
                    <Badge
                      tone={
                        doc.status === 'ready' ? 'green' : doc.status === 'error' ? 'red' : ''
                      }
                    >
                      {doc.status}
                    </Badge>
                  </div>
                  <pre className="code-block kb-preview">
                    {doc.content || 'No extractable text available.'}
                  </pre>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No documents uploaded to this collection yet.</p>
          )}
        </Modal>
      )}
      {test && (
        <ConversationTest
          session={test}
          title={`Test ${agent.name}`}
          close={() => setTest(undefined)}
          notice={notice}
        />
      )}
      {confirmDelete && (
        <Modal title="Delete agent" close={() => !busy && setConfirmDelete(false)}>
          <p className="muted">
            Delete <strong>{agent.name}</strong>? This removes the agent and its published versions.
          </p>
          <div className="toolbar-actions">
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => setConfirmDelete(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await del(`/agents/${agent.id}`);
                  setConfirmDelete(false);
                  await refresh();
                  notice('Agent deleted');
                } catch (e) {
                  notice((e as Error).message, true);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <Trash2 size={15} />
              Delete agent
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
