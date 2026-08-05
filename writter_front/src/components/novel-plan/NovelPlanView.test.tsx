import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { NovelPlan } from '@/types/novel'
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
})
