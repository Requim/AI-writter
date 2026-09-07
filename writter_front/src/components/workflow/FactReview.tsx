import { Alert, Button, Input, Popconfirm } from 'antd'
import { useState } from 'react'
import type { InterruptInfo } from '@/types/novel'
import { asRecord, asText, asTextList, proposalPayload } from './valueHelpers'

interface Props { interrupt: InterruptInfo; onResume: (value: unknown) => void }

export function FactReview({ interrupt, onResume }: Props) {
  const [instruction, setInstruction] = useState('')
  const report = asRecord(interrupt.fact_report) || asRecord(proposalPayload(interrupt)?.report)
  const blocked = report?.status === 'blocked'
  const proposalId = interrupt.proposal?.proposal_id || interrupt.proposal_id
  const findings = Array.isArray(report?.findings) ? report.findings : []
  const artifact = asText(interrupt.artifact_content)
  const canAccept = !blocked && !!proposalId && !!report && !!artifact
  const send = (decision: string) => onResume({ proposal_id: proposalId, decision,
    ...(decision === 'revise' ? { instruction: instruction.trim() } : {}) })
  return <section className="interrupt-block fact-review">
    <h3>{report?.artifact_kind === 'outline' ? '章节细纲事实核对' : '正文事实核对'}</h3>
    <Alert showIcon type={blocked ? 'error' : 'warning'} title={blocked ? '存在明确事实冲突，尚未归档' : '事实证据尚未完整确认'} />
    {asTextList(report?.reasons).map((reason, index) => <p key={index}>{reason}</p>)}
    {findings.map((raw, index) => {
      const finding = asRecord(raw)
      const expected = asRecord(finding?.expected_evidence)
      const actual = asRecord(finding?.actual_evidence)
      return <div className="fact-evidence" key={index} style={{ borderBottom: '1px solid #d9d9d9', padding: '12px 0', overflowWrap: 'anywhere' }}>
        <strong>{asText(finding?.message) || '待核对的事实陈述'}</strong>
        {expected && <p>已确认依据：{asText(expected.quote)}（版本 {String(finding?.fact_version || '未知')}）</p>}
        <p>稿件原文：{asText(actual?.quote) || '未获得有效引用'}</p>
      </div>
    })}
    {artifact && <details className="fact-artifact">
      <summary>待核对稿件</summary>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 360, overflowY: 'auto', fontFamily: 'inherit' }}>{artifact}</pre>
    </details>}
    <div className="interrupt-actions">
      <Popconfirm title="确认已人工核对这些未确认事实？" description="本次决定仅适用于当前稿件及事实版本，不会把未知结果改为自动通过。"
        okText="已核对，继续" cancelText="返回核对" disabled={!canAccept} onConfirm={() => send('accept')}>
        <Button type="primary" disabled={!canAccept}>人工核对后继续</Button>
      </Popconfirm>
      <Button disabled={!proposalId} onClick={() => send('regenerate')}>重新生成</Button>
      <Button disabled={!proposalId} onClick={() => send('recheck')}>重新核对事实</Button>
    </div>
    <div className="review-instruction">
      <Input.TextArea aria-label="事实修订要求" value={instruction} onChange={event => setInstruction(event.target.value)}
        placeholder="填写需要修正的事实及依据" autoSize={{ minRows: 2, maxRows: 5 }} />
      <Button disabled={!proposalId || !instruction.trim()} onClick={() => send('revise')}>按依据修订</Button>
    </div>
  </section>
}
