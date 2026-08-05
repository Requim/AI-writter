import { useEffect, useState } from 'react'
import { novelApi } from '@/api/novel'
import type { PlanningOptions } from '@/types/novel'

let cachedOptions: PlanningOptions | undefined
let pendingOptions: Promise<PlanningOptions> | undefined

function fetchPlanningOptions(): Promise<PlanningOptions> {
  if (cachedOptions) return Promise.resolve(cachedOptions)
  if (!pendingOptions) {
    pendingOptions = novelApi.planningOptions()
      .then((options) => {
        cachedOptions = options
        return options
      })
      .finally(() => { pendingOptions = undefined })
  }
  return pendingOptions
}

export function usePlanningOptions() {
  const [options, setOptions] = useState<PlanningOptions | undefined>(cachedOptions)
  const [loading, setLoading] = useState(!cachedOptions)
  const [error, setError] = useState(false)

  useEffect(() => {
    let active = true
    fetchPlanningOptions()
      .then((value) => { if (active) setOptions(value) })
      .catch(() => { if (active) setError(true) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  return { options, loading, error }
}
