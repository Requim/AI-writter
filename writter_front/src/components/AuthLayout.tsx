import type { PropsWithChildren } from 'react'
import { BookOutlined } from '@ant-design/icons'

export function AuthLayout({ children }: PropsWithChildren) {
  return (
    <main className="auth-page">
      <section className="auth-imprint" aria-label="墨间编辑部">
        <div className="auth-brand"><BookOutlined /><span>墨间</span></div>
        <div>
          <span className="eyebrow">Novel Desk · Multi-tenant Edition</span>
          <h1>每一间编辑部，<br />都有自己的书架。</h1>
          <p>稿件、章节记忆与 AI 创作进度严格归属于当前工作区。</p>
        </div>
        <small>MOJIAN EDITORIAL SYSTEM / 2026</small>
      </section>
      <section className="auth-form-panel">{children}</section>
    </main>
  )
}
