import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    files: [
      'src/api/{novel,workflow}.ts',
      'src/hooks/{useWorkflowStream,workflowState}.ts',
      'src/components/WorkflowPanel.tsx',
      'src/components/AppShell.tsx',
      'src/components/workflow/**/*.{ts,tsx}',
      'src/pages/CreateNovel.tsx',
      'src/pages/creationQuota.ts',
      'src/pages/novelStudioUtils.ts',
      'src/pages/novel-studio/{NovelStudioView.tsx,useNovelStudioController.ts,useAutoRunNotifications.ts}',
      'src/stores/quotaStore.ts',
      'src/workflowReviewPolicy.ts',
    ],
    rules: {
      'max-lines-per-function': ['error', {
        max: 50,
        skipBlankLines: true,
        skipComments: true,
      }],
      'max-depth': ['error', 3],
    },
  },
])
