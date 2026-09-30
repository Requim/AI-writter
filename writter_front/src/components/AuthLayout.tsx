import type { PropsWithChildren } from 'react'
import { BookOutlined } from '@ant-design/icons'

export function AuthLayout({ children }: PropsWithChildren) {
  return (
    <main className="auth-page">
      <section className="auth-imprint" aria-label="墨间编辑部">
        <div className="auth-brand"><BookOutlined /><span>墨间</span></div>
        <div>
          <span className="eyebrow">墨间 · 作家工作台</span>
          <h1>开始你的下一部作品</h1>
        </div>
        <small>MOJIAN EDITORIAL SYSTEM / 2026</small>
      </section>
      <section className="auth-form-panel">{children}</section>
    </main>
  )
}
