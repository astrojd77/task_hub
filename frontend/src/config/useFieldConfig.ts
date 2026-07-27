import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AppConfig, FieldConfig } from '../api/types'

/**
 * The configured fields, for the review screens.
 *
 * Refetched whenever `revision` changes so saving on the Config tab is
 * reflected in review without a reload.
 */
export function useFieldConfig(revision: number) {
  const [config, setConfig] = useState<AppConfig | null>(null)

  useEffect(() => {
    api
      .config()
      .then(setConfig)
      .catch(() => setConfig(null))
  }, [revision])

  const custom: FieldConfig[] = (config?.fields ?? []).filter(
    (f) => f.kind === 'custom' && f.enabled,
  )

  return { config, customFields: custom }
}
