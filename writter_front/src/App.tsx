import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import BookShelf from '@/pages/BookShelf'
import NovelConfig from '@/pages/NovelConfig'
import NovelProgress from '@/pages/NovelProgress'
import Login from '@/pages/Login'
import { useNovelStore } from '@/stores/novelStore'

function App() {
  const { currentNovelId } = useNovelStore()

  return (
    <ConfigProvider locale={zhCN}>
      <AntApp>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<BookShelf />} />
            <Route path="/novel/:novelId" element={<NovelConfig />} />
            <Route path="/progress/:novelId" element={<NovelProgress />} />
            <Route path="/login" element={<Login />} />
          </Routes>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  )
}

export default App
