// The headline tag of a Singularity-engine job card (issue #63): name what really ran, not the tier the job was filed
// under. Model "base" loads H3's own pruned FL2VA/Ref2VA, never the Singularity weights (_skin_model() in
// backend/workflows.py), and a tier only matters when it still adds one of its own LoRAs or its own graph
// (skin_loras() there): its speed LoRA (speed_lora "tier"), the People realism LoRA (every tier but Max), or App flow.

export type SkinTagJob = { workflow_variant?: string; mode?: string; skin_options_json?: string | null }

export function skinTierLabel(tier: string): string {
  if (tier === 'skin_balanced') return 'Balanced'
  if (tier === 'skin_max') return 'Max Intelligence'
  if (tier === 'skin_app') return 'App flow'
  return 'God Tier'
}

export function skinJobTag(job: SkinTagJob): string {
  let options: { model?: string; speed_lora?: string; people_strength?: number } = {}
  try { options = JSON.parse(job.skin_options_json || '{}') || {} } catch { options = {} }
  const tier = job.workflow_variant || 'skin_god'
  const speed = options.speed_lora || 'tier'
  const people = options.people_strength ?? 1
  const tierAdds = tier === 'skin_app' || speed === 'tier' || (tier !== 'skin_max' && people > 0)
  if (options.model === 'base') {
    const base = job.mode === 'reference' ? 'H3 Ref2VA' : 'H3'
    return `${base}${speed === 'pika' ? ' + Pika' : ''} (no Singularity)`
  }
  return tierAdds ? `Singularity · ${skinTierLabel(tier)}` : 'Singularity (own LoRAs)'
}
