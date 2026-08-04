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
      proposal_id: 'proposal-characters', decision: 'modify',
      value: { name_selections: { 'lead-m': 'm-2' }, custom_names: { 'lead-f': '梁知夏' } },
    })
    fireEvent.change(screen.getByPlaceholderText('输入具体修改要求'), { target: { value: '男主姓名更朴素，避免生僻字' } })
    fireEvent.click(screen.getByRole('button', { name: '按要求修订' }))
    expect(onResume).toHaveBeenLastCalledWith({
      proposal_id: 'proposal-characters', decision: 'regenerate', feedback: '男主姓名更朴素，避免生僻字',
    })
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

describe('WorkflowPanel titles', () => {
  it('shows scored title candidates and submits the selected object', () => {
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
    expect(onResume).toHaveBeenCalledWith({
      proposal_id: 'proposal-title', decision: 'modify', value: expect.objectContaining({ title: '候选书名4' }),
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
    expect(onResume).toHaveBeenCalledWith({ proposal_id: 'reflection-1', decision: 'modify', value: 'retry' })
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
    expect(screen.getByRole('button', { name: /重试第 3 章质量审读/ })).toBeInTheDocument()
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
