import React, { useEffect, useMemo, useState } from 'react'
import {
  Archive, Bot, Check, ChevronLeft, Clapperboard, Copy, Download, FileArchive, FolderPlus, ImagePlus,
  Gauge, LoaderCircle, MessageSquare, Pause, Pencil, Play, RefreshCw, RotateCcw, Send, Settings,
  ShieldCheck, Sparkles, Square, Trash2, Upload, UserRound, X,
} from 'lucide-react'
import { AppModal, useAppModal } from './app-modal'

type ModelOption = { id: string; name: string; efforts: string[] }
type Runtime = 'codex' | 'agy'
type AgentSettings = { codex_runtime: Runtime; codex_model: string; codex_effort: string; agy_runtime: Runtime; agy_model: string; agy_effort: string }
type Skill = {
  id: string; name: string; description: string; source: string; managed: boolean;
  enabled: boolean; valid: boolean; error?: string; agents: string[]
}
type Message = {
  id: string; sequence: number; participant: 'user' | 'codex' | 'agy' | 'system';
  recipient: string; kind: string; content: string; metadata?: Record<string, unknown>; created_at: string
}
type Decision = {
  id: string; stage: string; title: string; summary: string; status: string;
  payload?: Record<string, unknown>; resolution?: string; created_at: string
}
type Production = {
  id: string; title: string; pipeline: string; status: string; stage: string;
  participation_mode: string; continuity_mode: string; concept: string; lyrics: string;
  song_name: string; codex_runtime: Runtime; codex_model: string; codex_effort: string; agy_runtime: Runtime; agy_model: string;
  agy_effort: string; skills: string[]; progress: number; error?: string;
  created_at: string; archived?: boolean; messages?: Message[]; decisions?: Decision[]; shots?: Shot[]; artifacts?: Artifact[]; references?: ReferenceMedia[]
}
type ShotAttempt = { id: string; attempt: number; status: string; output_path?: string; frames?: string[]; error?: string }
type Shot = {
  id: string; shot_index: number; title: string; prompt: string;
  mode: 'text'|'opening'|'reference'; continuity: 'hard_cut'|'sequential';
  audio_mode: 'silent'|'lip_sync'; audio_source: 'song'|'reference'; audio_start: number;
  audio_duration?: number; audio_reference_id?: string | null;
  duration: number; megapixels: number; aspect_ratio: string; steps: number; engine: string;
  turbo_profile: string; reference_ids: string[]; status: string; accepted_attempt?: number; attempts: ShotAttempt[]
}
type Artifact = { id: string; kind: string; url: string; metadata?: Record<string, unknown> }
type ReferenceMedia = { id: string; kind: 'image'|'video'|'audio'; name: string; notes: string; url: string }
type RegularJob = { id: string; prompt: string; duration: number; status: string; mode: string; output_url?: string }

const effortLabels: Record<string, string> = { none: 'None', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', ultra: 'Ultra', max: 'Maximum' }
const defaultGates = ['treatment', 'references', 'prompts', 'shots', 'final']

async function jsonResponse(response: Response) {
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || 'Request failed')
  return data
}

function AgentSelect({ label, catalogs, runtime, model, effort, onRuntime, onModel, onEffort, runtimeLocked = false, showRuntime = false }: {
  label: string; catalogs: Record<Runtime, ModelOption[]>; runtime: Runtime; model: string; effort: string;
  onRuntime: (value: Runtime) => void; onModel: (value: string) => void; onEffort: (value: string) => void; runtimeLocked?: boolean; showRuntime?: boolean
}) {
  const models = catalogs[runtime] || []
  const selected = models.find(item => item.id === model)
  const efforts = selected?.efforts?.length ? selected.efforts : ['low', 'medium', 'high']
  return <div className="ps-agent-select">
    <div className="ps-field-title"><Bot size={15} /><span>{label}</span></div>
    {showRuntime && <label><span>Runtime</span><select value={runtime} disabled={runtimeLocked} onChange={event => { const value = event.target.value as Runtime; const first = catalogs[value]?.[0]; onRuntime(value); if (first) { onModel(first.id); onEffort(first.efforts[0] || 'medium') } }}>
      <option value="codex">Codex CLI</option><option value="agy">AGY CLI</option>
    </select></label>}
    <label><span>Model</span><select value={model} onChange={event => { const value = event.target.value; onModel(value); const next = models.find(item => item.id === value); if (next && !next.efforts.includes(effort)) onEffort(next.efforts[0]) }}>
      {!models.some(item => item.id === model) && model && <option value={model}>{model}</option>}
      {models.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label>
    <label><span>Thinking level</span><select value={effort} onChange={event => onEffort(event.target.value)}>
      {!efforts.includes(effort) && <option value={effort}>{effortLabels[effort] || effort}</option>}
      {efforts.map(value => <option key={value} value={value}>{effortLabels[value] || value}</option>)}
    </select></label>
  </div>
}

function ParticipantIcon({ participant }: { participant: Message['participant'] }) {
  if (participant === 'user') return <UserRound size={17} />
  if (participant === 'system') return <Gauge size={17} />
  return participant === 'codex' ? <Bot size={17} /> : <Sparkles size={17} />
}

export function ProductionStudio({ csrf }: { csrf: string }) {
  const appModal = useAppModal()
  const [view, setView] = useState<'room' | 'settings'>('room')
  const [models, setModels] = useState<Record<Runtime, ModelOption[]>>({ codex: [], agy: [] })
  const [modelsFetchedAt, setModelsFetchedAt] = useState('')
  const [modelsRefreshing, setModelsRefreshing] = useState(false)
  const [settings, setSettings] = useState<AgentSettings>({ codex_runtime: 'codex', codex_model: 'gpt-5.6-sol', codex_effort: 'high', agy_runtime: 'agy', agy_model: 'gemini-3.1-pro-high', agy_effort: 'high' })
  const [skills, setSkills] = useState<Skill[]>([])
  const [productions, setProductions] = useState<Production[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [production, setProduction] = useState<Production | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [newProject, setNewProject] = useState(false)
  const [title, setTitle] = useState('')
  const [lyrics, setLyrics] = useState('')
  const [concept, setConcept] = useState('')
  const [song, setSong] = useState<File | null>(null)
  const [referenceFiles, setReferenceFiles] = useState<File[]>([])
  const [participation, setParticipation] = useState<'autonomous' | 'interactive'>('autonomous')
  const [continuity, setContinuity] = useState('hybrid')
  const [codexRuntime, setCodexRuntime] = useState<Runtime>(settings.codex_runtime)
  const [codexModel, setCodexModel] = useState(settings.codex_model)
  const [codexEffort, setCodexEffort] = useState(settings.codex_effort)
  const [agyRuntime, setAgyRuntime] = useState<Runtime>('agy')
  const [agyModel, setAgyModel] = useState(settings.agy_model)
  const [agyEffort, setAgyEffort] = useState(settings.agy_effort)
  const [selectedSkills, setSelectedSkills] = useState<string[]>([])
  const [intervention, setIntervention] = useState('')
  const [recipient, setRecipient] = useState('both')
  const [registerPath, setRegisterPath] = useState('')
  const [editingShot, setEditingShot] = useState<Shot | null>(null)
  const [configOpen, setConfigOpen] = useState(false)
  const [configDraft, setConfigDraft] = useState<Production | null>(null)
  const [importIds, setImportIds] = useState('')
  const [regularJobs, setRegularJobs] = useState<RegularJob[]>([])
  const [referenceName, setReferenceName] = useState('')
  const [referencePrompt, setReferencePrompt] = useState('')
  const [referenceProvider, setReferenceProvider] = useState<'auto'|'codex'|'agy'>('auto')
  const [referenceGenerating, setReferenceGenerating] = useState(false)

  const headers = useMemo(() => ({ 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }), [csrf])

  const loadCatalog = async (refreshModels = false) => {
    const productionTask = Promise.all([
      fetch('/api/productions', { cache: 'no-store' }),
      fetch('/api/jobs', { cache: 'no-store' }),
    ])
    const catalogTask = Promise.all([
      fetch(`/api/agents/models${refreshModels ? '?refresh=true' : ''}`, { cache: 'no-store' }),
      fetch('/api/settings/agents', { cache: 'no-store' }),
      fetch('/api/skills', { cache: 'no-store' }),
    ])
    try {
      const [productionResponse, jobsResponse] = await productionTask
      const [productionData, jobsData] = await Promise.all([jsonResponse(productionResponse), jsonResponse(jobsResponse)])
      setProductions(productionData.productions || [])
      setRegularJobs((jobsData.jobs || []).filter((job: RegularJob) => job.status === 'completed'))
      if (!selectedId && productionData.productions?.length) setSelectedId(productionData.productions[0].id)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load productions')
    }
    try {
      const [modelResponse, settingsResponse, skillResponse] = await catalogTask
      const [modelData, settingsData, skillData] = await Promise.all([
        jsonResponse(modelResponse), jsonResponse(settingsResponse), jsonResponse(skillResponse),
      ])
      setModels({ codex: modelData.codex || [], agy: modelData.agy || [] })
      setModelsFetchedAt(modelData.fetched_at ? new Date(modelData.fetched_at * 1000).toLocaleTimeString() : '')
      setSettings(settingsData)
      setSkills(skillData.skills || [])
      setSelectedSkills(current => current.length ? current : (skillData.skills || []).filter((item: Skill) => item.enabled && item.valid).map((item: Skill) => item.id))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load agent settings')
    } finally {
      setModelsRefreshing(false)
    }
  }

  const refreshModels = async () => {
    setModelsRefreshing(true)
    await loadCatalog(true)
  }

  const loadProduction = async (id = selectedId) => {
    if (!id) { setProduction(null); return }
    try {
      const data = await jsonResponse(await fetch(`/api/productions/${id}`, { cache: 'no-store' }))
      setProduction(data)
      setProductions(current => current.map(item => item.id === data.id ? { ...item, ...data } : item))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to load production')
    }
  }

  useEffect(() => { void loadCatalog(true) }, [])
  useEffect(() => {
    if (view === 'settings') void loadCatalog(true)
  }, [view])
  useEffect(() => {
    if (!selectedId) return
    void loadProduction(selectedId)
    const events = new EventSource(`/api/productions/${selectedId}/events`)
    events.onmessage = () => { void loadProduction(selectedId) }
    const refresh = () => { void loadProduction(selectedId) }
    const eventNames = ['message.created', 'decision.created', 'decision.resolved', 'production.started', 'production.failed', 'production.recovered', 'shots.planned', 'shot.queued', 'shot.progress', 'shot.reviewing']
    eventNames.forEach(name => events.addEventListener(name, refresh))
    const timer = window.setInterval(refresh, 5000)
    return () => { window.clearInterval(timer); events.close() }
  }, [selectedId])
  useEffect(() => {
    setCodexRuntime(settings.codex_runtime || 'codex'); setCodexModel(settings.codex_model); setCodexEffort(settings.codex_effort)
    setAgyRuntime('agy'); setAgyModel(settings.agy_model); setAgyEffort(settings.agy_effort)
  }, [settings])
  useEffect(() => {
    const referenceId = editingShot?.audio_reference_id
    if (!referenceId || editingShot.reference_ids.includes(referenceId)) return
    setEditingShot(current => current && current.audio_reference_id === referenceId && !current.reference_ids.includes(referenceId)
      ? { ...current, reference_ids: [...current.reference_ids, referenceId] }
      : current)
  }, [editingShot?.audio_reference_id])

  const mutate = async (url: string, method = 'POST', body?: BodyInit) => {
    if (!csrf) throw new Error('Session is still connecting')
    const response = await fetch(url, { method, headers: body instanceof FormData ? { 'X-CSRF-Token': csrf } : headers, body })
    return jsonResponse(response)
  }

  const create = async () => {
    setError('')
    if (!title.trim() || !lyrics.trim() || !song) return setError('Title, song file and lyrics are required.')
    setBusy(true)
    try {
      const form = new FormData()
      form.set('title', title.trim()); form.set('lyrics', lyrics.trim()); form.set('song', song)
      referenceFiles.forEach(file => form.append('reference_files', file))
      form.set('concept', concept.trim()); form.set('participation_mode', participation); form.set('continuity_mode', continuity)
      form.set('codex_runtime', 'codex')
      form.set('codex_model', codexModel); form.set('codex_effort', codexEffort)
      form.set('agy_runtime', agyRuntime)
      form.set('agy_model', agyModel); form.set('agy_effort', agyEffort)
      form.set('skills_json', JSON.stringify(selectedSkills)); form.set('approval_gates_json', JSON.stringify(participation === 'interactive' ? defaultGates : ['final']))
      const created = await mutate('/api/productions', 'POST', form)
      setProductions(current => [created, ...current]); setSelectedId(created.id); setProduction(created); setNewProject(false)
      setTitle(''); setLyrics(''); setConcept(''); setSong(null); setReferenceFiles([])
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to create production') }
    finally { setBusy(false) }
  }

  const control = async (action: 'start' | 'pause' | 'resume' | 'stop') => {
    if (!production) return
    setBusy(true); setError('')
    try {
      const body = action === 'stop' ? JSON.stringify({ cancel_generation: true }) : undefined
      const updated = await mutate(`/api/productions/${production.id}/${action}`, 'POST', body)
      setProduction(updated)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Control failed') }
    finally { setBusy(false) }
  }

  const sendIntervention = async () => {
    if (!production || !intervention.trim()) return
    setBusy(true)
    try {
      const data = await mutate(`/api/productions/${production.id}/interventions`, 'POST', JSON.stringify({ content: intervention.trim(), recipient }))
      setProduction(data.production); setIntervention('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Message failed') }
    finally { setBusy(false) }
  }

  const decide = async (decision: Decision, action: 'approve' | 'reject') => {
    const resolution = await appModal.askPrompt({
      title: action === 'reject' ? 'מה צריך לשנות?' : 'הנחיה לשלב הבא',
      message: action === 'reject' ? 'כתוב ל־Codex ול־AGY מה צריך לתקן לפני ההמשך.' : 'אפשר להוסיף הנחיה לשלב הבא, או לאשר בלי טקסט.',
      placeholder: action === 'reject' ? 'מה צריך לשנות…' : 'הנחיה אופציונלית…',
      confirmLabel: action === 'reject' ? 'שליחת תיקונים' : 'אישור והמשך',
      required: action === 'reject',
    })
    if (resolution === null || (action === 'reject' && !resolution.trim())) return
    setBusy(true)
    try {
      const updated = await mutate(`/api/productions/${production!.id}/decisions/${decision.id}/${action}`, 'POST', JSON.stringify({ resolution }))
      setProduction(updated)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Decision failed') }
    finally { setBusy(false) }
  }

  const saveSettings = async () => {
    setBusy(true)
    try {
      const updated = await mutate('/api/settings/agents', 'PATCH', JSON.stringify(settings))
      setSettings(updated)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Settings failed') }
    finally { setBusy(false) }
  }

  const toggleSkill = async (skill: Skill) => {
    try {
      const updated = await mutate(`/api/skills/${skill.id}`, 'PATCH', JSON.stringify({ enabled: !skill.enabled }))
      setSkills(current => current.map(item => item.id === updated.id ? updated : item))
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Skill update failed') }
  }

  const registerSkillFolder = async () => {
    if (!registerPath.trim()) return
    try {
      const added = await mutate('/api/skills/register', 'POST', JSON.stringify({ path: registerPath.trim() }))
      setSkills(current => [...current.filter(item => item.id !== added.id), added]); setRegisterPath('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Skill registration failed') }
  }

  const uploadSkill = async (file: File | null) => {
    if (!file) return
    const form = new FormData(); form.set('package', file)
    try {
      const added = await mutate('/api/skills/upload', 'POST', form)
      setSkills(current => [...current.filter(item => item.id !== added.id), added])
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Skill upload failed') }
  }

  const deleteSkill = async (skill: Skill, mode: 'unregister' | 'complete') => {
    const text = mode === 'complete' ? `Delete ${skill.name} and its managed files completely?` : `Unregister ${skill.name} but keep its files?`
    if (!await appModal.askConfirm({
      title: mode === 'complete' ? 'מחיקת Skill וקבציו' : 'הסרת Skill מהרשימה',
      message: text,
      confirmLabel: mode === 'complete' ? 'מחיקה מלאה' : 'הסרה',
      danger: mode === 'complete',
    })) return
    try {
      await mutate(`/api/skills/${skill.id}?mode=${mode}`, 'DELETE')
      setSkills(current => current.filter(item => item.id !== skill.id))
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Skill removal failed') }
  }

  const uploadReference = async (file: File | null) => {
    if (!file || !production) return
    const form = new FormData(); form.set('media', file)
    setBusy(true)
    try { await mutate(`/api/productions/${production.id}/references`, 'POST', form); await loadProduction() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Reference upload failed') }
    finally { setBusy(false) }
  }

  const generateReference = async () => {
    if (!production || !referenceName.trim() || !referencePrompt.trim()) return
    setReferenceGenerating(true); setError('')
    try {
      const data = await mutate(
        `/api/productions/${production.id}/references/generate`, 'POST',
        JSON.stringify({ name: referenceName.trim(), prompt: referencePrompt.trim(), provider: referenceProvider }),
      )
      setProduction(data.production); setReferenceName(''); setReferencePrompt('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Reference generation failed') }
    finally { setReferenceGenerating(false) }
  }

  const removeReference = async (reference: ReferenceMedia) => {
    if (!production || !await appModal.askConfirm({
      title: 'מחיקת רפרנס',
      message: `למחוק את הרפרנס „${reference.name}”?`,
      confirmLabel: 'מחיקה',
      danger: true,
    })) return
    try { await mutate(`/api/productions/${production.id}/references/${reference.id}`, 'DELETE'); await loadProduction() }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Reference removal failed') }
  }

  const saveShot = async () => {
    if (!production || !editingShot) return
    setBusy(true)
    try {
      const updated = await mutate(`/api/productions/${production.id}/shots/${editingShot.id}`, 'PATCH', JSON.stringify({
        title: editingShot.title, prompt: editingShot.prompt, mode: editingShot.mode,
        continuity: editingShot.continuity, duration: Number(editingShot.duration),
        audio_mode: editingShot.audio_mode, audio_source: editingShot.audio_source,
        audio_start: Number(editingShot.audio_start || 0), audio_duration: Number(editingShot.audio_duration || editingShot.duration),
        audio_reference_id: editingShot.audio_reference_id || null,
        megapixels: Number(editingShot.megapixels), aspect_ratio: editingShot.aspect_ratio,
        steps: Number(editingShot.steps), engine: editingShot.engine,
        turbo_profile: editingShot.turbo_profile, reference_ids: editingShot.reference_ids,
      }))
      setProduction(updated); setEditingShot(null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Shot update failed') }
    finally { setBusy(false) }
  }

  const retryShot = async (shot: Shot) => {
    if (!production || !await appModal.askConfirm({
      title: 'יצירת ניסיון חדש',
      message: `להכניס לתור ניסיון חדש עבור השוט „${shot.title}”?`,
      confirmLabel: 'הכנס לתור',
    })) return
    setBusy(true)
    try { setProduction(await mutate(`/api/productions/${production.id}/shots/${shot.id}/retry`, 'POST', JSON.stringify({ regenerate_downstream: true }))) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Retry failed') }
    finally { setBusy(false) }
  }

  const saveProductionConfig = async () => {
    if (!production || !configDraft) return
    setBusy(true)
    try {
      const updated = await mutate(`/api/productions/${production.id}/settings`, 'PATCH', JSON.stringify({
        participation_mode: configDraft.participation_mode, continuity_mode: configDraft.continuity_mode,
        codex_runtime: 'codex', codex_model: configDraft.codex_model,
        codex_effort: configDraft.codex_effort, agy_runtime: 'agy', agy_model: configDraft.agy_model,
        agy_effort: configDraft.agy_effort, skills: configDraft.skills,
        reason: 'Updated from Production Room',
      }))
      setProduction(updated); setConfigOpen(false)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Production settings failed') }
    finally { setBusy(false) }
  }

  const lifecycle = async (action: 'duplicate'|'archive'|'delete') => {
    if (!production) return
    if (action === 'delete' && !await appModal.askConfirm({
      title: 'מחיקת הפקה',
      message: `למחוק את ההפקה „${production.title}” ואת קבצי ההפקה שלה?`,
      confirmLabel: 'מחיקה לצמיתות',
      danger: true,
    })) return
    setBusy(true)
    try {
      if (action === 'duplicate') {
        const copy = await mutate(`/api/productions/${production.id}/duplicate`)
        setProductions(current => [copy, ...current]); setSelectedId(copy.id); setProduction(copy)
      } else if (action === 'archive') {
        const updated = await mutate(`/api/productions/${production.id}/archive`, 'PATCH', JSON.stringify({ archived: !production.archived }))
        setProduction(updated); await loadCatalog()
      } else {
        await mutate(`/api/productions/${production.id}`, 'DELETE'); setProduction(null); setSelectedId(''); await loadCatalog()
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : `${action} failed`) }
    finally { setBusy(false) }
  }

  const importJobs = async () => {
    if (!production) return
    const ids = importIds.split(/[\s,]+/).map(value => value.trim()).filter(Boolean)
    if (!ids.length) return
    setBusy(true)
    try { setProduction(await mutate(`/api/productions/${production.id}/imports/jobs`, 'POST', JSON.stringify({ job_ids: ids }))); setImportIds('') }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Import failed') }
    finally { setBusy(false) }
  }

  const active = production && ['queued', 'running', 'pausing', 'retrying', 'stopping'].includes(production.status)
  const pendingDecisions = production?.decisions?.filter(item => item.status === 'pending') || []
  const finalVideo = production?.artifacts?.find(item => item.kind === 'final_video')

  if (view === 'settings') return <section className="ps-root">
    <header className="ps-page-head"><button className="ps-icon" onClick={() => setView('room')}><ChevronLeft size={19} /></button><div><span>Production Studio</span><h2>Agent & skill settings</h2></div><button className="ps-icon" onClick={() => void refreshModels()} disabled={modelsRefreshing}><RefreshCw className={modelsRefreshing ? 'spin' : ''} size={18} /></button></header>
    {error && <div className="ps-error">{error}<button onClick={() => setError('')}><X size={14} /></button></div>}
    <div className="ps-settings-grid">
      <section className="ps-panel"><div className="ps-panel-title"><Bot size={18} /><div><h3>Agent defaults</h3><p>Used by new productions. Active projects keep their frozen configuration.</p></div></div>
        <div className="ps-agent-grid">
          <AgentSelect label="CODEX" catalogs={models} runtime={settings.codex_runtime} model={settings.codex_model} effort={settings.codex_effort} onRuntime={value => setSettings(current => ({ ...current, codex_runtime: value }))} onModel={value => setSettings(current => ({ ...current, codex_model: value }))} onEffort={value => setSettings(current => ({ ...current, codex_effort: value }))} />
          <AgentSelect label="AGY" catalogs={models} runtime="agy" model={settings.agy_model} effort={settings.agy_effort} runtimeLocked onRuntime={() => {}} onModel={value => setSettings(current => ({ ...current, agy_model: value }))} onEffort={value => setSettings(current => ({ ...current, agy_effort: value }))} />
        </div><div className="ps-model-status"><span>Models queried from the installed CLIs{modelsFetchedAt ? ` · ${modelsFetchedAt}` : ''}</span><button className="ps-secondary" onClick={() => void refreshModels()} disabled={modelsRefreshing}>{modelsRefreshing ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />} Refresh models</button></div><button className="ps-primary" onClick={() => void saveSettings()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <Check size={17} />} Save defaults</button>
      </section>
      <section className="ps-panel ps-skills-panel"><div className="ps-panel-title"><Sparkles size={18} /><div><h3>Production skills</h3><p>Enabled skills become available to new productions.</p></div></div>
        <div className="ps-add-skill"><input value={registerPath} onChange={event => setRegisterPath(event.target.value)} placeholder="Existing skill folder path" /><button onClick={() => void registerSkillFolder()}><FolderPlus size={16} /> Register</button><label><FileArchive size={16} /> Upload ZIP<input type="file" accept=".zip,application/zip" onChange={event => { void uploadSkill(event.target.files?.[0] || null); event.currentTarget.value = '' }} /></label></div>
        <div className="ps-skill-list">{skills.map(skill => <article key={skill.id} className={`ps-skill ${!skill.valid ? 'invalid' : ''}`}>
          <label className="ps-switch"><input type="checkbox" checked={skill.enabled} disabled={!skill.valid} onChange={() => void toggleSkill(skill)} /><span /></label>
          <div><h4>{skill.name}</h4><p>{skill.error || skill.description || 'No description'}</p><small>{skill.source} · {skill.agents.join(' + ')}</small></div>
          <div className="ps-skill-actions"><button onClick={() => void deleteSkill(skill, 'unregister')}>Unregister</button>{skill.managed && <button className="danger" onClick={() => void deleteSkill(skill, 'complete')}><Trash2 size={14} /> Delete files</button>}</div>
        </article>)}</div>
      </section>
    </div>
    <AppModal modal={appModal.modal} value={appModal.value} onValueChange={appModal.setValue} onResolve={appModal.resolveModal} />
  </section>

  return <section className="ps-root">
    <header className="ps-page-head"><div className="ps-brand"><Sparkles size={20} /></div><div><span>Codex + AGY + You</span><h2>Production Room</h2></div><button className="ps-icon" onClick={() => setView('settings')} aria-label="Production settings"><Settings size={19} /></button></header>
    {error && <div className="ps-error">{error}<button onClick={() => setError('')}><X size={14} /></button></div>}
    <div className="ps-project-bar"><select value={selectedId} onChange={event => { setSelectedId(event.target.value); setNewProject(false) }}><option value="">Select a production</option>{productions.map(item => <option key={item.id} value={item.id}>{item.archived ? '[Archived] ' : ''}{item.title} · {item.status}</option>)}</select><button className="ps-new" onClick={() => setNewProject(true)}>+ New production</button></div>

    {(newProject || !production) ? <section className="ps-create ps-panel">
      <div className="ps-panel-title"><Clapperboard size={20} /><div><h3>New music-video production</h3><p>The pipeline is music-video only for this POC.</p></div></div>
      <div className="ps-form-grid"><label><span>Project title</span><input value={title} onChange={event => setTitle(event.target.value)} placeholder="Belly of the Beast" /></label><label><span>Song file</span><input type="file" accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg" onChange={event => setSong(event.target.files?.[0] || null)} /></label></div>
      <label><span>Lyrics</span><textarea value={lyrics} onChange={event => setLyrics(event.target.value)} placeholder="Paste the complete lyrics…" /></label>
      <label><span>Creative direction (optional)</span><textarea value={concept} onChange={event => setConcept(event.target.value)} placeholder="Characters, locations, visual style, story ideas, constraints…" /></label>
      <label className="ps-reference-upload ps-intake-references"><Upload size={16} /><span>Optional source references · characters, locations, props, video or audio</span><input type="file" multiple accept="image/*,video/*,audio/*" onChange={event => { setReferenceFiles(Array.from(event.target.files || [])); event.currentTarget.value = '' }} /></label>
      {!!referenceFiles.length && <div className="ps-intake-file-list">{referenceFiles.map(file => <span key={`${file.name}-${file.size}`}>{file.name}</span>)}</div>}
      <p className="ps-form-note">References are optional and can be partial. Codex and AGY will use the files you provide, then create only the missing visual references.</p>
      <div className="ps-choice-row"><div><span>Production mode</span><div className="ps-segment"><button className={participation === 'autonomous' ? 'active' : ''} onClick={() => setParticipation('autonomous')}>Autonomous</button><button className={participation === 'interactive' ? 'active' : ''} onClick={() => setParticipation('interactive')}>Interactive</button></div></div><label><span>Continuity</span><select value={continuity} onChange={event => setContinuity(event.target.value)}><option value="hybrid">Hybrid</option><option value="sequential">Sequential</option><option value="hard_cut">Hard cuts</option><option value="segmented">Segmented</option></select></label></div>
      <details className="ps-advanced-settings"><summary>Advanced settings (optional)</summary>
      <div className="ps-agent-grid"><AgentSelect label="CODEX" catalogs={models} runtime={codexRuntime} model={codexModel} effort={codexEffort} onRuntime={setCodexRuntime} onModel={setCodexModel} onEffort={setCodexEffort} /><AgentSelect label="AGY" catalogs={models} runtime="agy" model={agyModel} effort={agyEffort} runtimeLocked onRuntime={() => {}} onModel={setAgyModel} onEffort={setAgyEffort} /></div>
      <div className="ps-project-skills"><div className="ps-field-title"><Sparkles size={15} /><span>Enabled skills</span></div><div>{skills.filter(item => item.valid && item.enabled).map(skill => <label key={skill.id}><input type="checkbox" checked={selectedSkills.includes(skill.id)} onChange={() => setSelectedSkills(current => current.includes(skill.id) ? current.filter(id => id !== skill.id) : [...current, skill.id])} />{skill.name}</label>)}</div></div>
      </details>
      <div className="ps-create-actions">{newProject && production && <button className="ps-secondary" onClick={() => setNewProject(false)}>Cancel</button>}<button className="ps-primary" onClick={() => void create()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={18} /> : <Sparkles size={18} />} Create production</button></div>
    </section> : <>
      <section className="ps-production-head ps-panel"><div><span className={`ps-status ${production.status}`}>{production.status}</span><h3>{production.title}</h3><p>{production.stage.replaceAll('_', ' ')} · {production.participation_mode} · {production.continuity_mode}</p></div><div className="ps-controls">
        {['draft', 'stopped', 'failed'].includes(production.status) && <button className="primary" onClick={() => void control('start')} disabled={busy}><Play size={17} /> Start</button>}
        {production.status === 'paused' && <button className="primary" onClick={() => void control('resume')} disabled={busy}><Play size={17} /> Resume</button>}
        {active && <button onClick={() => void control('pause')} disabled={busy || production.status === 'pausing'}><Pause size={17} /> Pause</button>}
        {!['stopped', 'completed'].includes(production.status) && <button className="danger" onClick={() => void control('stop')} disabled={busy}><Square size={15} /> Stop</button>}
        <button onClick={() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })}><MessageSquare size={15} /> Intervene</button>
        <details className="ps-head-more"><summary>More</summary><div>
        <button onClick={() => { setConfigDraft({ ...production }); setConfigOpen(true) }} disabled={busy || !!active}><Settings size={15} /> Configure</button>
        <button onClick={() => void lifecycle('duplicate')} disabled={busy}><Copy size={15} /> Duplicate</button>
        <button onClick={() => void lifecycle('archive')} disabled={busy || !!active}><Archive size={15} /> {production.archived ? 'Unarchive' : 'Archive'}</button>
        <a className="ps-control-link" href={`/api/productions/${production.id}/export`}><Download size={15} /> Export</a>
        <button className="danger" onClick={() => void lifecycle('delete')} disabled={busy || !!active}><Trash2 size={15} /> Delete</button>
        </div></details>
      </div><div className="ps-stage-progress"><span style={{ width: `${Math.round((production.progress || 0) * 100)}%` }} /></div></section>

      {configOpen && configDraft && <section className="ps-panel ps-project-config"><div className="ps-panel-title"><Settings size={18} /><div><h3>Production configuration</h3><p>Available while the production is not running. Saving creates a revision.</p></div></div><div className="ps-choice-row"><label><span>Mode</span><select value={configDraft.participation_mode} onChange={event => setConfigDraft(current => current && ({ ...current, participation_mode: event.target.value }))}><option value="autonomous">Autonomous</option><option value="interactive">Interactive</option></select></label><label><span>Continuity</span><select value={configDraft.continuity_mode} onChange={event => setConfigDraft(current => current && ({ ...current, continuity_mode: event.target.value }))}><option value="hybrid">Hybrid</option><option value="sequential">Sequential</option><option value="hard_cut">Hard cuts</option><option value="segmented">Segmented</option></select></label></div><div className="ps-agent-grid"><AgentSelect label="CODEX" catalogs={models} runtime={configDraft.codex_runtime} model={configDraft.codex_model} effort={configDraft.codex_effort} onRuntime={value => { const first=models[value][0]; setConfigDraft(current => current && ({...current,codex_runtime:value,codex_model:first?.id || '',codex_effort:first?.efforts[0] || 'medium'})) }} onModel={value => setConfigDraft(current => current && ({...current,codex_model:value}))} onEffort={value => setConfigDraft(current => current && ({...current,codex_effort:value}))} /><AgentSelect label="AGY" catalogs={models} runtime="agy" model={configDraft.agy_model} effort={configDraft.agy_effort} onRuntime={value => setConfigDraft(current => current && ({...current,agy_runtime:value}))} onModel={value => setConfigDraft(current => current && ({...current,agy_model:value}))} onEffort={value => setConfigDraft(current => current && ({...current,agy_effort:value}))} /></div><div className="ps-project-skills"><div className="ps-field-title"><Sparkles size={15}/><span>Skills used by this production</span></div><div>{skills.filter(item => item.valid && item.enabled).map(skill => <label key={skill.id}><input type="checkbox" checked={configDraft.skills.includes(skill.id)} onChange={() => setConfigDraft(current => current && ({...current,skills:current.skills.includes(skill.id)?current.skills.filter(id=>id!==skill.id):[...current.skills,skill.id]}))}/>{skill.name}</label>)}</div></div><div className="ps-create-actions"><button className="ps-secondary" onClick={() => setConfigOpen(false)}>Cancel</button><button className="ps-primary" onClick={() => void saveProductionConfig()}>Save revision</button></div></section>}

      <details className="ps-panel ps-reference-manager"><summary className="ps-panel-title"><Upload size={18} /><div><h3>Reference media</h3><p>Images, videos, and audio can be assigned to current T2V/I2V production shots. R2V remains available elsewhere in the app for future production support. Generated stills are jointly reviewed by Codex and AGY.</p></div></summary><div className="ps-reference-generator"><div className="ps-field-title"><ImagePlus size={16}/><span>Generate reference image</span></div><div className="ps-form-grid"><label><span>Reference name</span><input value={referenceName} onChange={event => setReferenceName(event.target.value)} placeholder="Main character · night wardrobe"/></label><label><span>Image provider</span><select value={referenceProvider} onChange={event => setReferenceProvider(event.target.value as 'auto'|'codex'|'agy')}><option value="auto">Auto · Codex then AGY fallback</option><option value="codex">Codex ImageGen</option><option value="agy">AGY ImageGen</option></select></label></div><label><span>Complete image brief</span><textarea value={referencePrompt} onChange={event => setReferencePrompt(event.target.value)} placeholder="Describe identity, wardrobe, location, lighting, camera and composition…"/></label><button className="ps-primary" onClick={() => void generateReference()} disabled={referenceGenerating || !!active || !referenceName.trim() || !referencePrompt.trim()}>{referenceGenerating ? <LoaderCircle className="spin" size={16}/> : <ImagePlus size={16}/>} {referenceGenerating ? 'Generating and reviewing…' : 'Generate reference image'}</button>{active && <small>Pause or stop this production to generate a manual reference.</small>}</div><label className="ps-reference-upload"><Upload size={16} /> Add image, video, or audio<input type="file" accept="image/*,video/*,audio/*" onChange={event => { void uploadReference(event.target.files?.[0] || null); event.currentTarget.value='' }} /></label><div className="ps-reference-list">{production.references?.map(reference => <article key={reference.id}><a href={reference.url} target="_blank" rel="noreferrer"><b>{reference.kind}</b><span>{reference.name}</span></a><button onClick={() => void removeReference(reference)}><Trash2 size={13} /></button></article>)}{!production.references?.length && <p>No reference media uploaded yet.</p>}</div><div className="ps-import-jobs"><span>Import completed generations</span>{regularJobs.slice(0, 20).map(job => <label key={job.id}><input type="checkbox" checked={importIds.split(',').filter(Boolean).includes(job.id)} onChange={() => { const current=importIds.split(',').filter(Boolean); setImportIds(current.includes(job.id)?current.filter(id=>id!==job.id).join(','):[...current,job.id].join(',')) }}/><b>{job.duration}s · {job.mode}</b><small>{job.prompt}</small></label>)}{!regularJobs.length && <small>No completed regular jobs are available.</small>}<button onClick={() => void importJobs()} disabled={!importIds}>Import selected results</button></div></details>

      <div className="ps-workspace">
        <aside className="ps-panel ps-timeline"><div className="ps-panel-title"><Clapperboard size={17} /><div><h3>Storyboard</h3><p>Shot plan · persistent checkpoint</p></div></div>{['intake','song_analysis','treatment','references','prompts','generation','review','assembly','final'].map((stage, index) => <div key={stage} className={production.stage.includes(stage) ? 'current' : index / 9 < production.progress ? 'done' : ''}><i>{index / 9 < production.progress ? <Check size={12} /> : index + 1}</i><span>{stage}</span></div>)}
          {!!production.shots?.length && <div className="ps-shot-list"><h4>Shots</h4>{production.shots.map(shot => <article key={shot.id}><span>{shot.shot_index}</span><div><b>{shot.title}</b><small>{shot.mode.toUpperCase()} · {shot.continuity === 'sequential' ? 'SEQUENTIAL' : 'HARD CUT'} · {shot.duration}s · {shot.megapixels} MP · {shot.aspect_ratio}{shot.audio_mode === 'lip_sync' ? ' · LIP-SYNC' : ''}</small><details><summary>Details</summary><p>{shot.prompt}</p>{shot.audio_mode === 'lip_sync' && <p className="ps-shot-audio-note">Audio: {shot.audio_source === 'reference' ? 'reference audio' : 'song'} · starts at {shot.audio_start.toFixed(2)}s</p>}{shot.attempts.map(attempt => <div className="ps-attempt" key={attempt.id}>Attempt {attempt.attempt}: {attempt.status}{attempt.output_path && <> · <a href={attempt.output_path} target="_blank" rel="noreferrer">video</a></>}</div>)}</details><div className="ps-shot-actions"><button onClick={() => setEditingShot({ ...shot, audio_mode: shot.audio_mode || 'silent', audio_source: shot.audio_source || 'song', audio_start: shot.audio_start || 0, audio_duration: shot.audio_duration || shot.duration, reference_ids: [...shot.reference_ids] })}><Pencil size={11}/> Shot settings</button><button onClick={() => void retryShot(shot)} disabled={!!active}><RotateCcw size={11}/> Retry</button></div></div><i className={shot.status}>{shot.status}</i></article>)}</div>}
        </aside>
        <main className="ps-panel ps-conversation"><div className="ps-panel-title"><MessageSquare size={18} /><div><h3>Production council</h3><p>User, Codex and AGY</p></div></div><div className="ps-messages">{production.messages?.map(message => <article key={message.id} className={`ps-message ${message.participant}`}><div className="ps-avatar"><ParticipantIcon participant={message.participant} /></div><div><header><b>{message.participant === 'user' ? 'YOU' : message.participant.toUpperCase()}</b><span>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span></header><p>{message.content}</p>{message.metadata && typeof message.metadata.model === 'string' && <small>{message.metadata.model} · {String(message.metadata.effort || '')}</small>}</div></article>)}</div>
          {finalVideo && <section className="ps-final-video"><div><Clapperboard size={18} /><b>Final music video</b></div><video controls playsInline preload="metadata" src={finalVideo.url} /><a href={finalVideo.url} download>Download final video</a></section>}
          <div className="ps-composer"><select value={recipient} onChange={event => setRecipient(event.target.value)}><option value="both">Both agents</option><option value="codex">Codex only</option><option value="agy">AGY only</option></select><textarea value={intervention} onChange={event => setIntervention(event.target.value)} placeholder="Guide Codex and AGY, correct a decision, or intervene…" /><button onClick={() => void sendIntervention()} disabled={busy || !intervention.trim()}><Send size={17} /></button></div>
        </main>
        <aside className="ps-panel ps-decisions"><div className="ps-panel-title"><ShieldCheck size={18} /><div><h3>Shot review</h3><p>{pendingDecisions.length} pending decisions</p></div></div>{!pendingDecisions.length && <div className="ps-empty"><ShieldCheck size={24} /><p>No pending decisions.</p></div>}{pendingDecisions.map(decision => <article className="ps-decision" key={decision.id}><span>{decision.stage.replaceAll('_', ' ')}</span><h4>{decision.title}</h4><p>{decision.summary}</p><div><button className="approve" onClick={() => void decide(decision, 'approve')}><Check size={15} /> Approve</button><button className="reject" onClick={() => void decide(decision, 'reject')}><X size={15} /> Reject / edit</button></div></article>)}</aside>
      </div>
      {production.error && <div className="ps-error">{production.error}</div>}
      {editingShot && <div className="ps-modal-backdrop"><section className="ps-panel ps-shot-editor"><div className="ps-panel-title"><Pencil size={18}/><div><h3>Edit shot {editingShot.shot_index}</h3><p>Set the essentials below. Prompt and references are under Advanced.</p></div><button onClick={() => setEditingShot(null)}><X size={16}/></button></div><div className="ps-form-grid"><label><span>Title</span><input value={editingShot.title} onChange={event => setEditingShot(current => current && ({...current,title:event.target.value}))}/></label><label><span>Mode</span><select value={editingShot.mode} onChange={event => { const mode=event.target.value as Shot['mode']; setEditingShot(current => current && ({...current,mode,steps:mode==='reference'?4:6,audio_mode:mode==='reference'?'silent':current.audio_mode})) }}><option value="text">T2V</option><option value="opening">I2V</option><option value="reference" disabled>R2V · future production support</option></select></label></div><details className="ps-advanced-settings"><summary>Prompt (optional)</summary><label><span>Complete prompt</span><textarea value={editingShot.prompt} onChange={event => setEditingShot(current => current && ({...current,prompt:event.target.value}))}/></label></details><div className="ps-form-grid"><label><span>Continuity</span><select value={editingShot.continuity} onChange={event => setEditingShot(current => current && ({...current,continuity:event.target.value as Shot['continuity']}))}><option value="hard_cut">Hard cut / independent</option><option value="sequential">Previous last frame</option></select></label><label><span>Aspect ratio</span><select value={editingShot.aspect_ratio} onChange={event => setEditingShot(current => current && ({...current,aspect_ratio:event.target.value}))}><option>16:9</option><option>9:16</option><option>1:1</option><option>4:3</option><option>3:4</option></select></label><label><span>Duration seconds</span><input type="number" min="0.5" max="15" step="0.5" value={editingShot.duration} onChange={event => setEditingShot(current => current && ({...current,duration:Number(event.target.value),audio_duration:current.audio_duration || Number(event.target.value)}))}/></label><label><span>Megapixels</span><input type="number" min="0.1" max="2" step="0.05" value={editingShot.megapixels} onChange={event => setEditingShot(current => current && ({...current,megapixels:Number(event.target.value)}))}/></label></div><div className="ps-form-grid ps-shot-audio-controls"><label><span>Audio</span><select value={editingShot.audio_mode || 'silent'} onChange={event => setEditingShot(current => current && ({...current,audio_mode:event.target.value as Shot['audio_mode'],audio_source:event.target.value==='silent'?'song':current.audio_source}))}><option value="silent">Silent generation</option><option value="lip_sync" disabled={editingShot.mode === 'reference'}>Lip-sync · song or reference audio</option></select></label>{editingShot.audio_mode === 'lip_sync' && <label><span>Audio source</span><select value={editingShot.audio_source || 'song'} onChange={event => setEditingShot(current => current && ({...current,audio_source:event.target.value as Shot['audio_source']}))}><option value="song">Production song segment</option><option value="reference" disabled={!production.references?.some(reference => reference.kind === 'audio')}>Assigned audio reference</option></select></label>}</div>{editingShot.audio_mode === 'lip_sync' && <div className="ps-form-grid ps-shot-audio-timing"><label><span>Audio start (seconds)</span><input type="number" min="0" max="3600" step="0.1" value={editingShot.audio_start || 0} onChange={event => setEditingShot(current => current && ({...current,audio_start:Number(event.target.value)}))}/></label><label><span>Audio duration</span><input type="number" min="0.5" max="60" step="0.1" value={editingShot.audio_duration || editingShot.duration} onChange={event => setEditingShot(current => current && ({...current,audio_duration:Number(event.target.value)}))}/></label>{editingShot.audio_source === 'reference' && <label><span>Audio reference</span><select value={editingShot.audio_reference_id || ''} onChange={event => setEditingShot(current => current && ({...current,audio_reference_id:event.target.value || null}))}><option value="">Choose audio reference</option>{production.references?.filter(reference => reference.kind === 'audio').map(reference => <option key={reference.id} value={reference.id}>{reference.name}</option>)}</select></label>}</div>}<details className="ps-advanced-settings"><summary>Assigned references (optional)</summary><div className="ps-reference-checks"><span>Assigned source references (used as I2V inputs; R2V is not used in production yet)</span>{production.references?.map(reference => <label key={reference.id}><input type="checkbox" checked={editingShot.reference_ids.includes(reference.id)} onChange={() => setEditingShot(current => current && ({...current,reference_ids:current.reference_ids.includes(reference.id)?current.reference_ids.filter(id=>id!==reference.id):[...current.reference_ids,reference.id]}))}/>{reference.kind}: {reference.name}</label>)}</div></details><div className="ps-create-actions"><button className="ps-secondary" onClick={() => setEditingShot(null)}>Cancel</button><button className="ps-primary" onClick={() => void saveShot()} disabled={busy}>Save shot</button></div></section></div>}
    </>}
    <AppModal modal={appModal.modal} value={appModal.value} onValueChange={appModal.setValue} onResolve={appModal.resolveModal} />
  </section>
}
