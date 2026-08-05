import { Button, Empty, Skeleton } from 'antd'
import { AppShell } from '@/components/AppShell'
import { NovelStudioView } from './novel-studio/NovelStudioView'
import { useNovelStudioController } from './novel-studio/useNovelStudioController'

export default function NovelStudio() {
  const controller = useNovelStudioController()
  if (controller.document.loading) return (
    <AppShell>
      <div className="studio-loading-shell" role="status" aria-live="polite" aria-label="正在载入工作台">
        <header><Skeleton.Input active size="small" /><Skeleton.Button active size="small" /></header>
        <div className="studio-loading-progress"><Skeleton.Input active size="small" block /></div>
        <div className="studio-loading-grid"><Skeleton active /><Skeleton active /><Skeleton active /></div>
      </div>
    </AppShell>
  )
  if (controller.document.loadError || !controller.document.novel) return (
    <AppShell>
      <section className="studio-failure" role="status" aria-live="polite">
        <Empty description={controller.document.loadError === 'forbidden'
          ? '你没有查看这份稿件的权限'
          : controller.document.loadError === 'network' ? '暂时无法连接稿件服务' : '稿件不存在或已被删除'}>
          <Button type="primary" onClick={() => void controller.refresh()}>重新加载</Button>
          <Button onClick={controller.goBack}>返回书架</Button>
        </Empty>
      </section>
    </AppShell>
  )
  return (
    <AppShell onBeforeNavigate={controller.confirmDiscardChanges}>
      <NovelStudioView controller={controller} />
    </AppShell>
  )
}
