(async function () {
  const root = document.getElementById('operations');
  const schema = await fetch('/api/v1/openapi.json').then(r => r.json());
  for (const [path, methods] of Object.entries(schema.paths)) {
    for (const [method, op] of Object.entries(methods)) {
      if (!['get','post','put','delete','patch'].includes(method)) continue;
      const detail = document.createElement('details');
      const summary = document.createElement('summary');
      const verb = document.createElement('b'); verb.textContent = method.toUpperCase();
      const name = document.createElement('code'); name.textContent = path;
      const label = document.createElement('span'); label.textContent = op.summary || '';
      summary.append(verb, name, label); detail.append(summary);
      const pre = document.createElement('pre'); pre.textContent = JSON.stringify(op, null, 2);
      detail.append(pre); root.append(detail);
    }
  }
  const types = document.createElement('details');
  const title = document.createElement('summary'); title.textContent = 'Shared request and response schemas';
  const pre = document.createElement('pre'); pre.textContent = JSON.stringify(schema.components || {}, null, 2);
  types.append(title, pre); root.append(types);
})().catch(() => { document.getElementById('operations').textContent = 'Could not load the OpenAPI schema.'; });
