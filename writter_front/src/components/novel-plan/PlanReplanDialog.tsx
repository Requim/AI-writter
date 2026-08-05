import { EditOutlined } from '@ant-design/icons'
import { Button, Input, Modal, Segmented, Tooltip } from 'antd'
import { useState } from 'react'
import type { PlanReplanRequest, PlanReplanScope } from '@/types/novel'

const scopeOptions = [
  { label: '后续章节', value: 'future' },
  { label: '当前卷', value: 'volume' },
  { label: '整书规模', value: 'scale' },
]

interface PlanReplanDialogProps {
  disabledReason?: string
  onSubmit: (request: PlanReplanRequest) => void
}

export function PlanReplanDialog({ disabledReason, onSubmit }: PlanReplanDialogProps) {
  const [open, setOpen] = useState(false)
  const [scope, setScope] = useState<PlanReplanScope>('future')
  const [instruction, setInstruction] = useState('')
  const close = () => { setOpen(false); setScope('future'); setInstruction('') }
  const submit = () => {
    const value = instruction.trim()
    if (!value) return
    onSubmit({ scope, instruction: value })
    close()
  }
  return <>
    <Tooltip title={disabledReason}>
      <span className="plan-replan-trigger">
        <Button aria-label="调整规划" icon={<EditOutlined />} disabled={Boolean(disabledReason)}
          onClick={() => setOpen(true)}>调整规划</Button>
      </span>
    </Tooltip>
    <Modal className="plan-replan-dialog" title="调整整书规划" open={open} onCancel={close}
      onOk={submit} okText="提交调整" cancelText="取消" okButtonProps={{ disabled: !instruction.trim() }}>
      <div className="plan-replan-fields">
        <label><span>调整范围</span><Segmented block value={scope} options={scopeOptions}
          onChange={(value) => setScope(value as PlanReplanScope)} /></label>
        <label><span>修改要求</span><Input.TextArea aria-label="重规划修改要求" value={instruction}
          onChange={(event) => setInstruction(event.target.value)} maxLength={1000} showCount
          autoSize={{ minRows: 4, maxRows: 8 }} placeholder="调整目标与不可改变的内容" /></label>
      </div>
    </Modal>
  </>
}
