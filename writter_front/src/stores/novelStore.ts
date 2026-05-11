import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { novelApi } from '@/api/novel'
import type { NovelResponse, ProgressResponse, ChapterResponse } from '@/api/novel'

interface NovelStore {
  currentNovelId: string | null
  novel: NovelResponse | null
  progress: ProgressResponse | null
  chapters: ChapterResponse[]
  loading: boolean
  autoMode: boolean
  setCurrentNovel: (novelId: string) => void
  setAutoMode: (enabled: boolean) => void
  fetchNovel: (novelId: string) => Promise<void>
  fetchProgress: (novelId: string) => Promise<void>
  fetchChapters: (novelId: string) => Promise<void>
}

export const useNovelStore = create<NovelStore>()(
  persist(
    (set) => ({
  currentNovelId: null,
  novel: null,
  progress: null,
  chapters: [],
  loading: false,
  autoMode: false,

  setCurrentNovel: (novelId: string) => {
    set({ currentNovelId: novelId })
  },

  setAutoMode: (enabled: boolean) => {
    set({ autoMode: enabled })
  },

  fetchNovel: async (novelId: string) => {
    set({ loading: true })
    try {
      // client.ts 响应拦截器已解包 response.data
      const novelData = await novelApi.getNovel(novelId)
      set({ novel: novelData, currentNovelId: novelId })
    } finally {
      set({ loading: false })
    }
  },

  fetchProgress: async (novelId: string) => {
    try {
      const progressData = await novelApi.getProgress(novelId)
      set({ progress: progressData })
    } catch (error) {
      console.error('Failed to fetch progress:', error)
    }
  },

  fetchChapters: async (novelId: string) => {
    try {
      const chaptersData = await novelApi.getChapters(novelId)
      set({ chapters: chaptersData })
    } catch (error) {
      console.error('Failed to fetch chapters:', error)
    }
  },
}),
    {
      name: 'novel-store',
      partialize: (state) => ({ autoMode: state.autoMode }),
    },
  )
)
