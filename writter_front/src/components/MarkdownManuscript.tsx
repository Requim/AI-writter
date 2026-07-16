import { useEffect, useMemo, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface MarkdownManuscriptProps {
  content: string
  live?: boolean
}

function normalizeStreamedMarkdown(content: string): string {
  return content
    .replace(/\*\*[ \t]+([^*\n]*?\S)[ \t]*\*\*/g, '**$1**')
    .replace(/\*\*((?![ \t])[^*\n]*?\S)[ \t]+\*\*/g, '**$1**')
}

export function MarkdownManuscript({ content, live = false }: MarkdownManuscriptProps) {
  const articleRef = useRef<HTMLElement>(null)
  const followTailRef = useRef(true)
  const renderedContent = useMemo(() => normalizeStreamedMarkdown(content), [content])

  useEffect(() => {
    const article = articleRef.current
    if (live && article && followTailRef.current) {
      article.scrollTop = article.scrollHeight
    }
  }, [content, live])

  return (
    <article
      ref={articleRef}
      className="manuscript-renderer"
      data-live={live || undefined}
      aria-busy={live}
      aria-label={live ? '正在生成的章节正文' : '章节正文'}
      onScroll={(event) => {
        const article = event.currentTarget
        followTailRef.current = article.scrollHeight - article.scrollTop - article.clientHeight < 120
      }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer">{children}</a>
          ),
        }}
      >
        {renderedContent}
      </ReactMarkdown>
      {live && <span className="stream-caret" aria-hidden="true" />}
    </article>
  )
}
