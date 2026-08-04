import type { GenreProfile } from '@/types/novel'
import type { CreationForm } from './creationSubmission'

const DEFAULT_PACE = 'balanced'

function firstValue(items: Array<{ value: string }>): string | undefined {
  return items[0]?.value
}

function paceValue(profile: GenreProfile): string | undefined {
  return profile.pace_options.find((item) => item.value === DEFAULT_PACE)?.value
    || firstValue(profile.pace_options)
}

export function genreDefaults(profile?: GenreProfile): Partial<CreationForm> {
  if (!profile) return {}
  return {
    novel_type: profile.value,
    subgenre: firstValue(profile.subgenres),
    reader_experience: firstValue(profile.reader_experiences),
    narrative_pace: paceValue(profile),
  }
}

export function selectedGenreProfile(
  profiles: GenreProfile[],
  value?: string,
): GenreProfile | undefined {
  return profiles.find((profile) => profile.value === value) || profiles[0]
}
