import { Skeleton } from 'antd'
import { AppShell } from '@/components/AppShell'
import { NovelStudioView } from './novel-studio/NovelStudioView'
import { useNovelStudioController } from './novel-studio/useNovelStudioController'

export default function NovelStudio() {
  const controller = useNovelStudioController()
  if (controller.document.loading) return (
    <AppShell><div className="studio-loading"><Skeleton active /></div></AppShell>
  )
  if (!controller.document.novel) return (
    <AppShell><div className="studio-loading">稿件不存在</div></AppShell>
  )
  return (
    <AppShell onBeforeNavigate={controller.confirmDiscardChanges}>
      <NovelStudioView controller={controller} />
    </AppShell>
  )
}
