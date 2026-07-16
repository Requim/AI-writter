import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MarkdownManuscript } from './MarkdownManuscript'


describe('MarkdownManuscript', () => {
  it('renders streamed markdown emphasis instead of raw markers', () => {
    const { container, rerender } = render(
      <MarkdownManuscript content="雨停在半小时前。\n\n**沈氏集团核心资产，临时冻结。**" live />,
    )
    expect(screen.getByText('沈氏集团核心资产，临时冻结。').tagName).toBe('STRONG')
    expect(container.textContent).not.toContain('**')

    rerender(<MarkdownManuscript content="雨停在半小时前。\n\n**沈南乔，官方死亡状态。**" live />)
    expect(screen.getByText('沈南乔，官方死亡状态。').tagName).toBe('STRONG')
  })

  it('tolerates whitespace inside emphasis markers from streamed model output', () => {
    const { container } = render(
      <MarkdownManuscript content="**沈氏集团核心资产，临时冻结。 **" live />,
    )

    expect(screen.getByText('沈氏集团核心资产，临时冻结。').tagName).toBe('STRONG')
    expect(container.textContent).not.toContain('**')
  })

  it('does not inject raw html from chapter content', () => {
    const { container } = render(
      <MarkdownManuscript content={'<script>window.hacked = true</script>\n\n正文'} />,
    )
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByText('正文')).toBeInTheDocument()
  })
})
