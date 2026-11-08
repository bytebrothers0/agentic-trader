// Client-side test: emulates an external tool that connects with ITS OWN
// opencode API key + its own model id. Nothing else configured on the proxy.
const BASE = 'http://localhost:8080/v1';
const CLIENT_KEY = 'oc_sk_027dd67fc523_pHZptYjN2WVN5KPeCp3vnGE6bmaokJeg'; // the tool's own key
const headers = {
  'Content-Type': 'application/json',
  Authorization: `Bearer ${CLIENT_KEY}`,
};

// 1) models — client key unlocks the live catalog
const models = await (await fetch(`${BASE}/models`, { headers })).json();
console.log(`1) /models -> ${models.data.length} models, sample: ${models.data.slice(0, 5).map((m) => m.id).join(', ')}`);

// 2) non-stream chat, client picks the model
const t0 = Date.now();
const chat = await (await fetch(`${BASE}/chat/completions`, {
  method: 'POST', headers,
  body: JSON.stringify({
    model: 'deepseek-v4.1-flash-free',
    stream: false,
    messages: [{ role: 'user', content: 'Reply with exactly two words: client works' }],
  }),
})).json();
console.log(`2) chat (${chat.model}) -> "${chat.choices[0].message.content}" | ${chat.usage.total_tokens} tok | ${Date.now() - t0}ms | finish=${chat.choices[0].finish_reason}`);

// 3) different model id — proves the CLIENT controls model selection
const t1 = Date.now();
const chat2 = await (await fetch(`${BASE}/chat/completions`, {
  method: 'POST', headers,
  body: JSON.stringify({
    model: 'glm-5.3-flash-free',
    stream: false,
    messages: [{ role: 'user', content: 'Reply with exactly: glm here' }],
  }),
})).json();
console.log(`3) chat (${chat2.model}) -> "${chat2.choices[0].message.content}" | ${Date.now() - t1}ms`);

// 4) streaming with the client key — count SSE frames
const t2 = Date.now();
const s = await fetch(`${BASE}/chat/completions`, {
  method: 'POST', headers,
  body: JSON.stringify({
    model: 'deepseek-v4.1-flash-free',
    stream: true,
    messages: [{ role: 'user', content: 'Say exactly: stream ok' }],
  }),
});
const reader = s.body.getReader();
const dec = new TextDecoder();
let chunks = 0, text = '', done_ = false;
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  for (const line of dec.decode(value).split('\n')) {
    if (!line.startsWith('data: ')) continue;
    const p = line.slice(6);
    if (p === '[DONE]') { done_ = true; continue; }
    try {
      const j = JSON.parse(p);
      const c = j.choices?.[0]?.delta?.content;
      if (c) { chunks++; text += c; }
    } catch { /* non-chat frame */ }
  }
}
console.log(`4) stream -> "${text}" in ${chunks} content frames | [DONE] received: ${done_} | ${Date.now() - t2}ms`);

// 5) negative: a WRONG key (not oc_sk_ format... use a fake oc_sk_) -> gateway verdict passes through
const bad = await fetch(`${BASE}/chat/completions`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', Authorization: 'Bearer oc_sk_fake_client_deadbeef' },
  body: JSON.stringify({ model: 'deepseek-v4.1-flash-free', messages: [{ role: 'user', content: 'hi' }] }),
});
console.log(`5) bad key -> HTTP ${bad.status}: ${JSON.stringify(await bad.json()).slice(0, 140)}...`);
