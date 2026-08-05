import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { initialWorkflowState } from '@/hooks/useWorkflowStream'
import { NovelStudioView } from './NovelStudioView'
import type { NovelStudioController } from './useNovelStudioController'
import type { NovelPlan } from '@/types/novel'

afterEach(cleanup)

function completedController(): NovelStudioController {
  const action = vi.fn()
  return {
    novelId: 'novel-1', autoMode: false, autoRunActive: false, isCompleted: true,
    canDelete: true, hasUnsavedChanges: false, hasRecoverableCheckpoint: false, planningEnabled: true,
    recoveryLabel: '继续创作', confirmDiscardChanges: action,
    document: {
      novel: { id: 'novel-1', novel_type: 'suspense', title: '三章完稿', status: 'completed' },
      progress: { current_chapter: 3, total_chapters: 3, percentage: 100, status: 'completed' },
      chapters: [{
        id: 'chapter-1', chapter_index: 0, title: '未审读章节', word_count: 5200,
        status: 'completed', version: 1, review_status: 'accepted_unreviewed', quality_score: null,
      }, {
        id: 'chapter-2', chapter_index: 1, title: '已审读章节', word_count: 4800,
        status: 'completed', version: 1, review_status: 'passed', quality_score: 0.76,
      }, {
        id: 'chapter-3', chapter_index: 2, title: '历史审读缺失章节', word_count: 4600,
        status: 'completed', version: 1, review_status: 'unknown', quality_score: null,
      }],
      editorTitle: '', editorContent: '', editorMode: 'read', workspaceMode: 'chapter',
      mobilePanel: 'editor', loading: false, saving: false, rewriting: false, tacticalVersions: [],
    },
    workflow: { state: initialWorkflowState, sync: vi.fn() } as unknown as NovelStudioController['workflow'],
    refresh: async () => undefined, openChapter: action, saveChapter: vi.fn(async () => true),
    deleteChapter: action, rewriteChapter: action, startWriting: action, resumeWriting: action,
    continueAutoWriting: action, replanPlan: action, stopWriting: action, setAutoMode: action,
    setEditor: action, goBack: action, notifySyncError: action,
  }
}

function editorController(): NovelStudioController {
  const controller = completedController()
  controller.document.selectedChapter = {
    id: 'chapter-2', chapter_index: 1, title: '已审读章节', content: '章节正文', word_count: 4,
    status: 'completed', version: 1, review_status: 'passed', quality_score: 0.76,
    updated_at: '2026-08-05T09:00:00Z',
  }
  controller.document.editorTitle = '已审读章节'
  controller.document.editorContent = '章节正文'
  controller.document.editorMode = 'edit'
  return controller
}

function studioPlan(): NovelPlan {
  return {
    schema_version: 1, version: 1, source: 'initial', created_at: '2026-08-05T08:00:00Z',
    scale: { preset: 'short', target_chapters: 3, target_total_words: 14_600,
      tolerance_ratio: 0.1, average_chapter_words: 4867, target_volumes: 1, lock_window: 5 },
    ending_contract: { final_state: '主线闭合' },
    volumes: [{ volume_id: 'vol-1', title: '第一卷', start_chapter: 1, end_chapter: 3,
      target_words: 14_600, opening_state: '起局', midpoint_turn: '转折', climax: '高潮', ending_state: '闭合',
      reader_promises: [], setup_ids: [], payoff_ids: [] }],
    arcs: [{ arc_id: 'main', arc_type: 'main', start_chapter: 1, end_chapter: 3,
      goal: '完成追索', escalation_points: [], resolution_condition: '真相揭晓', is_core: true }],
    chapter_slots: [],
  }
}

describe('NovelStudioView completed state', () => {
  it('shows the finished-manuscript action without continue or stop commands at 3/3', () => {
    render(<NovelStudioView controller={completedController()} />)
    expect(screen.getByText('第 3 / 3 章')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /查看完稿/ })).toBeInTheDocument()
    expect(screen.getByText('未审读')).toBeInTheDocument()
    expect(screen.getByText('未审读 1 章')).toBeInTheDocument()
    expect(screen.getByText('生成完成')).toBeInTheDocument()
    expect(screen.getAllByText(/审读记录缺失/)).toHaveLength(2)
    expect(screen.getByText('3.8 / 5')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /继续创作|停止/ })).not.toBeInTheDocument()
  })

  it('shows saved, dirty, saving and retryable failure states in the editor toolbar', () => {
    const controller = editorController()
    const { rerender } = render(<NovelStudioView controller={controller} />)
    expect(screen.getByText('已保存')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '章节操作' })).toBeInTheDocument()

    controller.hasUnsavedChanges = true
    rerender(<NovelStudioView controller={controller} />)
    expect(screen.getByText('有未保存修改')).toBeInTheDocument()

    controller.document.saving = true
    rerender(<NovelStudioView controller={controller} />)
    expect(screen.getByText('保存中')).toBeInTheDocument()

    controller.document.saving = false
    controller.document.saveFailed = true
    rerender(<NovelStudioView controller={controller} />)
    fireEvent.click(screen.getByRole('button', { name: '保存失败，重试' }))
    expect(controller.saveChapter).toHaveBeenCalledOnce()
  })

  it('switches from the directory to the read-only planning workspace', () => {
    const controller = completedController()
    controller.document.plan = studioPlan()
    const { rerender } = render(<NovelStudioView controller={controller} />)
    fireEvent.click(screen.getByRole('radio', { name: '规划' }))
    expect(controller.setEditor).toHaveBeenCalledWith({ workspaceMode: 'plan', mobilePanel: 'plan' })

    controller.document.workspaceMode = 'plan'
    controller.document.mobilePanel = 'plan'
    rerender(<NovelStudioView controller={controller} />)
    expect(screen.getByRole('heading', { name: '整书规划' })).toBeInTheDocument()
    expect(screen.getAllByText('第一卷')).toHaveLength(2)
  })

  it('returns the mobile planning index to chapter mode from the directory tab', () => {
    const controller = completedController()
    controller.document.plan = studioPlan()
    controller.document.workspaceMode = 'plan'
    controller.document.mobilePanel = 'plan'
    render(<NovelStudioView controller={controller} />)

    fireEvent.click(screen.getByRole('tab', { name: /目录/ }))

    expect(controller.setEditor).toHaveBeenCalledWith({
      mobilePanel: 'chapters', workspaceMode: 'chapter',
    })
  })

  it('starts a scoped replan and opens the workflow panel for review', () => {
    const controller = completedController()
    controller.isCompleted = false
    controller.document.novel!.status = 'writing'
    controller.document.plan = studioPlan()
    controller.document.workspaceMode = 'plan'
    controller.document.mobilePanel = 'plan'
    render(<NovelStudioView controller={controller} />)

    fireEvent.click(screen.getByRole('button', { name: '调整规划' }))
    fireEvent.click(screen.getByRole('radio', { name: '当前卷' }))
    fireEvent.change(screen.getByRole('textbox', { name: '重规划修改要求' }), {
      target: { value: '加强第二幕冲突，但保留既定结局' },
    })
    fireEvent.click(screen.getByRole('button', { name: '提交调整' }))

    expect(controller.replanPlan).toHaveBeenCalledWith({
      scope: 'volume', instruction: '加强第二幕冲突，但保留既定结局',
    })
  })

  it('disables replanning without a plan, while busy, and after completion', () => {
    const controller = completedController()
    controller.isCompleted = false
    controller.document.novel!.status = 'writing'
    controller.document.workspaceMode = 'plan'
    controller.document.mobilePanel = 'plan'
    const { rerender } = render(<NovelStudioView controller={controller} />)
    expect(screen.getByRole('button', { name: '调整规划' })).toBeDisabled()

    controller.document.plan = studioPlan()
    controller.workflow.state = { ...initialWorkflowState, status: 'running' }
    rerender(<NovelStudioView controller={controller} />)
    expect(screen.getByRole('button', { name: '调整规划' })).toBeDisabled()

    controller.workflow.state = initialWorkflowState
    controller.isCompleted = true
    rerender(<NovelStudioView controller={controller} />)
    expect(screen.getByRole('button', { name: '调整规划' })).toBeDisabled()
  })

  it('hides all planning workspace entries when the tenant flag is ineffective', () => {
    const controller = completedController()
    controller.planningEnabled = false
    controller.document.plan = studioPlan()
    controller.document.workspaceMode = 'plan'
    controller.document.mobilePanel = 'plan'
    render(<NovelStudioView controller={controller} />)
    expect(screen.queryByRole('radio', { name: '规划' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '规划' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '调整规划' })).not.toBeInTheDocument()
    expect(screen.getByText('稿纸已经铺好').closest('section')).toHaveClass('mobile-active')
  })
})
