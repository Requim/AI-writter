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

const Login = lazy(() => import('@/pages/Login'))
const Register = lazy(() => import('@/pages/Register'))
const AcceptInvite = lazy(() => import('@/pages/AcceptInvite'))
const TenantSettings = lazy(() => import('@/pages/TenantSettings'))
const PlatformAdmin = lazy(() => import('@/pages/PlatformAdmin'))

function LegacyStudioRedirect() {
  const { novelId } = useParams<{ novelId: string }>()
  return <Navigate to={`/novels/${novelId}`} replace />
}

const protect = (element: React.ReactNode) => <ProtectedRoute>{element}</ProtectedRoute>

const router = createBrowserRouter([{
  element: (
    <Suspense fallback={<div className="route-loading" role="status" aria-live="polite">正在铺开稿纸...</div>}>
      <Outlet />
    </Suspense>
  ),
  children: [
    { path: '/login', element: <Login /> },
    { path: '/register', element: <Register /> },
    { path: '/invite/:token', element: <AcceptInvite /> },
    { path: '/', element: protect(<BookShelf />) },
    { path: '/novels/new', element: protect(<CreateNovel />) },
    { path: '/novels/:novelId', element: protect(<NovelStudio />) },
    { path: '/settings/members', element: protect(<TenantSettings />) },
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
      theme={{ token: {
        colorPrimary: '#8d2f3d', colorInfo: '#176b5b', colorSuccess: '#176b5b',
        colorText: '#292625', colorTextSecondary: '#716b66', colorBorder: '#d8d1c8',
        colorBgContainer: '#fffefa', borderRadius: 6, fontFamily: '"Noto Sans SC", sans-serif',
      } }}
    >
      <AntApp>
        <RouterProvider router={router} />
      </AntApp>
    </ConfigProvider>
  )
}
