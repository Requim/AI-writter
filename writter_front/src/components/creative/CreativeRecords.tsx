import { Descriptions, Empty, Table, Tag } from 'antd'
import type { CreativeRecord } from '@/types/creative'

const statusLabels: Record<string, string> = {
  candidate: '候选', accepted: '已接受', planned: '计划', active: '在场', latent: '潜伏',
  offstage: '离场', exited: '退场', completed: '完成', seeded: '已埋设', reinforced: '已强化',
  partial: '部分兑现', simulated: '模拟评估', isolated: '隔离试稿', received: '已入库',
  model_supported_trial: '模型支持试用', human_supported: '真人复测支持', revoked: '已撤销',
  unknown: '未知', pending: '待处理', available: '已收录', unclassified: '待分类', reviewed: '已复盘',
  feasible: '可行', no_feasible_route: '无可行路线', applied: '已应用', legacy_style: '沿用原风格',
  compiled: '已编译', invalid: '未通过校验', stale_unverified: '旧正文版本反馈', fact_review_required: '待事实核实',
}
const fieldLabels: Record<string, string> = {
  brief: '创作简报', core_premise: '核心设想', core_conflict: '核心冲突', theme_question: '主题问题',
  reader_promise: '阅读承诺', engine: '故事发动机', differentiation: '差异点', name: '姓名', goal: '目标',
  belief: '信念', lack: '缺口', voice: '语言习惯', red_line: '底线', arc_duties: '主线职责',
  narrative_status: '叙事状态', life_status: '生死事实', perceived_life_status: '外界认知',
  knowledge: '人物认知', known: '读者已知', misunderstandings: '读者误解', expectations: '读者期待',
  emotions: '情绪', fatigue: '疲劳', open_promises: '未兑现承诺', paid_promises: '阶段兑现',
  reason: '理由', scores: '模拟评分', market_evidence_status: '市场证据', real_reader_validation: '真人效果验收',
  evidence: '原文依据', instruction: '调整建议', issues: '问题', factor: '实验因素',
  variant_a: 'A 稿', variant_b: 'B 稿', status: '状态', narrative_mode: '叙事承诺',
  character_id: '人物ID', story_entity_id: '事实实体ID', aliases: '历史姓名', secret_ids: '秘密关联',
  description: '内容', due_chapter: '兑现窗口', conceived_at: '实际构思时间', resolution: '收束说明',
  source_url: '来源地址', observed_at: '采集日期', applicable_scope: '适用范围', category: '类别', text: '正文',
  title: '标题', comment: '反馈', reader_id: '读者标识', issue_key: '问题标识', source: '来源',
}
const kindLabels: Record<string, string> = {
  candidate: '选题方案', engine: '故事发动机', selection: '立项决策', pilot: '隔离试稿', evaluation: '方案评估',
  decision: '人物决策', replan: '剧情调整', character: '人物', role_slot: '未来角色', relationship: '人物关系',
  secret: '秘密', foreshadow: '伏笔', reader_state: '读者状态', engine_review: '故事复盘',
  style_application: '审美应用', feedback: '反馈', hypothesis: '修改假设', experiment: '对照实验', adoption: '采用记录', source: '资料',
}
const sourceLabels: Record<string, string> = {
  model: '模型', human_reader: '真人读者', author: '作者', system: '规则', research: '检索',
}

function valueText(value: unknown): string {
  if (value == null) return '未记录'
  if (typeof value === 'string') return statusLabels[value] || ({ stable: '稳定主角', ensemble_relay: '群像接力', not_performed: '尚未进行' }[value] ?? value)
  if (typeof value !== 'object') return String(value)
  return JSON.stringify(value, null, 2)
}

export function CreativeRecordDetail({ record }: { record: CreativeRecord }) {
  const fields = Object.entries(record.payload).filter(([key]) => key !== 'evidence')
  return <div className="creative-record-detail">
    <div className="creative-record-provenance">
      <span>{kindLabels[record.kind] || record.kind}</span><span>V{record.version}</span>
      <span>来源：{sourceLabels[record.source] || record.source}</span>
    </div>
    <Descriptions column={1} size="small" items={fields.map(([key, value]) => ({
      key, label: fieldLabels[key] || key,
      children: <div className={key === 'variant_a' || key === 'variant_b' ? 'creative-manuscript' : 'creative-value'}>{valueText(value)}</div>,
    }))} />
    {record.evidence?.map((evidence, index) => <blockquote key={`${evidence.chapter_id}:${evidence.start}:${index}`}>
      <small>第 {evidence.chapter_number} 章 · V{evidence.chapter_version} · 字符 {evidence.start}-{evidence.end}</small>
      <p>{evidence.quote}</p>
    </blockquote>)}
  </div>
}

export function CreativeRecords({ records }: { records: CreativeRecord[] }) {
  if (!records.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无归档成果" />
  return <Table className="creative-records" size="small" rowKey="id" tableLayout="fixed" pagination={{ pageSize: 8, hideOnSinglePage: true }} dataSource={[...records].reverse()}
    expandable={{ expandedRowRender: (record) => <CreativeRecordDetail record={record} /> }}
    columns={[
      { title: '创作成果', key: 'title', render: (_, record) => <span className="creative-record-title">{valueText(record.payload.name ?? record.payload.title ?? record.payload.issue_key ?? record.payload.description ?? record.key)}</span> },
      { title: '类别', dataIndex: 'kind', width: 100, responsive: ['sm'], render: (value: string) => kindLabels[value] || value },
      { title: '版本', dataIndex: 'version', width: 70, responsive: ['md'], render: (value) => `V${value}` },
      { title: '状态', dataIndex: 'status', width: 130, render: (value: string) => <Tag color={value === 'human_supported' ? 'green' : value === 'model_supported_trial' ? 'gold' : undefined}>{statusLabels[value] || value}</Tag> },
      { title: '来源', dataIndex: 'source', width: 90, responsive: ['md'], render: (value: string) => sourceLabels[value] || value },
    ]} />
}
