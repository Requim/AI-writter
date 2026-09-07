import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FactLedger } from './FactLedger'
import { apiClient } from '@/api/client'
import { ConfigProvider } from 'antd'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
const fact = { subject_id: 'hero', predicate: 'surname', value_text: '辛', version: 1, status: 'confirmed', valid_from_chapter: 1, evidence: { quote: '族谱记载', source_ref: 'human' } }
function setup() {
  vi.spyOn(apiClient, 'get').mockImplementation(async url => ({ data: String(url).endsWith('/conflicts')
    ? [{ chapter_id: 'chapter-1', chapter_number: 1, title: '旧宅', status: 'legacy_unverified' }]
    : { entities: [{ id: 'hero', name: '辛远', kind: 'character', entity_key: 'hero' }], fact_heads: [fact] } }))
  render(<ConfigProvider theme={{ token: { motion: false } }}><FactLedger novelId="novel-1" /></ConfigProvider>)
  fireEvent.click(screen.getByRole('button', { name: '事实台账与冲突中心' }))
}
describe('作者事实台账', () => {
  it('shows facts and does not mark legacy chapters as passed', async () => {
    setup()
    await screen.findByText('辛远')
    fireEvent.click(screen.getByRole('tab', { name: '冲突与章节记录' }))
    expect(await screen.findByText('历史章节未验证')).toBeInTheDocument()
    expect(screen.queryByText('已核对')).not.toBeInTheDocument()
  })
  it('requires preview confirmation before writing a new version', async () => {
    const post = vi.spyOn(apiClient, 'post').mockImplementation(async url => ({ data: String(url).endsWith('/proposals')
      ? { token: 'signed-proposal', previous: fact, proposal: { fact: { ...fact, evidence: { quote: '已核对原始族谱' } }, expected_version: 1 } }
      : { ...fact, version: 2 } }))
    setup()
    fireEvent.click(await screen.findByRole('button', { name: '纠错' }))
    fireEvent.change(screen.getByLabelText('确认依据或纠错原因'), { target: { value: '已核对原始族谱' } })
    fireEvent.click(screen.getByRole('button', { name: '预览事实变更' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1), { timeout: 5000 })
    // 组件库测试模式复用 test-id；以标题定位所属弹窗，浏览器验收另查可访问名称。
    await waitFor(() => expect(screen.getByText('确认事实变更').closest('[role="dialog"]')).toBeVisible(), { timeout: 5000 })
    expect(post).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: '确认追加版本' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/v1/novels/novel-1/facts/confirm', { token: 'signed-proposal' }))
  }, 30000)
})
