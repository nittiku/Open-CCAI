import { test } from 'node:test';
import assert from 'node:assert/strict';
import { eventsUrl } from '../src/url.ts';

test('root origins do not introduce double-slash WebSocket paths', () => {
  assert.equal(
    eventsUrl('http://localhost:5173', 'conversation'),
    'ws://localhost:5173/api/v1/events/conversation',
  );
  assert.equal(
    eventsUrl('https://contact.example/', 'conversation'),
    'wss://contact.example/api/v1/events/conversation',
  );
});
test('optional deployment prefix survives URL conversion', () => {
  assert.equal(
    eventsUrl('https://contact.example/ccai/', 'conversation'),
    'wss://contact.example/ccai/api/v1/events/conversation',
  );
});
