import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { NovelPlan, TacticalPlanResponse } from '@/types/novel'
import { NovelPlanView } from './NovelPlanView'

afterEach(cleanup)

function largePlan(): NovelPlan {
  const volumes = Array.from({ length: 8 }, (_, index) => ({
    volume_id: `vol-${index + 1}`, title: `第${index + 1}卷`,
    start_chapter: index * 25 + 1, end_chapter: (index + 1) * 25, target_words: 105_000,
    opening_state: '局势建立', midpoint_turn: '认知反转', climax: '正面冲突', ending_state: '阶段闭合',
    reader_promises: ['持续升级'], setup_ids: [], payoff_ids: [],
  }))
  return {
    schema_version: 1, version: 3, source: 'replan', created_at: '2026-08-05T08:00:00Z',
    scale: {
      preset: 'custom', target_chapters: 200, target_total_words: 840_000,
      tolerance_ratio: 0.1, average_chapter_words: 4200, target_volumes: 8, lock_window: 5,
    },
    ending_contract: { final_state: '主线闭合' }, volumes,
    arcs: [{
      arc_id: 'main', arc_type: 'main', start_chapter: 1, end_chapter: 200,
      goal: '完成主线追索', escalation_points: [{ chapter_number: 100, description: '真相翻转' }],
      resolution_condition: '核心谜题解决', is_core: true,
    }],
    chapter_slots: Array.from({ length: 200 }, (_, index) => ({
      chapter_number: index + 1, volume_id: `vol-${Math.floor(index / 25) + 1}`, arc_ids: ['main'],
      story_function: `推进第 ${index + 1} 章`, must_happen: ['关键事件'], planned_state_delta: '局势变化',
      target_words: 4200, setup_ids: [], payoff_ids: [], detail_level: 'skeleton', status: 'planned',
    })),
  }
}

function tacticalPlan(): TacticalPlanResponse {
  const slot = largePlan().chapter_slots[4]
  return { status: 'active', window: {
    schema_version: 1, version: 6, novel_plan_version: 3, story_state_revision: 4,
    source: 'chapter_refresh', start_chapter: 5, end_chapter: 9, volume_id: 'vol-1',
    window_objective: '逼近第一卷中点并验证关键证词', created_at: '2026-08-05T10:00:00Z',
    beats: [{ chapter_number: 5, slot_ref: 'ch5', tactical_goal: '查验证词矛盾',
      approach: '让主角重访现场', bridge_from_previous: '承接匿名电话', pressure_escalation: '证人失踪',
      exit_hook: '现场留下第二封信', pacing: '紧凑' }],
  }, assembled_slots: [{ tactical: {
    chapter_number: 5, slot_ref: 'ch5', tactical_goal: '查验证词矛盾', approach: '让主角重访现场',
    bridge_from_previous: '承接匿名电话', pressure_escalation: '证人失踪', exit_hook: '现场留下第二封信', pacing: '紧凑',
  }, slot_contract: { chapter_number: 5, volume_id: slot.volume_id, arc_ids: slot.arc_ids,
    story_function: slot.story_function, obligations: [{ id: 'ch5:must:1', event: '关键事件' }],
    planned_state_delta: { id: 'ch5:state_delta', value: slot.planned_state_delta },
    setup_requirements: [], payoff_requirements: [], target_words: slot.target_words,
    detail_level: slot.detail_level, status: slot.status } }] }
}

describe('NovelPlanView', () => {
  it('keeps a 200-chapter plan grouped by volume and exposes the final slot', () => {
    render(<NovelPlanView plan={largePlan()} />)
    expect(screen.getByText('200 章')).toBeInTheDocument()
    expect(screen.getByText('840,000 字')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /章节骨架/ }))
    fireEvent.click(screen.getByRole('button', { name: /第8卷/ }))
    expect(screen.getByText('推进第 200 章')).toBeInTheDocument()
  })

  it('shows a stable empty state before a legacy book receives a plan', () => {
    render(<NovelPlanView />)
    expect(screen.getByText('整书规划尚未建立')).toBeInTheDocument()
  })

  it('shows the current tactical window, hard contracts, and append-only history', () => {
    render(<NovelPlanView plan={largePlan()} tactical={tacticalPlan()} tacticalVersions={[{
      version: 6, novel_plan_version: 3, story_state_revision: 4, start_chapter: 5,
      end_chapter: 9, source: 'chapter_refresh', created_at: '2026-08-05T10:00:00Z',
    }]} />)
    fireEvent.click(screen.getByRole('tab', { name: /近期战术/ }))
    expect(screen.getByText('逼近第一卷中点并验证关键证词')).toBeInTheDocument()
    expect(screen.getByText('查验证词矛盾')).toBeInTheDocument()
    expect(screen.getByText('版本历史')).toBeInTheDocument()
    expect(screen.getByText('4,200 字')).toBeInTheDocument()
  })

  it('does not present a tactical history request failure as an empty history', () => {
    render(<NovelPlanView plan={largePlan()} tactical={tacticalPlan()}
      tacticalVersionsLoadFailed />)
    fireEvent.click(screen.getByRole('tab', { name: /近期战术/ }))
    expect(screen.getByText(/版本历史暂时无法读取/)).toBeInTheDocument()
    expect(screen.queryByText('尚无历史版本')).not.toBeInTheDocument()
  })
})
