document.querySelector('form').addEventListener('submit', (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const endpoint = new URL(String(form.get('api')));
  if (!['https:', 'http:'].includes(endpoint.protocol)) return;
  const script = document.createElement('script');
  script.src = './dist/open-ccai.js';
  script.dataset.api = endpoint.origin;
  script.dataset.bot = String(form.get('bot')).trim();
  document.body.append(script);
  document.querySelector('#result').textContent =
    'Widget loaded. Open the launcher to start a conversation.';
  event.currentTarget.querySelector('button').disabled = true;
});
