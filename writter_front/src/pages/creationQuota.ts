import { estimatedQuotaCost } from '@/stores/quotaStore'
import type { QuotaUsage } from '@/types/auth'

export interface CreationQuotaDetails {
  state: 'unknown' | 'empty' | 'warning' | 'ready'
  headline: string
  detail: string
}

/** 判断当前额度是否连一次创作命令都无法预留。 */
export function quotaBlocksCreation(quota?: QuotaUsage): boolean {
  return Boolean(quota && (!quota.ai_enabled || (!quota.unlimited && quota.remaining < 1)))
}

/** 生成新建页的额度状态与风险提示。 */
export function quotaNoticeDetails(
  quota?: QuotaUsage,
  chapters?: number,
): CreationQuotaDetails {
  if (!quota) return {
    state: 'unknown', headline: '额度暂时无法读取', detail: '提交时仍会由服务端核验',
  }
  if (quotaBlocksCreation(quota)) return {
    state: 'empty', headline: 'AI 创作不可用', detail: '当前无法启动 AI 创作',
  }
  const estimate = estimatedQuotaCost(chapters)
  const chapterCount = estimate - 1
  if (quota.unlimited) return {
    state: 'ready', headline: '无限额度', detail: `计划生成 ${chapterCount} 章`,
  }
  if (quota.remaining < estimate) return {
    state: 'warning',
    headline: `本月剩余 ${quota.remaining} / ${quota.limit} 次`,
    detail: `仍可启动 1 次，但余额不足以覆盖预计全书（预计 ${estimate} 次，含 ${chapterCount} 章生成）`,
  }
  return {
    state: 'ready',
    headline: `本月剩余 ${quota.remaining} / ${quota.limit} 次`,
    detail: `立即启动 1 次 · 全书预计 ${estimate} 次（含 ${chapterCount} 章生成）`,
  }
}
