import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { initialWorkflowState } from '@/hooks/useWorkflowStream'
import { NovelStudioView } from './NovelStudioView'
import type { NovelStudioController } from './useNovelStudioController'

afterEach(cleanup)

function completedController(): NovelStudioController {
  const action = vi.fn()
  return {
    novelId: 'novel-1', autoMode: false, autoRunActive: false, isCompleted: true,
    canDelete: true, hasUnsavedChanges: false, hasRecoverableCheckpoint: false,
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
      }],
      editorTitle: '', editorContent: '', editorMode: 'read',
      mobilePanel: 'editor', loading: false, saving: false, rewriting: false,
    },
    workflow: { state: initialWorkflowState, sync: vi.fn() } as unknown as NovelStudioController['workflow'],
    refresh: async () => undefined, openChapter: action, saveChapter: async () => true,
    deleteChapter: action, rewriteChapter: action, startWriting: action, resumeWriting: action,
    continueAutoWriting: action, stopWriting: action, setAutoMode: action,
    setEditor: action, goBack: action, notifySyncError: action,
  }
}

describe('NovelStudioView completed state', () => {
  it('shows the finished-manuscript action without continue or stop commands at 3/3', () => {
    render(<NovelStudioView controller={completedController()} />)
    expect(screen.getByText('第 3 / 3 章')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /查看完稿/ })).toBeInTheDocument()
    expect(screen.getByText('未审读')).toBeInTheDocument()
    expect(screen.getByText('未审读 1 章')).toBeInTheDocument()
    expect(screen.getByText('3.8 / 5')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /继续创作|停止/ })).not.toBeInTheDocument()
  })
})
