// 8 parallel browser-like clients -> wall clock measures the PROXY, not the clients
const url = 'http://localhost:8080/v1/chat/completions';
const t0 = Date.now();
const results = await Promise.allSettled(Array.from({ length: 8 }, (_, i) =>
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer local' },
    body: JSON.stringify({
      model: 'deepseek-v4.1-flash-free',
      stream: false,
      messages: [{ role: 'user', content: `Tool ${i + 1} here: reply with exactly one word: ok${i + 1}` }],
    }),
  }).then(async (r) => {
    const j = await r.json();
    return { tool: i + 1, status: r.status, ms: Date.now() - t0, text: j.choices?.[0]?.message?.content, tokens: j.usage?.total_tokens };
  })
));
for (const r of results) {
  if (r.status === 'fulfilled') console.log(`tool ${r.value.tool}: ${r.value.status} in ${r.value.ms}ms -> "${r.value.text}" (${r.value.tokens} tok)`);
  else console.log('FAILED:', r.reason?.message || r.reason);
}
console.log(`WALL CLOCK (8 concurrent, lean clients): ${Date.now() - t0}ms  (sequential estimate ~8800ms)`);
const stats = await (await fetch('http://localhost:8080/stats')).json();
console.log('stats:', JSON.stringify(stats));
