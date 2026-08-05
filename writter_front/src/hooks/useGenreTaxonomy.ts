import { useCallback, useEffect, useMemo, useState } from 'react'
import { novelApi } from '@/api/novel'
import type { GenreProfile } from '@/types/novel'

let cachedProfiles: GenreProfile[] | undefined
let pendingProfiles: Promise<GenreProfile[]> | undefined

function fetchGenreTaxonomy(): Promise<GenreProfile[]> {
  if (cachedProfiles) return Promise.resolve(cachedProfiles)
  if (!pendingProfiles) {
    pendingProfiles = novelApi.genreTaxonomy()
      .then((profiles) => {
        cachedProfiles = profiles
        return profiles
      })
      .finally(() => { pendingProfiles = undefined })
  }
  return pendingProfiles
}

export function useGenreTaxonomy() {
  const [profiles, setProfiles] = useState<GenreProfile[]>(() => cachedProfiles || [])
  const [loading, setLoading] = useState(() => !cachedProfiles)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      setProfiles(await fetchGenreTaxonomy())
    } catch {
      setProfiles([])
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true
    fetchGenreTaxonomy()
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
