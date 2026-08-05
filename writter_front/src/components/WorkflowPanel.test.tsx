import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { WorkflowPanel } from './WorkflowPanel'
import type { WorkflowViewState } from '@/hooks/useWorkflowStream'
import type { InterruptInfo } from '@/types/novel'


afterEach(cleanup)

function nameCandidate(id: string, name: string, source: string) {
  return {
    candidate_id: id, name, surname: name[0], given_name: name.slice(1), source_id: `source-${id}`,
    source_title: source, source_quote: '有美一人，清扬婉兮。', meaning: '眉目清朗，品性坦荡。',
    pinyin: 'qīng yáng', role_fit: '与人物克制而坚定的行动方式相合。',
  }
}

function characterDesignInterrupt(): InterruptInfo {
  return {
    action: 'review_or_modify_character_design', proposal_id: 'proposal-characters',
    proposal: { proposal_id: 'proposal-characters', kind: 'character_design', version: 1, payload: {
      naming_policy: { source_scope: ['诗经', '楚辞'] },
      core_roles: [{
        character_id: 'lead-m', role_type: 'male_lead',
        profile: { identity: '县报记者', external_goal: '查清旧案' },
        name_candidates: [nameCandidate('m-1', '江清扬', '《诗经·野有蔓草》'), nameCandidate('m-2', '周既白', '《诗经·烝民》'), nameCandidate('m-3', '许维桢', '《诗经·文王》')],
        recommended_candidate_id: 'm-1',
      }, {
        character_id: 'lead-f', role_type: 'female_lead',
        profile: { identity: '档案管理员', external_goal: '守住母亲留下的秘密' },
        name_candidates: [nameCandidate('f-1', '陶静姝', '《诗经·静女》'), nameCandidate('f-2', '宋攸宁', '《诗经·斯干》'), nameCandidate('f-3', '程令仪', '《诗经·湛露》')],
        recommended_candidate_id: 'f-1',
      }],
      supporting_characters: [{ character_id: 'support-1', name: '闻绍庭', role_type: 'antagonist', profile: {}, name_origin: 'classical' }],
      relationships: [{ from: 'lead-m', to: 'lead-f', relation: '旧识' }],
    } },
  }
}

function renderCharacterReview(onResume: (value: unknown) => void) {
  render(<WorkflowPanel state={{
    status: 'paused', connection: 'idle', draft: '', activeNode: 'character_design_review_node', issues: [], events: [],
    interrupt: characterDesignInterrupt(),
  }} autoMode={false} onResume={onResume} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
}

describe('WorkflowPanel creative brief', () => {
  it('shows the generated creative brief for manual confirmation', () => {
    const onResume = vi.fn()
    const brief = {
      core_premise: '一名记者发现所有失踪者都曾收到同一封信。',
      protagonist_drive: '查清妹妹失踪的真相。',
      core_conflict: '每接近真相一步，妹妹留下的证据就更像伪造。',
      theme_question: '真相是否值得用亲密关系来交换？',
      reader_promise: '持续解谜，并在终局获得情感回响。',
    }
    render(
      <WorkflowPanel
        state={{
          status: 'paused',
          connection: 'idle',
          draft: '',
          activeNode: 'creative_brief_node',
          issues: [],
          events: [],
          interrupt: {
            action: 'review_or_modify_creative_brief',
            message: '创作简报已生成，请确认或修改',
            ai_generated_creative_brief: brief,
          },
        }}
        autoMode={false}
        onResume={onResume}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getAllByText('审阅创作简报').length).toBeGreaterThan(0)
    expect(screen.getByText('一名记者发现所有失踪者都曾收到同一封信。')).toBeInTheDocument()
    expect(screen.getByText('查清妹妹失踪的真相。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确认创作简报' }))
    expect(onResume).toHaveBeenCalledWith(brief)
  })
})

describe('WorkflowPanel character design', () => {
  it('shows verified name context and accepts untouched recommendations', () => {
    const onResume = vi.fn()
    renderCharacterReview(onResume)
    expect(screen.getByText('《诗经·野有蔓草》')).toBeInTheDocument()
    expect(screen.getAllByText('有美一人，清扬婉兮。').length).toBeGreaterThan(0)
    expect(screen.getAllByText('与人物克制而坚定的行动方式相合。').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: '确认角色设计' }))
    expect(onResume).toHaveBeenCalledWith({ proposal_id: 'proposal-characters', decision: 'accept' })
  })

  it('submits changed candidates, custom names, and regeneration feedback', () => {
    const onResume = vi.fn()
    renderCharacterReview(onResume)
    fireEvent.click(screen.getByRole('radio', { name: /周既白/ }))
    fireEvent.change(screen.getByRole('textbox', { name: '女主角自定义姓名' }), { target: { value: '梁知夏' } })
    fireEvent.click(screen.getByRole('button', { name: '确认角色设计' }))
    expect(onResume).toHaveBeenCalledWith({
      proposal_id: 'proposal-characters', decision: 'replace',
      value: { name_selections: { 'lead-m': 'm-2' }, custom_names: { 'lead-f': '梁知夏' } },
    })
    fireEvent.change(screen.getByPlaceholderText('输入具体修改要求'), { target: { value: '男主姓名更朴素，避免生僻字' } })
    fireEvent.click(screen.getByRole('button', { name: '按要求修订' }))
    expect(onResume).toHaveBeenLastCalledWith({
      proposal_id: 'proposal-characters', decision: 'revise', instruction: '男主姓名更朴素，避免生僻字',
    })
  })
})

describe('WorkflowPanel novel plan', () => {
  it('forces a structured plan review in automatic mode and accepts by proposal id', () => {
    const onResume = vi.fn()
    render(<WorkflowPanel state={{
      status: 'paused', connection: 'idle', draft: '', activeNode: 'novel_plan_review_node', issues: [], events: [],
      interrupt: {
        action: 'review_novel_plan', proposal_id: 'plan-1', message: '整书规划已完成，请确认',
        proposal: { proposal_id: 'plan-1', kind: 'novel_plan', version: 1, payload: {
          schema_version: 1, version: 1, source: 'initial', created_at: '2026-08-05T08:00:00Z',
          scale: { preset: 'short', target_chapters: 2, target_total_words: 8400,
            tolerance_ratio: 0.1, average_chapter_words: 4200, target_volumes: 1, lock_window: 5 },
          ending_contract: { final_state: '谜题闭合' },
          volumes: [{ volume_id: 'vol-1', title: '第一卷', start_chapter: 1, end_chapter: 2,
            target_words: 8400, opening_state: '危机出现', midpoint_turn: '线索翻转', climax: '揭晓',
            ending_state: '危机解除', reader_promises: [], setup_ids: [], payoff_ids: [] }],
          arcs: [{ arc_id: 'main', arc_type: 'main', start_chapter: 1, end_chapter: 2,
            goal: '查明真相', escalation_points: [], resolution_condition: '案件解决', is_core: true }],
          chapter_slots: [{ chapter_number: 1, volume_id: 'vol-1', arc_ids: ['main'],
            story_function: '危机进入', must_happen: ['收到来信'], planned_state_delta: '主角接案',
            target_words: 4200, setup_ids: [], payoff_ids: [], detail_level: 'detailed', status: 'planned' },
          { chapter_number: 2, volume_id: 'vol-1', arc_ids: ['main'], story_function: '真相揭晓',
            must_happen: ['找到真凶'], planned_state_delta: '危机解除', target_words: 4200,
            setup_ids: [], payoff_ids: [], detail_level: 'skeleton', status: 'planned' }],
        } },
      },
    }} autoMode onResume={onResume} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getByText('整书规划提案')).toBeInTheDocument()
    expect(screen.getAllByText('8,400 字')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: '确认整书规划' }))
    expect(onResume).toHaveBeenCalledWith({ proposal_id: 'plan-1', decision: 'accept' })
  })
})

describe('WorkflowPanel chapter outline', () => {
  it('shows a chapter outline review instead of the internal router stage', () => {
    const state: WorkflowViewState = {
      status: 'paused',
      connection: 'idle',
      draft: '',
      activeNode: 'chapter_outline_node',
      reasoning: '第1章细纲已生成，请审阅或修改',
      issues: [],
      events: [
        {
          id: 1,
          type: 'status',
          thread_id: 'thread-1',
          node: 'router_agent',
          data: { status: 'completed', next_node: 'chapter_outline_node' },
          timestamp: '2026-07-15T14:00:00Z',
        },
      ],
      interrupt: {
        action: 'review_or_provide_chapter_outline',
        chapter_number: 1,
        message: '第1章细纲已生成，请审阅或修改',
        ai_generated_outline: {
          title: '遗嘱上的血字',
          chapter_goal: '迫使主角接下第一份危险委托',
          key_events: ['收到遗嘱', '发现异常签名', '决定追查'],
        },
      },
    }

    render(
      <WorkflowPanel
        state={state}
        autoMode={false}
        onResume={vi.fn()}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getAllByText('第 1 章细纲待审阅').length).toBeGreaterThan(0)
    expect(screen.getByText('遗嘱上的血字')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '使用细纲，生成正文' })).toBeInTheDocument()
    expect(screen.queryByText('规划下一步')).not.toBeInTheDocument()
    expect(screen.queryByText('router_agent')).not.toBeInTheDocument()
  })
})

describe('WorkflowPanel combined chapter plan', () => {
  it('reviews tactics, hard constraints, coverage, and submits a scoped revision', () => {
    const onResume = vi.fn()
    render(<WorkflowPanel state={{
      status: 'paused', connection: 'idle', draft: '', activeNode: 'chapter_plan_review_node', issues: [], events: [],
      interrupt: {
        action: 'review_or_modify_chapter_plan', chapter_number: 5, proposal_id: 'chapter-plan-5',
        proposal: { proposal_id: 'chapter-plan-5', kind: 'chapter_plan', version: 1, chapter_number: 5,
          payload: {
            tactical_window: { schema_version: 1, version: 6, novel_plan_version: 3,
              story_state_revision: 4, source: 'chapter_refresh', start_chapter: 5, end_chapter: 7,
              volume_id: 'vol-1', window_objective: '验证证词并把压力推向中点', created_at: '2026-08-05T10:00:00Z',
              beats: [{ chapter_number: 5, slot_ref: 'ch5', tactical_goal: '查验证词矛盾',
                approach: '重访现场', bridge_from_previous: '承接匿名电话', pressure_escalation: '证人失踪',
                exit_hook: '发现第二封信', pacing: '紧凑' }] },
            current_slot: { chapter_number: 5, story_function: '中点前加压', must_happen: ['证人失踪'],
              planned_state_delta: '主角转为主动追查', setup_ids: ['letter-2'], payoff_ids: [], target_words: 4200 },
            execution_contract: { plan_version: 3, tactical_version: 6, chapter_number: 5,
              obligation_coverage: { 'ch5:must:1': 2 }, state_delta_coverage: { 'ch5:state_delta': 3 },
              setup_payoff_coverage: { 'ch5:setup:letter-2': 2 } },
            chapter_outline: { title: '失踪证人的房间', chapter_goal: '查明证词为何自相矛盾',
              key_events: ['重访现场', '证人失踪'], estimated_word_count: 4200 },
          } },
      },
    }} autoMode={false} onResume={onResume} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getByText('查验证词矛盾')).toBeInTheDocument()
    expect(screen.getByText('ch5:must:1')).toBeInTheDocument()
    expect(screen.getByText('失踪证人的房间')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: '仅当前章细纲' }))
    fireEvent.change(screen.getByRole('textbox', { name: '章节计划修改要求' }), {
      target: { value: '保留战术目标，强化场景内人物对抗' },
    })
    fireEvent.click(screen.getByRole('button', { name: '按范围重新生成' }))
    expect(onResume).toHaveBeenCalledWith({ proposal_id: 'chapter-plan-5', decision: 'revise',
      scope: 'chapter_outline', instruction: '保留战术目标，强化场景内人物对抗' })
  })
})

describe('WorkflowPanel titles', () => {
  it('keeps a legacy title selection local until explicit confirmation', () => {
    const onResume = vi.fn()
    render(
      <WorkflowPanel
        state={{
          status: 'paused', connection: 'idle', draft: '', activeNode: 'title_node',
          issues: [], events: [],
          interrupt: {
            action: 'confirm_or_provide_title',
            ai_suggestions: [{ title: '死者请于雨夜回信', hint: '一封来信重启旧案', total_score: 35 }],
          },
        }}
        autoMode={false}
        onResume={onResume}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /死者请于雨夜回信/ }))
    expect(onResume).not.toHaveBeenCalled()
    expect(screen.getByText('35 / 40')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确认使用《死者请于雨夜回信》' }))
    expect(onResume).toHaveBeenCalledWith(expect.objectContaining({ title: '死者请于雨夜回信' }))
  })

  it('shows three v3 title candidates first and submits the chosen proposal decision', () => {
    const onResume = vi.fn()
    const candidates = Array.from({ length: 5 }, (_, index) => ({ title: `候选书名${index + 1}`, hint: `故事承诺${index + 1}`, total_score: 50 - index }))
    render(<WorkflowPanel state={{
      status: 'paused', connection: 'idle', draft: '', activeNode: 'title_review_node', issues: [], events: [],
      interrupt: {
        action: 'confirm_or_provide_title', proposal_id: 'proposal-title',
        proposal: { proposal_id: 'proposal-title', kind: 'title', version: 1, payload: candidates },
      },
    }} autoMode={false} onResume={onResume} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getByText('候选书名3')).toBeInTheDocument()
    expect(screen.queryByText('候选书名4')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '展开其余 2 个' }))
    fireEvent.click(screen.getByRole('button', { name: /候选书名4/ }))
    expect(onResume).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '确认使用《候选书名4》' }))
    expect(onResume).toHaveBeenCalledWith({
      proposal_id: 'proposal-title', decision: 'replace', value: expect.objectContaining({ title: '候选书名4' }),
    })
  })
})

describe('WorkflowPanel summary and quality', () => {
  it('separates the reader blurb from the editorial brief', () => {
    render(<WorkflowPanel state={{
      status: 'paused', connection: 'idle', draft: '', activeNode: 'summary_review_node', issues: [], events: [],
      interrupt: {
        action: 'confirm_or_provide_summary', proposal_id: 'proposal-summary',
        proposal: { proposal_id: 'proposal-summary', kind: 'summary', version: 1, payload: {
          reader_blurb: '给读者看的悬念。', editorial_brief: '供总纲推演的完整因果。',
        } },
      },
    }} autoMode={false} onResume={vi.fn()} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getByText('给读者看的悬念。')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '内部简报' }))
    expect(screen.getByText('供总纲推演的完整因果。')).toBeInTheDocument()
  })

  it('labels a legacy single-view summary instead of implying two generated variants', () => {
    render(<WorkflowPanel state={{
      status: 'paused', connection: 'idle', draft: '', issues: [], events: [],
      interrupt: {
        action: 'confirm_or_provide_summary', proposal_id: 'summary-legacy',
        proposal: { proposal_id: 'summary-legacy', kind: 'summary', version: 1,
          payload: { reader_blurb: '旧版简介', legacy_single_view: true } },
      },
    }} autoMode={false} onResume={vi.fn()} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getByRole('note')).toHaveTextContent('旧版创作现场仅保存单一简介')
  })

  it('blocks acceptance when a v3 summary is missing either required view', () => {
    render(<WorkflowPanel state={{
      status: 'paused', connection: 'idle', draft: '', issues: [], events: [],
      interrupt: {
        action: 'confirm_or_provide_summary', proposal_id: 'summary-incomplete',
        proposal: { proposal_id: 'summary-incomplete', kind: 'summary', version: 1,
          payload: { reader_blurb: '只有读者文案' } },
      },
    }} autoMode={false} onResume={vi.fn()} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveTextContent('必须完整且内容不同')
    expect(screen.getByRole('button', { name: '接受并继续' })).toBeDisabled()
  })

  it('treats summaries that differ only in whitespace as the same content', () => {
    render(<WorkflowPanel state={{
      status: 'paused', connection: 'idle', draft: '', issues: [], events: [],
      interrupt: {
        action: 'confirm_or_provide_summary', proposal_id: 'summary-spaces',
        proposal: { proposal_id: 'summary-spaces', kind: 'summary', version: 1,
          payload: { reader_blurb: '雨 夜 来 信', editorial_brief: '雨夜来信' } },
      },
    }} autoMode={false} onResume={vi.fn()} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getByRole('button', { name: '接受并继续' })).toBeDisabled()
  })

  it('keeps the human quality decision visible in automatic mode', () => {
    render(
      <WorkflowPanel
        state={{
          status: 'paused', connection: 'idle', draft: '', activeNode: 'reflection_node',
          issues: [], events: [],
          interrupt: {
            action: 'quality_gate_exhausted',
            chapter_number: 3,
            message: '自动修订已达上限，请人工决定',
          },
        }}
        autoMode
        onResume={vi.fn()}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getAllByText('自动修订已达上限，请人工决定').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '接受当前版本' })).toBeInTheDocument()
  })
})

describe('WorkflowPanel unavailable quality review', () => {
  it('offers bounded recovery actions without mechanical retries', () => {
    const onResume = vi.fn()
    render(<WorkflowPanel state={{
      status: 'paused', connection: 'idle', draft: '草稿', activeNode: 'reflection_review_node', issues: [], events: [],
      interrupt: {
        action: 'quality_review_unavailable', chapter_number: 1, proposal_id: 'reflection-1',
        proposal: { proposal_id: 'reflection-1', kind: 'reflection', version: 1, chapter_number: 1,
          payload: { status: 'unavailable', reason: '模型连续返回非数值评分' } },
      },
    }} autoMode onResume={onResume} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getByText('模型连续返回非数值评分')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新审读' }))
    expect(onResume).toHaveBeenCalledWith({ proposal_id: 'reflection-1', decision: 'revise', instruction: 'retry' })
    expect(screen.getByRole('button', { name: '接受并标记未审读' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重写正文' })).toBeInTheDocument()
  })
})

describe('WorkflowPanel errors', () => {
  it('shows an explicit retry action for recoverable workflow errors', () => {
    render(
      <WorkflowPanel
        state={{
          status: 'error',
          connection: 'idle',
          draft: '第二章草稿',
          activeNode: 'reflection_node',
          checkpointChapterIndex: 2,
          issues: [],
          events: [],
          error: '模型返回的审读结果格式不符合要求，请重试当前步骤',
          errorCode: 'quality_result_invalid',
          errorNode: 'reflection_node',
          retryCount: 1,
          retryable: true,
        }}
        autoMode
        onResume={vi.fn()}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getByText('第 3 章质量审读失败')).toBeInTheDocument()
    expect(screen.getByText('quality_result_invalid')).toBeInTheDocument()
    expect(screen.getByText(/未完成预览已保留.*重试将从本章重新生成/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /同步现场/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重试第 3 章质量审读/ })).toBeInTheDocument()
  })
})

describe('WorkflowPanel summary recovery', () => {
  it('pauses automatic mode and requires a valid two-view repair', () => {
    const onResume = vi.fn()
    render(<WorkflowPanel state={{
      status: 'paused', connection: 'idle', draft: '', activeNode: 'summary_review_node', issues: [], events: [],
      interrupt: {
        action: 'summary_review_required', proposal_id: 'summary-repair',
        message: '简介结构纠正失败，请人工处理',
        proposal: { proposal_id: 'summary-repair', kind: 'summary', version: 2, payload: {
          reader_blurb: '相同内容', editorial_brief: '相同内容', human_review_required: true,
          validation_errors: ['reader_blurb 与 editorial_brief 不能相同'],
        } },
      },
    }} autoMode onResume={onResume} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getAllByText('简介结构纠正失败，请人工处理').length).toBeGreaterThan(0)
    expect(screen.getByText('reader_blurb 与 editorial_brief 不能相同')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '接受并继续' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '提交修复后的简介' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('内部简报'), { target: { value: '用于总纲推演的完整因果' } })
    fireEvent.click(screen.getByRole('button', { name: '提交修复后的简介' }))
    expect(onResume).toHaveBeenCalledWith({
      proposal_id: 'summary-repair', decision: 'replace',
      value: { reader_blurb: '相同内容', editorial_brief: '用于总纲推演的完整因果' },
    })
  })
})

describe('WorkflowPanel connection state', () => {
  it('shows background progress with the last successful sync age', () => {
    const lastSyncedAt = new Date(Date.now() - 5_000).toISOString()
    render(<WorkflowPanel state={{
      status: 'running', connection: 'detached', draft: '', issues: [], events: [],
      activeNode: 'chapter_writer_node', lastSyncedAt, connectionRecovering: false,
    }} autoMode onResume={vi.fn()} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getByText(/后台运行中，最近同步于 \d+ 秒前/)).toBeInTheDocument()
    expect(screen.queryByText(/实时连接已结束/)).not.toBeInTheDocument()
  })

  it('uses recovery wording only after repeated sync failures', () => {
    render(<WorkflowPanel state={{
      status: 'running', connection: 'detached', draft: '', issues: [], events: [],
      activeNode: 'chapter_writer_node', connectionRecovering: true, consecutiveSyncFailures: 2,
    }} autoMode onResume={vi.fn()} onRetry={vi.fn()} onCancel={vi.fn()} onRefresh={vi.fn()} />)
    expect(screen.getByText(/连接恢复中/)).toBeInTheDocument()
    expect(screen.queryByText(/后台运行中/)).not.toBeInTheDocument()
  })
})

describe('WorkflowPanel recovery', () => {
  it('shows preserved draft work as recoverable instead of idle', () => {
    render(
      <WorkflowPanel
        state={{
          status: 'recoverable',
          connection: 'idle',
          draft: '',
          activeNode: 'reflection_node',
          checkpointChapterIndex: 2,
          hasCheckpointDraft: true,
          hasPendingCheckpoint: true,
          issues: [],
          events: [],
        }}
        autoMode
        onResume={vi.fn()}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getByText('可继续')).toBeInTheDocument()
    expect(screen.getByText('第 3 章质量审读可继续')).toBeInTheDocument()
    expect(screen.getByText('草稿已保留，等待继续')).toBeInTheDocument()
    expect(screen.queryByText('尚未开始执行')).not.toBeInTheDocument()
    expect(screen.queryByText('空闲')).not.toBeInTheDocument()
  })
})

describe('WorkflowPanel completed history', () => {
  it('explains that legacy completed work has no retained node history', () => {
    render(
      <WorkflowPanel
        state={{ status: 'completed', connection: 'idle', draft: '', issues: [], events: [] }}
        autoMode={false}
        onResume={vi.fn()}
        onRetry={vi.fn()}
        onCancel={vi.fn()}
        onRefresh={vi.fn()}
      />,
    )

    expect(screen.getByText('执行已完成，节点历史未保留')).toBeInTheDocument()
    expect(screen.queryByText('尚未开始执行')).not.toBeInTheDocument()
  })
})

describe('WorkflowPanel persistence stages', () => {
  it('shows chapter context for summary and story-state persistence nodes', () => {
    const props = {
      autoMode: true, onResume: vi.fn(), onRetry: vi.fn(), onCancel: vi.fn(), onRefresh: vi.fn(),
    }
    const { rerender } = render(<WorkflowPanel {...props} state={{
      status: 'running', connection: 'streaming', draft: '', issues: [], events: [],
      activeNode: 'chapter_summary', currentChapter: 2,
    }} />)
    expect(screen.getByText('本章生成章节摘要')).toBeInTheDocument()
    expect(screen.getByText('正在为已完成章节生成可检索摘要。')).toBeInTheDocument()
    rerender(<WorkflowPanel {...props} state={{
      status: 'running', connection: 'streaming', draft: '', issues: [], events: [],
      activeNode: 'story_state', currentChapter: 2,
    }} />)
    expect(screen.getByText('本章更新故事状态')).toBeInTheDocument()
    expect(screen.getByText('正在更新人物、线索和连续性状态。')).toBeInTheDocument()
  })
})
