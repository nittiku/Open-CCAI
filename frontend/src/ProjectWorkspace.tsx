import React, { useState, useEffect } from 'react';
import {
  Plus,
  Workflow,
  Bot,
  GitBranch,
  Save,
  Rocket,
  MessageCircle,
  ArrowRight,
  Code2,
} from 'lucide-react';
import {
  api,
  post,
  put,
  type Project,
  type Bot as Flow,
  type FullAgent,
  type Provider,
  type Queue,
  type Orchestrator,
  type TestSession,
} from './api';
import { Field, Modal, Badge, Empty, ConfigSection, type Notice } from './ui';
import { ConversationTest } from './conversation';

const emptyOrchestrator: Orchestrator = {
  provider_id: null,
  description: '',
  purpose: '',
  instructions: '',
  welcome: 'Hello! What can I help you with?',
  flow_ids: [],
  agent_ids: [],
  fallback_queue_id: null,
};
export function ProjectWorkspace({
  projects,
  projectId,
  select,
  flows,
  agents,
  providers,
  queues,
  refresh,
  notice,
  newFlow,
  openFlow,
  openAgents,
}: {
  projects: Project[];
  projectId: string;
  select: (id: string) => void;
  flows: Flow[];
  agents: FullAgent[];
  providers: Provider[];
  queues: Queue[];
  refresh: () => Promise<unknown>;
  notice: Notice;
  newFlow: () => void;
  openFlow: (id: string) => void;
  openAgents: () => void;
}) {
  const [creating, setCreating] = useState(false);
  const [expanded, setExpanded] = useState('');
  useEffect(() => {
    if (expanded && expanded !== projectId) setExpanded('');
  }, [projectId, expanded]);
  const project = projects.find((p) => p.id === expanded && p.id === projectId);

  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ONE PROJECT. ONE ORCHESTRATOR.</span>
          <h1>Give every request a direction.</h1>
          <p>
            Describe your project, enable intents and agents, and let your orchestrator route the
            conversation.
          </p>
        </div>
        <button className="primary" onClick={() => setCreating(true)}>
          <Plus size={16} />
          New project
        </button>
      </div>
      <div className={`project-layout ${project ? '' : 'list-only'}`}>
        <section className="panel project-list">
          <div className="section-head">
            <h2>
              Projects <span className="count">{projects.length}</span>
            </h2>
          </div>
          {!projects.length && (
            <Empty
              icon={GitBranch}
              title="No projects yet"
              text="Create a project to add its orchestrator, intents, and agents."
            />
          )}
          {projects.map((p) => (
            <button
              key={p.id}
              className={p.id === project?.id ? 'selected' : ''}
              aria-expanded={p.id === project?.id}
              onClick={() => {
                select(p.id);
                setExpanded(project?.id === p.id ? '' : p.id);
              }}
            >
              <span className="bot-icon small-icon">
                <GitBranch size={18} />
              </span>
              <div>
                <strong>{p.name}</strong>
                <small>{p.published_id ? 'Published orchestrator' : 'Draft orchestrator'}</small>
              </div>
            </button>
          ))}
        </section>
        {project ? (
          <ProjectEditor
            key={project.id}
            project={project}
            flows={flows.filter((f) => f.project_id === project.id)}
            agents={agents.filter((a) => a.project_id === project.id)}
            providers={providers}
            queues={queues}
            refresh={refresh}
            notice={notice}
            newFlow={newFlow}
            openFlow={openFlow}
            openAgents={openAgents}
          />
        ) : null}
      </div>
      {creating && (
        <Modal title="Create a project" close={() => setCreating(false)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              try {
                const description = String(f.get('description'));
                await post<Project>('/projects', {
                  name: f.get('name'),
                  description,
                  orchestrator: { ...emptyOrchestrator, description },
                });
                await refresh();
                setExpanded('');
                setCreating(false);
                notice('Project created. Add intents or agents, then configure its orchestrator.');
              } catch (err) {
                notice((err as Error).message, true);
              }
            }}
          >
            <Field label="Project name">
              <input name="name" required maxLength={120} />
            </Field>
            <Field label="Description">
              <textarea
                name="description"
                rows={3}
                maxLength={5000}
                placeholder="What does this project cover?"
              />
            </Field>
            <button className="primary wide">Create project</button>
          </form>
        </Modal>
      )}
    </>
  );
}
function ProjectEditor({
  project,
  flows,
  agents,
  providers,
  queues,
  refresh,
  notice,
  newFlow,
  openFlow,
  openAgents,
}: {
  project: Project;
  flows: Flow[];
  agents: FullAgent[];
  providers: Provider[];
  queues: Queue[];
  refresh: () => Promise<unknown>;
  notice: Notice;
  newFlow: () => void;
  openFlow: (id: string) => void;
  openAgents: () => void;
}) {
  const [draft, setDraft] = useState({
    ...project,
    orchestrator: { ...emptyOrchestrator, ...project.orchestrator },
  });
  const [busy, setBusy] = useState(false);
  const [test, setTest] = useState<TestSession>();
  const cfg = draft.orchestrator;
  const set = (key: keyof Orchestrator, value: unknown) =>
    setDraft((d) => ({ ...d, orchestrator: { ...d.orchestrator, [key]: value } }));
  const toggle = (key: 'flow_ids' | 'agent_ids', id: string) =>
    set(key, cfg[key].includes(id) ? cfg[key].filter((x) => x !== id) : [...cfg[key], id]);
  async function action(kind: 'save' | 'publish' | 'test') {
    setBusy(true);
    try {
      await put(`/projects/${project.id}`, {
        name: draft.name,
        description: draft.description,
        purpose: draft.purpose,
        origins: draft.origins,
        orchestrator: cfg,
      });
      if (kind === 'publish') await post(`/projects/${project.id}/publish`);
      if (kind === 'test') setTest(await post(`/projects/${project.id}/test`));
      await refresh();
      notice(
        kind === 'publish'
          ? 'Orchestrator and target versions published'
          : kind === 'test'
            ? 'Test session started'
            : 'Project saved',
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
        label="Project configuration"
        title={
          <>
            {project.name}{' '}
            <Badge tone={project.published_id ? 'green' : ''}>
              {project.published_id ? 'Published' : 'Draft'}
            </Badge>
          </>
        }
        description={
          'New sessions use the published routing catalog. Existing sessions keep their versions.'
        }
        actions={
          <div className="toolbar-actions">
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
          <Field label="Project name">
            <input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              maxLength={120}
            />
          </Field>
          <Field label="Project description">
            <textarea
              rows={3}
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              maxLength={5000}
            />
          </Field>
        </div>
      </ConfigSection>
      <ConfigSection
        label="Orchestrator configuration"
        title={
          <>
            <GitBranch size={18} /> Orchestrator
          </>
        }
        description={
          'Choose an intent, delegate to an agent, ask for clarification, or hand off to a person.'
        }
        actions={<Badge tone="green">Project router</Badge>}
      >
        <div className="editor-fields">
          <div className="form-row">
            <Field label="Orchestrator description">
              <textarea
                rows={3}
                value={cfg.description}
                onChange={(e) => set('description', e.target.value)}
                maxLength={5000}
                placeholder="Describe the requests this router handles"
              />
            </Field>
            <Field label="Orchestrator purpose">
              <textarea
                rows={3}
                value={cfg.purpose}
                onChange={(e) => set('purpose', e.target.value)}
                maxLength={5000}
                placeholder="Explain how it should choose between targets"
              />
            </Field>
          </div>
          <div className="form-row">
            <Field label="Routing model">
              <select
                value={cfg.provider_id || ''}
                onChange={(e) => set('provider_id', e.target.value || null)}
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
            <Field label="Human fallback queue">
              <select
                value={cfg.fallback_queue_id || ''}
                onChange={(e) => set('fallback_queue_id', e.target.value || null)}
              >
                <option value="">Unassigned queue</option>
                {queues.map((q) => (
                  <option key={q.id} value={q.id}>
                    {q.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field
            label="Routing instructions"
            hint="Only enabled targets are routable. Ambiguous requests trigger clarification; routing errors go to the fallback queue."
          >
            <textarea
              rows={4}
              value={cfg.instructions || ''}
              onChange={(e) => set('instructions', e.target.value)}
              maxLength={20000}
            />
          </Field>
          <Field label="Welcome message">
            <input
              value={cfg.welcome || ''}
              onChange={(e) => set('welcome', e.target.value)}
              maxLength={16000}
            />
          </Field>
        </div>
      </ConfigSection>
      <ConfigSection
        label="Intents / flows"
        title={
          <>
            Intents / flows <span className="count">{flows.length}</span>
          </>
        }
        description={
          'An intent is a flow. Its description and purpose tell the orchestrator when to start it.'
        }
        actions={
          <button className="text-button" onClick={newFlow}>
            <Plus size={15} />
            New intent
          </button>
        }
      >
        <div className="target-list">
          {flows.map((f) => (
            <div className="target-row" key={f.id}>
              <input
                aria-label={`Enable intent ${f.name}`}
                type="checkbox"
                disabled={!f.published_id}
                checked={cfg.flow_ids.includes(f.id)}
                onChange={() => toggle('flow_ids', f.id)}
              />
              <Workflow size={19} />
              <div>
                <strong>{f.name}</strong>
                <p>
                  {f.purpose || f.description || 'Add a description and purpose in flow settings.'}
                </p>
              </div>
              <Badge tone={f.published_id ? 'green' : ''}>
                {f.published_id ? 'Published' : 'Publish first'}
              </Badge>
              <button className="text-button" onClick={() => openFlow(f.id)}>
                Edit
                <ArrowRight size={14} />
              </button>
            </div>
          ))}
          {!flows.length && (
            <p className="muted pad">
              Create an intent in Flow studio, then publish it to enable routing.
            </p>
          )}
        </div>
      </ConfigSection>
      <ConfigSection
        label="Full agents"
        title={
          <>
            Full agents <span className="count">{agents.length}</span>
          </>
        }
        description={'Independent agents with instructions, knowledge, and shared tools.'}
        actions={
          <button className="text-button" onClick={openAgents}>
            Agent builder
            <ArrowRight size={15} />
          </button>
        }
      >
        <div className="target-list">
          {agents.map((a) => (
            <div className="target-row" key={a.id}>
              <input
                aria-label={`Enable agent ${a.name}`}
                type="checkbox"
                disabled={!a.published_id}
                checked={cfg.agent_ids.includes(a.id)}
                onChange={() => toggle('agent_ids', a.id)}
              />
              <Bot size={19} />
              <div>
                <strong>{a.name}</strong>
                <p>{a.purpose || a.description}</p>
              </div>
              <Badge tone={a.published_id ? 'green' : ''}>
                {a.published_id ? 'Published' : 'Publish first'}
              </Badge>
            </div>
          ))}
          {!agents.length && (
            <p className="muted pad">
              Build and publish an agent before adding it to the orchestrator.
            </p>
          )}
        </div>
      </ConfigSection>
      <ConfigSection
        label="Project widget"
        title={
          <>
            <Code2 size={17} /> Project widget
          </>
        }
        description={'Publish the orchestrator and embed one entry point for all intents.'}
      >
        <pre className="code-block embed-code">{`<script src="${location.origin}/widget/open-ccai.js"\n  data-api="${location.origin}"\n  data-project="${project.id}" defer></script>`}</pre>
      </ConfigSection>
      {test && (
        <ConversationTest
          session={test}
          title="Test project routing"
          close={() => setTest(undefined)}
          notice={notice}
        />
      )}
    </div>
  );
}
