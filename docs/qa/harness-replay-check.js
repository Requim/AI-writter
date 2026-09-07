async (page) => {
  await page.reload();
  let posts = 0, replays = 0;
  const event = (id, type) => 'id: ' + id + '\nevent: ' + type + '\ndata: ' + JSON.stringify({ id, type, thread_id: 'qa-novel', data: { message: '合成传输验收' }, timestamp: '2026-09-07T00:00:00Z' }) + '\n\n';
  await page.route('**/workflows/qa-novel/stream', async route => {
    posts += 1;
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body: event(41, 'status') });
  });
  await page.route('**/workflows/qa-novel/events', async route => {
    if (route.request().method() !== 'GET' || route.request().headers()['last-event-id'] !== '41') throw Error('恢复请求不能重新执行命令');
    replays += 1;
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body: event(41, 'status') + event(42, 'completed') });
  });
  const result = await page.evaluate(async () => {
    const { streamWorkflow } = await import('/src/api/workflow.ts');
    const received = [];
    const result = await streamWorkflow('qa-novel', { input: {} }, value => received.push(value.id), undefined, 'qa-only-command');
    return { received, terminal: result.terminal };
  });
  if (posts !== 1 || replays !== 1 || !result.terminal || JSON.stringify(result.received) !== '[41,42]') throw Error('断线重放或去重断言失败: ' + JSON.stringify({ posts, replays, result }));
  console.log({ posts, replays, ...result, provider_calls: 0 });
}
