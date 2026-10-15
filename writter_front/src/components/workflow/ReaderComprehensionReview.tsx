import type { JsonValue } from '@/types/novel'
import { asRecord, asText } from './valueHelpers'

const labels: Record<string, string> = {
  who: '人物身份', relationship: '眼前关系', goal: '当前目标',
  obstacle: '阻碍与风险', hook: '继续阅读的理由',
}
const statuses: Record<string, string> = {
  clear: '清楚', unclear: '不清楚', not_applicable: '尚未涉及',
}

export function ReaderComprehensionReview({ value, expanded = true }: { value?: JsonValue; expanded?: boolean }) {
  const result = asRecord(value)
  const report = asRecord(result?.report)
  if (!report) return null
  const checks = Array.isArray(report.checks) ? report.checks : []
  const issues = Array.isArray(report.issues) ? report.issues : []
  return <details open={expanded} className="reader-comprehension">
    <summary>读者理解</summary>
    <p>模拟试读 · {result?.status === 'passed' ? '理解验收通过' : '需要修订'}</p>
    {result?.status === 'failed' && <p role="alert">读者理解验收未通过，章节未归档。</p>}
    {checks.map((item, index) => {
      const check = asRecord(item)
      if (!check) return null
      const evidence = Array.isArray(check.evidence) ? check.evidence : []
      return <div key={asText(check.key) || index}>
        <strong>{labels[asText(check.key) || ''] || '理解项'}</strong>
        <span> · {statuses[asText(check.status) || ''] || '待核对'}</span>
        <p>{asText(check.answer)}</p>
        {evidence.map((entry, evidenceIndex) => {
          const quote = asRecord(entry)
          return quote && <blockquote key={evidenceIndex}>
            {asText(quote.quote)}
            {asText(quote.source)?.startsWith('chapter:') && <small>（前文第 {asText(quote.source)?.slice(8)} 章）</small>}
          </blockquote>
        })}
      </div>
    })}
    {issues.map((item, index) => {
      const issue = asRecord(item)
      return issue && <div key={index}>
        <p>{asText(issue.reason)}</p>
        <blockquote>{asText(issue.quote)}</blockquote>
        <p>修订原因与建议：{asText(issue.suggestion)}</p>
      </div>
    })}
  </details>
}
