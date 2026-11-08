// Image passthrough test: does the proxy relay image content parts verbatim?
// Sends the same 1x1 PNG three ways and reports the gateway verdict each time.
const BASE = process.env.BASE || 'http://localhost:8080/v1';
const KEY = process.env.CLIENT_KEY;
if (!KEY) { console.error('set CLIENT_KEY'); process.exit(1); }
const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${KEY}` };

// 1x1 transparent PNG, valid base64 (data URI, OpenAI chat format)
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
const dataURI = `data:image/png;base64,${png}`;

const body = {
  model: process.env.MODEL || 'deepseek-v4.1-flash-free',
  stream: false,
  messages: [{
    role: 'user',
    content: [
      { type: 'image_url', image_url: { url: dataURI } },
      { type: 'text', text: 'Describe this image in five words.' },
    ],
  }],
  max_tokens: 200,
};

const t0 = Date.now();
const r = await fetch(`${BASE}/chat/completions`, { method: 'POST', headers, body: JSON.stringify(body) });
const text = await r.text();
console.log(`IMAGE request -> HTTP ${r.status} in ${Date.now() - t0}ms`);
console.log('BODY:', text.slice(0, 600));

// Control: identical request, text-only, same model
const ctrl = await fetch(`${BASE}/chat/completions`, {
  method: 'POST', headers,
  body: JSON.stringify({ model: body.model, stream: false, messages: [{ role: 'user', content: 'Say exactly: control ok' }], max_tokens: 50 }),
});
console.log(`CONTROL (text-only) -> HTTP ${ctrl.status}: ${(await ctrl.text()).slice(0, 300)}`);
