import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { lazy, Suspense } from 'react'
import { PlatformAdminRoute, ProtectedRoute } from '@/components/ProtectedRoute'

const BookShelf = lazy(() => import('@/pages/BookShelf'))
const CreateNovel = lazy(() => import('@/pages/CreateNovel'))
const NovelStudio = lazy(() => import('@/pages/NovelStudio'))
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
        <BrowserRouter>
          <Suspense fallback={<div className="route-loading">正在铺开稿纸...</div>}>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route path="/invite/:token" element={<AcceptInvite />} />
              <Route path="/" element={protect(<BookShelf />)} />
              <Route path="/novels/new" element={protect(<CreateNovel />)} />
              <Route path="/novels/:novelId" element={protect(<NovelStudio />)} />
              <Route path="/settings/members" element={protect(<TenantSettings />)} />
              <Route path="/admin" element={protect(<PlatformAdminRoute><PlatformAdmin /></PlatformAdminRoute>)} />
              <Route path="/novel/new" element={<Navigate to="/novels/new" replace />} />
              <Route path="/novel/:novelId" element={protect(<LegacyStudioRedirect />)} />
              <Route path="/progress/:novelId" element={protect(<LegacyStudioRedirect />)} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}
