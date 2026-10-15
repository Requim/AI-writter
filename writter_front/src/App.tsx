import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import {
  createBrowserRouter,
  Navigate,
  Outlet,
  RouterProvider,
  useParams,
} from 'react-router'
import { lazy, Suspense } from 'react'
import { PlatformAdminRoute, ProtectedRoute } from '@/components/ProtectedRoute'
import BookShelf from '@/pages/BookShelf'
import CreateNovel from '@/pages/CreateNovel'
import NovelStudio from '@/pages/NovelStudio'
import { conversationWorkbenchEnabled } from '@/pages/workbench/routeMode'
import { workbenchTheme } from '@/theme'

const Login = lazy(() => import('@/pages/Login'))
const Register = lazy(() => import('@/pages/Register'))
const AcceptInvite = lazy(() => import('@/pages/AcceptInvite'))
const TenantSettings = lazy(() => import('@/pages/TenantSettings'))
const PlatformAdmin = lazy(() => import('@/pages/PlatformAdmin'))
const ResearchConsole = lazy(() => import('@/pages/ResearchConsole'))
const SimpleCreateNovel = lazy(() => import('@/pages/SimpleCreateNovel'))
const ConversationWorkbench = lazy(() => import('@/pages/workbench/ConversationWorkbench'))
const useConversationWorkbench = conversationWorkbenchEnabled(import.meta.env.VITE_CONVERSATION_WORKBENCH)

function LegacyStudioRedirect() {
  const { novelId } = useParams<{ novelId: string }>()
  return <Navigate to={`/novels/${novelId}`} replace />
}

const protect = (element: React.ReactNode) => <ProtectedRoute>{element}</ProtectedRoute>

const router = createBrowserRouter([{
  element: (
    <Suspense fallback={<div className="route-loading" role="status" aria-live="polite">正在加载工作台...</div>}>
      <Outlet />
    </Suspense>
  ),
  children: [
    { path: '/login', element: <Login /> },
    { path: '/register', element: <Register /> },
    { path: '/invite/:token', element: <AcceptInvite /> },
    { path: '/', element: protect(<BookShelf />) },
    { path: '/novels/new', element: protect(<SimpleCreateNovel />) },
    { path: '/novels/new/advanced', element: protect(<CreateNovel />) },
    { path: '/novels/:novelId', element: protect(useConversationWorkbench ? <ConversationWorkbench /> : <NovelStudio />) },
    { path: '/novels/:novelId/studio', element: protect(<NovelStudio />) },
    { path: '/settings/members', element: protect(<TenantSettings />) },
    { path: '/research-workbench', element: protect(<ResearchConsole />) },
    { path: '/admin', element: protect(<PlatformAdminRoute><PlatformAdmin /></PlatformAdminRoute>) },
    { path: '/novel/new', element: <Navigate to="/novels/new" replace /> },
    { path: '/novel/:novelId', element: protect(<LegacyStudioRedirect />) },
    { path: '/progress/:novelId', element: protect(<LegacyStudioRedirect />) },
    { path: '*', element: <Navigate to="/" replace /> },
  ],
}])

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={workbenchTheme}
    >
      <AntApp>
        <RouterProvider router={router} />
      </AntApp>
    </ConfigProvider>
  )
}
