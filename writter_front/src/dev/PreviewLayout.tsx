import { Alert } from 'antd'
import { Link, Outlet } from 'react-router'
import { previewNovelId } from './workbenchFixtures'

export function PreviewLayout() {
  return <><div className="preview-notice">
    <Alert type="warning" showIcon banner title="界面预览 · 全部为模拟数据，不连接数据库和模型服务" />
    <nav aria-label="预览页面"><Link to="/">作品管理</Link><Link to="/novels/new">创建作品</Link>
      <Link to={`/novels/${previewNovelId}`}>正文编辑</Link><Link to="/login">登录页</Link></nav>
  </div><Outlet /></>
}
