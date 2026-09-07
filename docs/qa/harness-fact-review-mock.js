async (page) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  const tenant = { id: 'qa-tenant', name: '本地验收编辑部', slug: 'qa', role: 'owner', status: 'active', ai_enabled: true, monthly_generation_limit: 100, monthly_generation_unlimited: true, novel_planning_v1_enabled: true, novel_planning_v1_effective: true };
  const user = { id: 'qa-user', email: 'qa@example.invalid', is_platform_admin: false, status: 'active' };
  const plan = {
    schema_version: 1, version: 2, source: 'initial', created_at: '2026-09-07T08:00:00Z',
    scale: { target_chapters: 12, target_total_words: 48000, average_chapter_words: 4000, target_volumes: 1, tolerance_ratio: 0.1, lock_window: 3 },
    ending_contract: { final_state: '辛家旧案真相大白，人物关系得到收束' },
    volumes: [{ volume_id: 'vol-1', title: '第一卷 旧宅来信', start_chapter: 1, end_chapter: 12, target_words: 48000, opening_state: '辛远收到旧宅来信', midpoint_turn: '证词出现矛盾', climax: '旧案证据公开', ending_state: '恢复家族名誉', reader_promises: ['完整的线索推理'], setup_ids: [], payoff_ids: [] }],
    arcs: [{ arc_id: 'main', arc_type: 'main', start_chapter: 1, end_chapter: 12, goal: '寻找祠堂旧案真相', escalation_points: [], resolution_condition: '证据闭合', is_core: true }],
    chapter_slots: [],
  };
  const chapter = { id: 'chapter-1', chapter_index: 0, title: '旧宅来信', content: '雨落在旧宅门前。辛远收好来信，朝祖宅走去。祠堂的木门半掩着，门后的脚步声渐渐停下。', word_count: 4000, status: 'completed', version: 1, review_status: 'passed', quality_score: 0.84, updated_at: '2026-09-07T08:00:00Z' };
  const tactical = { status: 'active', assembled_slots: [], window: { schema_version: 1, version: 3, novel_plan_version: 2, story_state_revision: 1, source: 'chapter_refresh', start_chapter: 2, end_chapter: 4, volume_id: 'vol-1', window_objective: '核对祠堂旧案与辛家族谱中的矛盾', created_at: '2026-09-07T08:00:00Z', beats: [{ chapter_number: 2, slot_ref: 'ch2', tactical_goal: '找到族谱缺页的去向', approach: '询问守祠人并核对旧信', bridge_from_previous: '承接旧宅来信', pressure_escalation: '关键证人突然失踪', exit_hook: '桌上留下带血的拓片', pacing: '紧凑' }] } };
  const gate = { score: 0.84, decision: 'human_review', fulfillment_review_required: true, plan_fulfillment: { status: 'unknown', notes: '兑现报告不完整，需重新审阅' }, tactical_fulfillment: { status: 'unknown', notes: '未能确认章末悬念' }, issues: [] };
  const report = { artifact_kind: 'body', status: 'blocked', reasons: ['祠堂归属与已确认事实不一致'], findings: [{ message: '祠堂归属冲突', fact_version: 2, expected_evidence: { quote: '辛家祖祠归辛家所有' }, actual_evidence: { quote: '辛家祖祠归陆家所有' } }] };
  const proposal = { proposal_id: 'qa-fact-review', kind: 'fact_review', version: 1, chapter_number: 2, payload: { report } };
  await page.route('**/api/v1/**', async (route) => {
    const path = route.request().url().split('?')[0];
    if (route.request().method() !== 'GET') return route.fulfill({ status: 409, json: { detail: '本地视觉验收不执行写入' } });
    let data;
    if (path.endsWith('/auth/me')) data = { user, tenants: [tenant] };
    else if (path.endsWith('/tenants')) data = [tenant];
    else if (path.endsWith('/usage')) data = { used: 1, limit: 100, remaining: 99, unlimited: true, ai_enabled: true, period_start: '2026-09-01' };
    else if (path.endsWith('/progress')) data = { current_chapter: 1, total_chapters: 12, percentage: 8, status: 'writing' };
    else if (path.endsWith('/chapters')) data = [chapter];
    else if (path.endsWith('/chapters/chapter-1')) data = chapter;
    else if (path.endsWith('/tactical-plan')) data = tactical;
    else if (path.endsWith('/versions')) data = [];
    else if (path.endsWith('/plan')) data = plan;
    else if (path.endsWith('/state')) data = { thread_id: 'qa-novel', status: 'paused', interrupts: [{ action: 'fact_review_required', artifact_content: '辛远来到祖宅门前。辛家祖祠归陆家所有。守祠人递给他一封旧信。', chapter_number: 2, message: '发现明确事实冲突，必须修订后才能继续', proposal_id: proposal.proposal_id, proposal }], state: { current_chapter_index: 1, has_current_chapter_content: true }, next_nodes: ['fact_review_node'] };
    else if (path.endsWith('/qa-novel')) data = { id: 'qa-novel', thread_id: 'qa-novel', novel_type: 'suspense', title: '辛家旧事 · 视觉验收', status: 'writing', summary: '仅用于本地视觉验收的合成小说', total_outline: { total_chapters: 12 }, created_at: '2026-09-07T08:00:00Z' };
    else return route.fulfill({ status: 404, json: { detail: '验收未定义接口' } });
    return route.fulfill({ json: data });
  });
  await page.evaluate(({ tenant, user }) => {
    localStorage.setItem('novel-writer-auth', JSON.stringify({ state: { accessToken: 'qa-not-a-real-token', user, tenants: [tenant], currentTenantId: tenant.id }, version: 0 }));
  }, { tenant, user });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('http://127.0.0.1:5175/novels/qa-novel');
}
