# Novel Writer Frontend

React 19 + TypeScript + Vite 的编辑部式小说创作工作台。

```powershell
npm ci
npm run dev
```

质量检查：

```powershell
npm run lint
npm run test
npm run build
```

路由：

- `/login`、`/register`：账号登录与租户注册
- `/`：书架和创作模式设置
- `/novels/new`：新建作品
- `/novels/:novelId`：章节目录、实时稿件和 AI 执行记录
- `/settings/members`：租户成员、邀请和账号安全
- `/admin`：平台租户和账号管理

旧版 `/novel/:id` 与 `/progress/:id` 会重定向到统一工作台。Access/Refresh Token 保存在本地存储，Axios 和 SSE 客户端都会附加当前租户上下文。
