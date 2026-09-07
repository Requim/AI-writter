import type { WorkflowViewState } from '@/hooks/useWorkflowStream'

export function WorkflowDiagnostics({ state }: { state: WorkflowViewState }) {
  if (!state.activeNode && !state.activeCommandId && !state.reasoning) return null
  return <details className="workflow-diagnostics">
    <summary>技术详情</summary>
    <dl className="review-rows">
      {state.activeNode && <div><dt>内部步骤</dt><dd><code>{state.activeNode}</code></dd></div>}
      {state.activeCommandId && <div><dt>操作编号</dt><dd><code>{state.activeCommandId}</code></dd></div>}
      <div><dt>服务端草稿</dt><dd>{state.hasCheckpointDraft ? '可恢复进度包含草稿' : '尚未确认'}</dd></div>
      {state.reasoning && <div><dt>调度记录</dt><dd>{state.reasoning}</dd></div>}
    </dl>
  </details>
}
