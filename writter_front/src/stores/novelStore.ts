import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface NovelPreferences {
  autoMode: boolean
  setAutoMode: (enabled: boolean) => void
}

export const useNovelStore = create<NovelPreferences>()(
  persist(
    (set) => ({
      autoMode: false,
      setAutoMode: (autoMode) => set({ autoMode }),
    }),
    { name: 'novel-writer-preferences' },
  ),
)
