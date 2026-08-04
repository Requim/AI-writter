import { useCallback, useEffect, useMemo, useState } from 'react'
import { novelApi } from '@/api/novel'
import type { GenreProfile } from '@/types/novel'

export function useGenreTaxonomy() {
  const [profiles, setProfiles] = useState<GenreProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      setProfiles(await novelApi.genreTaxonomy())
    } catch {
      setProfiles([])
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true
    novelApi.genreTaxonomy()
      .then((items) => {
        if (active) setProfiles(items)
      })
      .catch(() => {
        if (active) {
          setProfiles([])
          setError(true)
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [])

  const labels = useMemo(
    () => Object.fromEntries(profiles.map((profile) => [profile.value, profile.label])),
    [profiles],
  )

  return { profiles, labels, loading, error, reload: load }
}
