import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ArrowDown, ArrowUp, AudioLines, BrainCircuit, Check, Clapperboard, Combine, Download, Gauge, Image as ImageIcon, Link2, LoaderCircle, Minus, Play, Plus, Power, RefreshCw, Route, Send, ShieldAlert, SlidersHorizontal, Sparkles, Square, Terminal, Trash2, X, Zap } from 'lucide-react'
import './styles.css'

type Mode = 'text' | 'frames' | 'reference' | 'opening' | 'closing'
type Engine = 'turbo' | 'standard' | 'spectrum'
type Encoder = 'native' | 'clipproj'
type TurboProfile = 'v1' | 'v4'
type Resolution = '512x288' | '736x416' | '864x480' | '768x768' | '1024x768' | '768x1024' | '1344x768' | '768x1344'
type Status = 'queued' | 'starting' | 'running' | 'verifying' | 'completed' | 'failed' | 'canceled'
type Phase = 'queued' | 'starting' | 'sampling' | 'processing' | 'verifying' | 'completed' | 'failed' | 'canceled'
type Page = 'studio' | 'comfy'
type Job = {
  id: string; prompt: string; mode: Mode; duration: number; status: Status; progress: number;
  engine: Engine; turbo_profile?: TurboProfile; encoder: Encoder; steps: number; width: number; height: number; position?: number;
  phase?: Phase; step?: number; total_steps?: number; eta_seconds?: number | null;
  error?: string; video_url?: string; created_at: string; started_at?: string; finished_at?: string;
  metrics?: { generation_seconds?: number };
}

type SequenceKind = 'connected' | 'history'
type Sequence = {
  id: string; kind: SequenceKind; title: string; status: Status; position: number;
  engine?: Engine | null; encoder?: Encoder | null; steps?: number | null;
  width?: number | null; height?: number | null; duration?: number | null;
  progress: number; phase: string; current_item: number; total_items: number;
  eta_seconds?: number | null; error?: string; video_url?: string;
  created_at: string; started_at?: string; finished_at?: string;
  metrics?: { assembly_seconds?: number; source_durations?: number[] };
  items?: { item_index: number; prompt?: string; status: string }[];
}

const modes: { id: Mode; label: string; hint: string }[] = [
  { id: 'text', label: 'טקסט בלבד', hint: 'רעיון הופך לסרטון' },
  { id: 'frames', label: 'פריים פותח + סוגר', hint: 'שתי תמונות באותו סרטון' },
  { id: 'reference', label: 'רפרנס', hint: 'זהות וסגנון מהתמונה' },
]

type Aspect = '1:1' | '4:3' | '3:4' | '16:9' | '9:16'
type ResolutionOption = { id: Resolution; label: string; hint: string; width: number; height: number; aspect: Aspect; megapixels: number }
const resolutions: ResolutionOption[] = [
  { id: '512x288', label: 'חסכוני', hint: '512×288 · 0.15MP', width: 512, height: 288, aspect: '16:9', megapixels: 0.15 },
  { id: '736x416', label: 'מאוזן', hint: '736×416 · 0.31MP', width: 736, height: 416, aspect: '16:9', megapixels: 0.31 },
  { id: '864x480', label: 'גבוה', hint: '864×480 · 0.41MP', width: 864, height: 480, aspect: '16:9', megapixels: 0.41 },
  { id: '768x768', label: 'ריבוע טבעי', hint: '768×768 · 0.56MP', width: 768, height: 768, aspect: '1:1', megapixels: 0.56 },
  { id: '1024x768', label: '4:3 טבעי', hint: '1024×768 · 0.75MP', width: 1024, height: 768, aspect: '4:3', megapixels: 0.75 },
  { id: '768x1024', label: '3:4 טבעי', hint: '768×1024 · 0.75MP', width: 768, height: 1024, aspect: '3:4', megapixels: 0.75 },
  { id: '1344x768', label: '16:9 טבעי', hint: '1344×768 · 0.98MP', width: 1344, height: 768, aspect: '16:9', megapixels: 0.98 },
  { id: '768x1344', label: '9:16 טבעי', hint: '768×1344 · 0.98MP', width: 768, height: 1344, aspect: '9:16', megapixels: 0.98 },
]
const aspectOptions: Aspect[] = ['1:1', '4:3', '3:4', '16:9', '9:16']

function dimensionsFor(aspect: Aspect, megapixels: number) {
  const ratios: Record<Aspect, number> = { '1:1': 1, '4:3': 4 / 3, '3:4': 3 / 4, '16:9': 16 / 9, '9:16': 9 / 16 }
  const ratio = ratios[aspect]
  const width = Math.max(256, Math.round(Math.sqrt(megapixels * 1_000_000 * ratio) / 32) * 32)
  const height = Math.max(256, Math.round(Math.sqrt(megapixels * 1_000_000 / ratio) / 32) * 32)
  return { width, height, id: `${width}x${height}` as Resolution }
}

type Preferences = {
  engine: Engine
  encoder: Encoder
  turboProfile: TurboProfile
  turboSteps: number
  standardSteps: number
  spectrumSteps: number
  resolution: Resolution
  aspect: Aspect
  megapixels: number
}

const defaultPreferences: Preferences = { engine: 'turbo', encoder: 'native', turboProfile: 'v1', turboSteps: 4, standardSteps: 20, spectrumSteps: 16, resolution: '736x416', aspect: '16:9', megapixels: 0.31 }
const preferenceKey = 'h3-generation-preferences-v1'

function readPreferences(): Preferences {
  try {
    const saved = JSON.parse(localStorage.getItem(preferenceKey) || '{}') as Partial<Preferences>
    return {
      engine: saved.engine === 'standard' || saved.engine === 'spectrum' ? saved.engine : 'turbo',
      encoder: saved.encoder === 'clipproj' ? 'clipproj' : 'native',
      turboProfile: saved.turboProfile === 'v4' ? 'v4' : 'v1',
      turboSteps: Number.isInteger(saved.turboSteps) && saved.turboSteps! >= 4 && saved.turboSteps! <= 12 ? saved.turboSteps! : 4,
      standardSteps: Number.isInteger(saved.standardSteps) && saved.standardSteps! >= 8 && saved.standardSteps! <= 30 ? saved.standardSteps! : 20,
      spectrumSteps: Number.isInteger(saved.spectrumSteps) && saved.spectrumSteps! >= 8 && saved.spectrumSteps! <= 30 ? saved.spectrumSteps! : 16,
      resolution: resolutions.some(item => item.id === saved.resolution) ? saved.resolution! : '736x416',
      aspect: aspectOptions.includes(saved.aspect as Aspect) ? saved.aspect as Aspect : '16:9',
      megapixels: typeof saved.megapixels === 'number' && saved.megapixels >= 0.1 && saved.megapixels <= 2 ? saved.megapixels : 0.31,
    }
  } catch {
    return defaultPreferences
  }
}

type ImageDropzoneProps = {
  label: string
  hint: string
  preview: string
  onChange: (file: File | null) => void
}

function ImageDropzone({ label, hint, preview, onChange }: ImageDropzoneProps) {
  return <label className={`dropzone ${preview ? 'has-image' : ''}`}>
    <input type="file" accept="image/jpeg,image/png,image/webp" onChange={e => onChange(e.target.files?.[0] || null)} />
    {preview ? <><img src={preview} alt="תצוגה מקדימה" /><button type="button" aria-label="הסרת תמונה" onClick={e => { e.preventDefault(); e.stopPropagation(); onChange(null) }}><X size={17} /></button></> : <><ImageIcon size={24} /><strong>{label}</strong><span>{hint}</span></>}
  </label>
}

type AudioDropzoneProps = {
  file: File | null
  onChange: (file: File | null) => void
}

function AudioDropzone({ file, onChange }: AudioDropzoneProps) {
  return <label className={`dropzone audio-dropzone ${file ? 'has-audio' : ''}`}>
    <input type="file" accept="audio/wav,audio/x-wav,audio/mpeg,audio/mp4,audio/x-m4a,audio/aac,audio/flac,audio/ogg" onChange={e => onChange(e.target.files?.[0] || null)} />
    {file ? <><AudioLines size={24} /><strong dir="auto">{file.name}</strong><span>{(file.size / 1024 / 1024).toFixed(1)}MB · רפרנס אופציונלי</span><button type="button" aria-label="הסרת אודיו" onClick={e => { e.preventDefault(); e.stopPropagation(); onChange(null) }}><X size={17} /></button></> : <><AudioLines size={24} /><strong>הוסף אודיו לרפרנס</strong><span>WAV, MP3, M4A, AAC, FLAC או OGG · עד 50MB</span></>}
  </label>
}

type ComfyPageProps = { running: boolean; busy: boolean; lines: string[]; error: string; onRefresh: () => void }

function ComfyPage({ running, busy, lines, error, onRefresh }: ComfyPageProps) {
  return <section className="comfy-page">
    <div className="comfy-page-heading"><div><span className="eyebrow"><Terminal size={15} /> ComfyUI</span><h2>ComfyUI logs</h2></div><button className="icon-button" onClick={onRefresh} aria-label="Refresh log"><RefreshCw size={18} /></button></div>
    <div className={`comfy-state ${running ? 'running' : 'stopped'}`}><i /> {running ? 'ComfyUI running' : 'ComfyUI stopped'}<span>{busy ? 'Updating…' : 'Auto-refreshing'}</span></div>
    {error && <div className="error-banner">{error}</div>}
    <pre className="comfy-log" aria-live="polite">{lines.length ? lines.join('\n') : 'No log output yet. Start ComfyUI to begin.'}</pre>
  </section>
}

function App() {
  const [page, setPage] = useState<Page>('studio')
  const [csrf, setCsrf] = useState('')
  const [jobs, setJobs] = useState<Job[]>([])
  const [sequences, setSequences] = useState<Sequence[]>([])
  const [prompt, setPrompt] = useState('')
  const [mode, setMode] = useState<Mode>('text')
  const [duration, setDuration] = useState(5)
  const [batch, setBatch] = useState(false)
  const [connected, setConnected] = useState(false)
  const [preferences, setPreferences] = useState<Preferences>(readPreferences)
  const [confirming, setConfirming] = useState(false)
  const [referenceImage, setReferenceImage] = useState<File | null>(null)
  const [referenceAudio, setReferenceAudio] = useState<File | null>(null)
  const [openingFrame, setOpeningFrame] = useState<File | null>(null)
  const [closingFrame, setClosingFrame] = useState<File | null>(null)
  const [referencePreview, setReferencePreview] = useState('')
  const [openingPreview, setOpeningPreview] = useState('')
  const [closingPreview, setClosingPreview] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [referenceReady, setReferenceReady] = useState(false)
  const [reference10Ready, setReference10Ready] = useState(false)
  const [spectrumReady, setSpectrumReady] = useState(false)
  const [clipprojReady, setClipprojReady] = useState(false)
  const [turboV4Ready, setTurboV4Ready] = useState(false)
  const [selectedResults, setSelectedResults] = useState<string[]>([])
  const [joining, setJoining] = useState(false)
  const [comfyRunning, setComfyRunning] = useState(false)
  const [comfyBusy, setComfyBusy] = useState(false)
  const [comfyLogs, setComfyLogs] = useState<string[]>([])
  const [comfyError, setComfyError] = useState('')

  const loadSession = async (): Promise<string | null> => {
    try {
      const response = await fetch('/api/session', { cache: 'no-store', credentials: 'same-origin' })
      if (!response.ok) throw new Error('session unavailable')
      const data = await response.json()
      if (!data.csrf_token) throw new Error('missing session token')
      setCsrf(data.csrf_token)
      setReferenceReady(data.reference_ready)
      setReference10Ready(data.reference_10s_ready)
      setSpectrumReady(data.spectrum_ready)
      setClipprojReady(data.clipproj_ready)
      setTurboV4Ready(data.turbo_v4_ready)
      return data.csrf_token
    } catch {
      setCsrf('')
      return null
    }
  }

  const load = async () => {
    try {
      const response = await fetch('/api/jobs', { cache: 'no-store' })
      if (response.ok) {
        const data = await response.json()
        setJobs(data.jobs); setSequences(data.sequences || []); setReferenceReady(data.reference_ready); setReference10Ready(data.reference_10s_ready); setSpectrumReady(data.spectrum_ready); setClipprojReady(data.clipproj_ready); setTurboV4Ready(data.turbo_v4_ready)
      }
    } catch {
      // The session retry below will recover after a brief bridge restart.
    }
  }

  useEffect(() => {
    void loadSession()
    void load()
    const timer = window.setInterval(load, 2000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (csrf) return
    const timer = window.setInterval(() => { void loadSession() }, 3000)
    return () => window.clearInterval(timer)
  }, [csrf])

  const loadComfy = async () => {
    try {
      const [statusResponse, logsResponse] = await Promise.all([
        fetch('/api/comfy/status', { cache: 'no-store' }),
        fetch('/api/comfy/logs?tail=400', { cache: 'no-store' }),
      ])
      if (!statusResponse.ok || !logsResponse.ok) throw new Error('ComfyUI status unavailable')
      const status = await statusResponse.json()
      const logs = await logsResponse.json()
      setComfyRunning(Boolean(status.running))
      setComfyLogs(Array.isArray(logs.lines) ? logs.lines : [])
      setComfyError('')
    } catch {
      setComfyError('Unable to read ComfyUI status')
    }
  }

  useEffect(() => {
    void loadComfy()
    const timer = window.setInterval(() => { void loadComfy() }, 2000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!referenceImage) { setReferencePreview(''); return }
    const url = URL.createObjectURL(referenceImage); setReferencePreview(url)
    return () => URL.revokeObjectURL(url)
  }, [referenceImage])

  useEffect(() => {
    if (!openingFrame) { setOpeningPreview(''); return }
    const url = URL.createObjectURL(openingFrame); setOpeningPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [openingFrame])

  useEffect(() => {
    if (!closingFrame) { setClosingPreview(''); return }
    const url = URL.createObjectURL(closingFrame); setClosingPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [closingFrame])

  useEffect(() => {
    localStorage.setItem(preferenceKey, JSON.stringify(preferences))
  }, [preferences])

  useEffect(() => {
    if (!confirming) return
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setConfirming(false) }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [confirming])

  const paragraphCount = useMemo(() => batch ? prompt.trim().split(/\n\s*\n/).filter(Boolean).length : 1, [prompt, batch])
  const effectiveEngine: Engine = mode === 'reference' && preferences.engine === 'turbo' ? 'standard' : preferences.engine
  const effectiveEncoder: Encoder = preferences.encoder
  const generationSteps = effectiveEngine === 'turbo' ? preferences.turboSteps : effectiveEngine === 'spectrum' ? preferences.spectrumSteps : preferences.standardSteps
  const stepRange = effectiveEngine === 'turbo'
    ? preferences.turboProfile === 'v4' ? { min: 4, max: 8, recommended: 6 } : { min: 4, max: 12, recommended: 4 }
    : effectiveEngine === 'spectrum' ? { min: 8, max: 30, recommended: 16 } : { min: 8, max: 30, recommended: 20 }
  const calculatedResolution = dimensionsFor(preferences.aspect, preferences.megapixels)
  const requestedFrames = Math.max(5, Math.round(duration * 24))
  const h3Frames = requestedFrames + (5 - requestedFrames % 17) % 17
  const engineLoadFactor = effectiveEngine === 'spectrum' ? 1.8 : 1
  const promptMultiplier = batch ? Math.max(1, paragraphCount) : 1
  const relativeLoad = calculatedResolution.width * calculatedResolution.height * duration * generationSteps * engineLoadFactor * promptMultiplier / (736 * 416 * 5 * 4)
  const loadLevel = relativeLoad >= 5 ? 'very-heavy' : relativeLoad >= 2 ? 'heavy' : 'normal'
  const loadLabel = loadLevel === 'very-heavy' ? 'כבד מאוד' : loadLevel === 'heavy' ? 'כבד' : 'רגיל'
  const needsConfirmation = effectiveEngine === 'spectrum' || effectiveEncoder === 'clipproj' || (effectiveEngine === 'turbo' && preferences.turboProfile === 'v4') || connected || relativeLoad >= 2 || (batch && paragraphCount >= 5)
  const queued = jobs.filter(j => j.status === 'queued')
  const active = jobs.filter(j => ['starting', 'running', 'verifying'].includes(j.status))
  const history = jobs.filter(j => !['queued', 'starting', 'running', 'verifying'].includes(j.status))
  const activeSequences = sequences.filter(item => ['starting', 'running', 'verifying'].includes(item.status))
  const queuedSequences = sequences.filter(item => item.status === 'queued')
  const sequenceHistory = sequences.filter(item => !['queued', 'starting', 'running', 'verifying'].includes(item.status))
  const queuedTasks = [
    ...queued.map(job => ({ kind: 'job' as const, position: job.position || Number.MAX_SAFE_INTEGER, job })),
    ...queuedSequences.map(sequence => ({ kind: 'sequence' as const, position: sequence.position, sequence })),
  ].sort((a, b) => a.position - b.position)

  const mutate = async (url: string, method = 'POST', body?: BodyInit, sessionToken = csrf) => {
    const response = await fetch(url, { method, headers: { 'X-CSRF-Token': sessionToken }, body })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || 'הפעולה נכשלה')
    await load()
    return data
  }

  const controlComfy = async (action: 'start' | 'stop') => {
    if (comfyBusy) return
    setComfyBusy(true)
    setComfyError('')
    try {
      const sessionToken = csrf || await loadSession()
      if (!sessionToken) throw new Error('The server session is not ready')
      const response = await fetch(`/api/comfy/${action}`, { method: 'POST', headers: { 'X-CSRF-Token': sessionToken } })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || 'ComfyUI action failed')
      setComfyRunning(Boolean(data.running))
      await loadComfy()
    } catch (e) {
      setComfyError(e instanceof Error ? e.message : 'ComfyUI action failed')
    } finally {
      setComfyBusy(false)
    }
  }

  const selectMode = (next: Mode) => {
    setMode(next)
    setError('')
    if (next !== 'text') setConnected(false)
    if (next === 'frames') { setReferenceImage(null); setReferenceAudio(null) }
    else if (next === 'reference') {
      setOpeningFrame(null)
      setClosingFrame(null)
    } else if (next === 'text') {
      setReferenceImage(null)
      setReferenceAudio(null)
      setOpeningFrame(null)
      setClosingFrame(null)
    }
  }

  const selectEngine = (engine: Engine) => {
    if (mode === 'reference' && engine === 'turbo') return
    if (engine === 'spectrum' && !spectrumReady) return
    setPreferences(current => ({ ...current, engine }))
  }

  const selectEncoder = (encoder: Encoder) => {
    if (encoder === 'clipproj' && !clipprojReady) return
    setPreferences(current => ({ ...current, encoder }))
  }

  const selectTurboProfile = (turboProfile: TurboProfile) => {
    if (turboProfile === 'v4' && !turboV4Ready) return
    setPreferences(current => ({
      ...current,
      turboProfile,
      turboSteps: turboProfile === 'v4' ? Math.min(current.turboSteps, 8) : current.turboSteps,
    }))
  }

  const setGenerationSteps = (value: number) => {
    const next = Math.max(stepRange.min, Math.min(stepRange.max, Math.round(value)))
    setPreferences(current => effectiveEngine === 'turbo'
      ? { ...current, turboSteps: next }
      : effectiveEngine === 'spectrum'
        ? { ...current, spectrumSteps: next }
        : { ...current, standardSteps: next })
  }

  const submit = async (confirmed = false) => {
    setError('')
    if (!prompt.trim()) return setError('צריך לכתוב פרומפט')
    if (mode === 'frames' && (!openingFrame || !closingFrame)) return setError('צריך לצרף גם פריים פותח וגם פריים סוגר')
    if (mode === 'reference' && !referenceImage) return setError('צריך לצרף תמונת רפרנס')
    if (batch && paragraphCount > 20) return setError('אפשר להוסיף עד 20 פרומפטים יחד')
    if (connected && (!batch || mode !== 'text' || paragraphCount < 2)) return setError('רצף מחובר דורש לפחות שני פרומפטים במצב טקסט')
    if (effectiveEncoder === 'clipproj' && !clipprojReady) return setError('ClipProj עדיין לא מוכן להפעלה')
    if (!confirmed && needsConfirmation) { setConfirming(true); return }
    const sessionToken = csrf || await loadSession()
    if (!sessionToken) return setError('החיבור לשרת עדיין מתחבר. נסי שוב בעוד רגע')
    const form = new FormData()
    form.set('prompt', prompt); form.set('mode', mode); form.set('duration', String(duration)); form.set('batch', String(batch))
    form.set('engine', effectiveEngine); form.set('encoder', effectiveEncoder); form.set('steps', String(generationSteps)); form.set('resolution', calculatedResolution.id); form.set('connected', String(connected))
    if (effectiveEngine === 'turbo') form.set('turbo_profile', preferences.turboProfile)
    if (mode === 'frames') {
      form.set('first_frame', openingFrame!)
      form.set('last_frame', closingFrame!)
    } else if (mode === 'reference') {
      form.set('image', referenceImage!)
      if (referenceAudio) form.set('reference_audio', referenceAudio)
    }
    setConfirming(false)
    setSending(true)
    try {
      await mutate('/api/jobs', 'POST', form, sessionToken)
      setPrompt(''); setReferenceImage(null); setReferenceAudio(null); setOpeningFrame(null); setClosingFrame(null); setBatch(false); setConnected(false)
    } catch (e) { setError(e instanceof Error ? e.message : 'השליחה נכשלה') }
    finally { setSending(false) }
  }

  const move = async (id: string, delta: number) => {
    const ids = queued.map(j => j.id); const index = ids.indexOf(id); const next = index + delta
    if (next < 0 || next >= ids.length) return
    ;[ids[index], ids[next]] = [ids[next], ids[index]]
    try { await mutate('/api/queue/order', 'PATCH', new Blob([JSON.stringify({ ids })], { type: 'application/json' })) } catch (e) { setError(String(e)) }
  }

  const toggleResult = (reference: string) => {
    setSelectedResults(current => current.includes(reference)
      ? current.filter(item => item !== reference)
      : [...current, reference])
  }

  const moveSelectedResult = (index: number, delta: number) => {
    setSelectedResults(current => {
      const nextIndex = index + delta
      if (nextIndex < 0 || nextIndex >= current.length) return current
      const next = [...current]
      ;[next[index], next[nextIndex]] = [next[nextIndex], next[index]]
      return next
    })
  }

  const joinSelected = async () => {
    setError('')
    if (selectedResults.length < 2) return setError('צריך לבחור לפחות שני סרטונים לחיבור')
    if (joining) return
    setJoining(true)
    try {
      const sessionToken = csrf || await loadSession()
      if (!sessionToken) throw new Error('החיבור לשרת עדיין מתחבר. נסי שוב בעוד רגע')
      await mutate('/api/sequences/join', 'POST', new Blob([JSON.stringify({ ids: selectedResults })], { type: 'application/json' }), sessionToken)
      setSelectedResults([])
    } catch (e) { setError(e instanceof Error ? e.message : 'החיבור נכשל') }
    finally { setJoining(false) }
  }

  const selectedResultLabel = (reference: string) => {
    const [kind, id] = reference.split(':', 2)
    if (kind === 'sequence') return sequences.find(item => item.id === id)?.title || 'וידאו מחובר'
    const job = jobs.find(item => item.id === id)
    return job?.prompt || 'וידאו מההיסטוריה'
  }

  return <main className="shell">
    <header className="topbar">
      <div className="brand-mark"><Clapperboard size={22} /></div>
      <div><h1>H3 Studio</h1><p>יוצרים וידאו מהמחשב שלך</p></div>
      <div className="topbar-actions">
        <button className={`comfy-status-button ${comfyRunning ? 'running' : ''}`} onClick={() => setPage('comfy')}><i /> <span>{comfyRunning ? 'ComfyUI running' : 'ComfyUI stopped'}</span></button>
        <button className="comfy-control-button" onClick={() => { void controlComfy(comfyRunning ? 'stop' : 'start') }} disabled={comfyBusy} aria-label={comfyRunning ? 'Stop ComfyUI' : 'Start ComfyUI'}>{comfyBusy ? <LoaderCircle className="spin" size={16} /> : comfyRunning ? <Square size={15} /> : <Power size={16} />}</button>
        <button className="icon-button" onClick={() => { if (page === 'comfy') void loadComfy(); else { void loadSession(); void load() } }} aria-label="רענון"><RefreshCw size={18} /></button>
      </div>
    </header>
    <nav className="page-tabs" aria-label="Navigation"><button className={page === 'studio' ? 'active' : ''} onClick={() => setPage('studio')}><Clapperboard size={15} /> Studio</button><button className={page === 'comfy' ? 'active' : ''} onClick={() => setPage('comfy')}><Terminal size={15} /> ComfyUI logs</button></nav>
    {page === 'comfy' ? <ComfyPage running={comfyRunning} busy={comfyBusy} lines={comfyLogs} error={comfyError} onRefresh={() => { void loadComfy() }} /> : <>

    <section className="composer">
      <div className="eyebrow"><Sparkles size={15} /> יצירה חדשה</div>
      <textarea value={prompt} onChange={e => setPrompt(e.target.value)} maxLength={batch ? 80000 : 4000}
        placeholder={batch ? 'הדבק כמה פרומפטים. השאר שורה ריקה בין כל אחד…' : 'תאר את הסרטון שאתה רוצה ליצור…'} />
      <div className="composer-meta"><span>{prompt.length.toLocaleString()} תווים</span><label className="batch-toggle"><input type="checkbox" checked={batch} onChange={e => { setBatch(e.target.checked); if (!e.target.checked) setConnected(false) }} /><span>כמה פרומפטים</span></label></div>
      {batch && <div className="batch-note">כל פסקה היא שוט אחד · {paragraphCount} שוטים</div>}
      {batch && mode === 'text' && <div className="sequence-choice" aria-label="אופן עיבוד הפרומפטים">
        <button type="button" className={!connected ? 'active' : ''} onClick={() => setConnected(false)}><Clapperboard size={17} /><span><strong>נפרדים</strong><small>כל פרומפט הוא תוצאה</small></span></button>
        <button type="button" className={connected ? 'active connected' : ''} onClick={() => setConnected(true)}><Route size={17} /><span><strong>רצף מחובר</strong><small>סוף שוט הופך לפתיחת הבא</small></span></button>
      </div>}
      {connected && <div className="connected-note"><Route size={14} /><span>האפליקציה תייצר לפי הסדר, תבדוק כל שוט, תחלץ את הפריים האחרון ותחבר MP4 סופי אחד.</span></div>}

      <div className="mode-grid">
        {modes.map(item => <button key={item.id} className={`mode-card ${mode === item.id ? 'selected' : ''}`} onClick={() => selectMode(item.id)}>
          <span className="mode-check">{mode === item.id && <Check size={13} />}</span>
          <strong>{item.label}</strong><small>{item.hint}</small>
        </button>)}
      </div>

      {mode === 'frames' && <div className="frame-grid">
        <ImageDropzone label="הוסף פריים פותח" hint="התמונה הראשונה · JPG, PNG או WebP עד 20MB" preview={openingPreview} onChange={setOpeningFrame} />
        <ImageDropzone label="הוסף פריים סוגר" hint="התמונה האחרונה · JPG, PNG או WebP עד 20MB" preview={closingPreview} onChange={setClosingFrame} />
      </div>}
      {mode === 'reference' && <>
        <div className="reference-grid">
          <ImageDropzone label="הוסף תמונת רפרנס" hint="חובה · JPG, PNG או WebP עד 20MB" preview={referencePreview} onChange={setReferenceImage} />
          <AudioDropzone file={referenceAudio} onChange={setReferenceAudio} />
        </div>
        {referenceAudio && <div className="reference-audio-note"><AudioLines size={14} /><span>בפרומפט אפשר לכתוב <b dir="ltr">&lt;Picture 1&gt;</b> ו־<b dir="ltr">&lt;Audio 1&gt;</b>. H3 ישתמש בקול ובתזמון כרפרנס וייצר אודיו חדש יחד עם תנועת השפתיים.</span></div>}
      </>}

      <div className="generation-panel">
        <div className="generation-heading">
          <div><SlidersHorizontal size={16} /><span>הגדרות יצירה</span></div>
          <span className={`load-badge ${loadLevel}`}><i /> עומס {loadLabel} · ×{relativeLoad.toFixed(relativeLoad < 10 ? 1 : 0)}</span>
        </div>

        <div className="settings-grid">
          <div className="setting-block">
            <div className="setting-title"><span>מנוע</span><small>מהירות מול איכות</small></div>
            <div className="engine-toggle">
              <button type="button" className={effectiveEngine === 'turbo' ? 'active' : ''} aria-pressed={effectiveEngine === 'turbo'} disabled={mode === 'reference'} onClick={() => selectEngine('turbo')}>
                <Zap size={16} /><span><strong>Turbo</strong><small>מהיר</small></span>
              </button>
              <button type="button" className={effectiveEngine === 'standard' ? 'active' : ''} aria-pressed={effectiveEngine === 'standard'} onClick={() => selectEngine('standard')}>
                <Gauge size={16} /><span><strong>רגיל</strong><small>מדויק</small></span>
              </button>
              <button type="button" className={effectiveEngine === 'spectrum' ? 'active' : ''} aria-pressed={effectiveEngine === 'spectrum'} disabled={!spectrumReady} onClick={() => selectEngine('spectrum')}>
                <Sparkles size={16} /><span><strong>Spectrum</strong><small>native + מהיר</small></span>
              </button>
            </div>
            {mode === 'reference' && <p className="setting-note">רפרנס עובד עם רגיל או Spectrum; Turbo לא מתאים למסלול הזה</p>}
            {!spectrumReady && <p className="setting-note">Spectrum יופיע אחרי שה־ComfyUI עם התוסף יופעל מחדש</p>}
            {effectiveEngine === 'turbo' && <>
              <div className="setting-title turbo-profile-title"><span>Turbo LoRA</span><small>בחירת אופי התוצאה</small></div>
              <div className="turbo-profile-toggle">
                <button type="button" className={preferences.turboProfile === 'v1' ? 'active' : ''} aria-pressed={preferences.turboProfile === 'v1'} onClick={() => selectTurboProfile('v1')}><strong>v1 · 850</strong><small>יציב יותר בתנועה מהירה</small></button>
                <button type="button" className={preferences.turboProfile === 'v4' ? 'active' : ''} aria-pressed={preferences.turboProfile === 'v4'} disabled={!turboV4Ready} onClick={() => selectTurboProfile('v4')}><strong>v4 · 600</strong><small>פנים ופרטים טובים יותר</small></button>
              </div>
              {!turboV4Ready && <p className="setting-note">Turbo v4 ייפתח אחרי הורדת המודל ובדיקת checksum</p>}
              {preferences.turboProfile === 'v4' && generationSteps === 4 && <p className="setting-note">בתנועה מהירה v4 על 4 סטפים עלול למרוח; 6–8 סטפים מומלצים</p>}
            </>}
          </div>

          <div className="setting-block">
            <div className="setting-title"><span>Text Encoder</span><small>זיכרון מול דיוק</small></div>
            <div className="encoder-toggle">
              <button type="button" className={effectiveEncoder === 'native' ? 'active' : ''} aria-pressed={effectiveEncoder === 'native'} onClick={() => selectEncoder('native')}>
                <BrainCircuit size={17} /><span><strong>32B מקורי</strong><small>דיוק מלא</small></span>
              </button>
              <button type="button" className={effectiveEncoder === 'clipproj' ? 'active' : ''} aria-pressed={effectiveEncoder === 'clipproj'} disabled={!clipprojReady} onClick={() => selectEncoder('clipproj')}>
                <Sparkles size={17} /><span><strong>ClipProj 4B</strong><small>חסכוני · ניסיוני</small></span>
              </button>
            </div>
            {!clipprojReady && <p className="setting-note">ClipProj ייפתח אחרי סיום ההתקנה והפעלה מחדש של ComfyUI</p>}
            {effectiveEncoder === 'clipproj' && mode === 'reference' && <p className="setting-note">ברפרנס ClipProj משתמש במצב resident ולכן העומס על 8GB עשוי להיות גבוה</p>}
          </div>

          <div className="setting-block">
            <div className="setting-title"><span>סטפים</span><small>{stepRange.recommended} מומלץ</small></div>
            <div className="stepper">
              <button type="button" aria-label="הפחתת סטפים" onClick={() => setGenerationSteps(generationSteps - 1)} disabled={generationSteps === stepRange.min}><Minus size={16} /></button>
              <div><strong>{generationSteps}</strong><span>סטפים</span></div>
              <button type="button" aria-label="הוספת סטפים" onClick={() => setGenerationSteps(generationSteps + 1)} disabled={generationSteps === stepRange.max}><Plus size={16} /></button>
            </div>
            <input className="steps-range" dir="ltr" type="range" min={stepRange.min} max={stepRange.max} step="1" value={generationSteps} onChange={event => setGenerationSteps(Number(event.target.value))} aria-label="מספר סטפים" />
            <div className="range-labels"><span>{stepRange.min}</span><span>{stepRange.max}</span></div>
          </div>

          <div className="setting-block resolution-block">
            <div className="setting-title"><span>רזולוציה</span><small>כפולות 32 שמתאימות ל־H3</small></div>
            <div className="aspect-grid">{aspectOptions.map(aspect => <button type="button" key={aspect} className={preferences.aspect === aspect ? 'active' : ''} onClick={() => setPreferences(current => ({ ...current, aspect }))}>{aspect}</button>)}</div>
            <label className="numeric-control"><span>Megapixels</span><input dir="ltr" type="number" min="0.1" max="2" step="0.01" value={preferences.megapixels} onChange={event => setPreferences(current => ({ ...current, megapixels: Math.max(0.1, Math.min(2, Number(event.target.value) || 0.1)) }))} /><small>׳׳×׳¨׳•׳× 0.1–2.0 · H3 מעגל לכפולות 32</small></label>
            <div className="calculated-resolution">{calculatedResolution.id} · {(calculatedResolution.width * calculatedResolution.height / 1_000_000).toFixed(2)} MP בפועל</div>
          </div>
        </div>

        <div className="generation-summary">
          <div className="profile-summary"><b dir="ltr">{engineLabel(effectiveEngine)}</b>{effectiveEngine === 'turbo' && <><i>·</i><b dir="ltr">{preferences.turboProfile.toUpperCase()}</b></>}<i>·</i><b dir="ltr">{encoderLabel(effectiveEncoder)}</b><i>·</i><b>{generationSteps} סטפים</b><i>·</i><b dir="ltr">{calculatedResolution.id}</b></div>
          <small>{loadLevel === 'normal' ? 'מוכן ליצירה' : 'לפני השליחה יוצג אישור עומס'}</small>
        </div>
      </div>

      <div className="final-row">
        <label className="duration-input"><span>משך בשניות</span><input dir="ltr" type="number" min="0.5" max="60" step="0.1" value={duration} onChange={event => setDuration(Math.max(0.5, Math.min(60, Number(event.target.value) || 0.5)))} /><small>H3 מעגל אוטומטית לפריים הקרוב</small></label>
        <button className="create-button" onClick={() => { void submit() }} disabled={sending} aria-busy={sending}><span>{sending ? 'שולח…' : connected ? `צור רצף של ${paragraphCount} שוטים` : batch ? `הוסף ${paragraphCount} לתור` : 'צור וידאו'}</span>{sending ? <LoaderCircle className="spin" size={19} /> : connected ? <Route size={18} /> : <Send size={18} />}</button>
      </div>
      {mode === 'reference' && !referenceReady && <p className="quiet-warning">מודל הרפרנס עדיין בהתקנה. פריימים וטקסט זמינים כרגיל.</p>}
      {mode === 'reference' && referenceReady && !reference10Ready && <p className="quiet-warning">רפרנס מעל 5 שניות ייפתח רק אחרי בדיקת עומס מוצלחת.</p>}
      {error && <div className="error-banner">{error}</div>}
    </section>

    <section className="queue-section">
      <div className="section-heading"><div><span>התור שלך</span><h2>{active.length || activeSequences.length ? 'היצירה בתנועה' : queued.length || queuedSequences.length ? 'ממתין ליצירה' : 'הכול שקט כרגע'}</h2></div><span className="queue-count">{active.length + queued.length + activeSequences.length + queuedSequences.length}</span></div>
      {!active.length && !queued.length && !activeSequences.length && !queuedSequences.length && <div className="empty"><div><Play size={22} /></div><p>הסרטון הבא שלך מתחיל בפרומפט למעלה</p></div>}
      {activeSequences.map(sequence => <SequenceCard key={sequence.id} sequence={sequence} onCancel={() => mutate(`/api/sequences/${sequence.id}/cancel`)} />)}
      {active.map(j => <JobCard key={j.id} job={j} onCancel={() => mutate(`/api/jobs/${j.id}/cancel`)} />)}
      {queuedTasks.map(task => task.kind === 'sequence'
        ? <SequenceCard key={task.sequence.id} sequence={task.sequence} onCancel={() => mutate(`/api/sequences/${task.sequence.id}/cancel`)} />
        : <JobCard key={task.job.id} job={task.job} index={queued.indexOf(task.job)} total={queued.length} onUp={() => move(task.job.id, -1)} onDown={() => move(task.job.id, 1)} onDelete={() => mutate(`/api/jobs/${task.job.id}`, 'DELETE')} />)}
    </section>

    {(!!history.length || !!sequenceHistory.length) && <section className="results-section">
      <div className="section-heading"><div><span>תוצאות</span><h2>הסרטונים האחרונים</h2></div><span className="selection-hint">בחר לפי סדר לחיבור</span></div>
      {!!selectedResults.length && <div className="join-dock">
        <div className="join-dock-head"><div><Combine size={18} /><span><strong>{selectedResults.length} קטעים נבחרו</strong><small>זה יהיה סדר החיבור</small></span></div><button type="button" onClick={() => setSelectedResults([])}>נקה</button></div>
        <div className="join-order">{selectedResults.map((reference, index) => <div className="join-chip" key={reference}><b>{index + 1}</b><span>{selectedResultLabel(reference)}</span><button type="button" onClick={() => moveSelectedResult(index, -1)} disabled={index === 0}><ArrowUp size={14} /></button><button type="button" onClick={() => moveSelectedResult(index, 1)} disabled={index === selectedResults.length - 1}><ArrowDown size={14} /></button><button type="button" onClick={() => toggleResult(reference)}><X size={14} /></button></div>)}</div>
        <button type="button" className="join-button" disabled={selectedResults.length < 2 || joining} onClick={() => { void joinSelected() }}>{joining ? <LoaderCircle className="spin" size={17} /> : <Combine size={17} />} {joining ? 'מוסיף לתור…' : 'חבר לסרטון אחד'}</button>
      </div>}
      {sequenceHistory.map(sequence => { const reference = `sequence:${sequence.id}`; const order = selectedResults.indexOf(reference) + 1; return <SequenceCard key={sequence.id} sequence={sequence} selectedOrder={order || undefined} onSelect={sequence.status === 'completed' ? () => toggleResult(reference) : undefined} onDelete={() => mutate(`/api/sequences/${sequence.id}`, 'DELETE')} /> })}
      {history.map(j => { const reference = `job:${j.id}`; const order = selectedResults.indexOf(reference) + 1; return <JobCard key={j.id} job={j} selectedOrder={order || undefined} onSelect={j.status === 'completed' ? () => toggleResult(reference) : undefined} onDelete={() => mutate(`/api/jobs/${j.id}`, 'DELETE')} /> })}
    </section>}
    <footer>H3 עובד מקומית · החיבור זמין רק ברשת הפרטית שלך</footer>

    {confirming && <div className="dialog-backdrop" onMouseDown={() => setConfirming(false)}>
      <section className="workload-dialog" role="dialog" aria-modal="true" aria-labelledby="workload-title" onMouseDown={event => event.stopPropagation()}>
        <div className="dialog-icon"><ShieldAlert size={22} /></div>
        <span className="dialog-eyebrow">בדיקה לפני התור</span>
        <h2 id="workload-title">{relativeLoad >= 2 ? 'ההגדרה הזו כבדה' : 'זה תור ארוך'}</h2>
        <p>המחשב עשוי לעבוד זמן רב ולהשתמש בהרבה זיכרון. אפשר להמשיך, או לחזור ולהוריד סטפים, משך או רזולוציה.</p>
        <div className="dialog-specs">
          <span>{engineLabel(effectiveEngine)}</span>
          {effectiveEngine === 'turbo' && <span>{preferences.turboProfile.toUpperCase()}</span>}
          <span>{encoderLabel(effectiveEncoder)}</span>
          <span>{generationSteps} סטפים</span>
          <span>{calculatedResolution.id}</span><span>{h3Frames} frames</span>
          <span>{duration} שנ׳</span>
          {batch && <span>{paragraphCount} משימות</span>}
        </div>
        <div className="dialog-actions">
          <button type="button" onClick={() => setConfirming(false)}>חזרה להגדרות</button>
          <button type="button" className="confirm" autoFocus onClick={() => { void submit(true) }}>הוסף בכל זאת</button>
        </div>
      </section>
    </div>}
    </>}
  </main>
}

function JobCard({ job, index, total, selectedOrder, onSelect, onUp, onDown, onDelete, onCancel }: { job: Job; index?: number; total?: number; selectedOrder?: number; onSelect?: () => void; onUp?: () => void; onDown?: () => void; onDelete?: () => void; onCancel?: () => void }) {
  const labels: Record<Status, string> = { queued: 'ממתין', starting: 'מפעיל מנוע', running: 'יוצר עכשיו', verifying: 'בודק וידאו', completed: 'מוכן', failed: 'נכשל', canceled: 'בוטל' }
  const phaseLabels: Record<Phase, string> = { queued: 'ממתין', starting: 'מפעיל מנוע', sampling: 'יוצר פריימים', processing: 'מעבד וידאו', verifying: 'בודק וידאו', completed: 'מוכן', failed: 'נכשל', canceled: 'בוטל' }
  const active = ['starting', 'running', 'verifying'].includes(job.status)
  const engine = job.engine || (job.mode === 'reference' ? 'standard' : 'turbo')
  const steps = job.steps || (engine === 'turbo' ? 4 : engine === 'spectrum' ? 16 : 20)
  const width = job.width || 736
  const height = job.height || 416
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])

  const phase = job.phase || job.status
  const hasStepProgress = phase === 'sampling' && (job.total_steps || 0) > 0
  const percent = Math.round(Math.max(0, Math.min(1, job.progress || 0)) * 100)
  const elapsedSeconds = job.started_at
    ? Math.max(0, (now - Date.parse(job.started_at)) / 1000)
    : undefined
  const share = async () => {
    if (!job.video_url) return
    const url = new URL(job.video_url, location.href).href
    if (navigator.share) await navigator.share({ title: 'H3 Video', url })
    else await navigator.clipboard.writeText(url)
  }
  return <article className={`job-card ${job.status} ${selectedOrder ? 'result-selected' : ''}`}>
    {selectedOrder && <span className="selection-order">{selectedOrder}</span>}
    {job.video_url && <video src={job.video_url} controls preload="metadata" playsInline style={{ aspectRatio: `${width}/${height}` }} />}
    <div className="job-body">
      <div className="job-head"><span className="status"><i />{labels[job.status]}</span><span>{job.duration} שנ׳ · {modeLabel(job.mode)}</span></div>
      <p>{job.prompt}</p>
      <div className="job-config"><span>{engineLabel(engine)}</span>{engine === 'turbo' && <span>{(job.turbo_profile || 'v1').toUpperCase()}</span>}<span>{encoderLabel(job.encoder || 'native')}</span><span>{steps} סטפים</span><span>{width}×{height}</span></div>
      {active && <div className="progress-shell">
        <div className={`progress ${hasStepProgress ? 'determinate' : 'indeterminate'}`} role="progressbar"
          aria-label="התקדמות יצירת הווידאו" aria-valuemin={hasStepProgress ? 0 : undefined}
          aria-valuemax={hasStepProgress ? 100 : undefined} aria-valuenow={hasStepProgress ? percent : undefined}>
          <span style={hasStepProgress ? { width: `${percent}%` } : undefined} />
        </div>
        <div className="progress-meta">
          <span>{phaseLabels[phase as Phase] || labels[job.status]}{hasStepProgress ? ` · ${percent}% · שלב ${job.step || 0}/${job.total_steps}` : ''}</span>
          <span>{elapsedSeconds !== undefined ? `עבר ${formatDuration(elapsedSeconds)}` : ''}{job.eta_seconds !== null && job.eta_seconds !== undefined ? ` · נשאר ~${formatDuration(job.eta_seconds)}` : ''}</span>
        </div>
      </div>}
      {job.error && <div className="job-error">{job.error}</div>}
      <div className="job-actions">
        {job.status === 'queued' && <><button onClick={onUp} disabled={index === 0}><ArrowUp size={17} /></button><button onClick={onDown} disabled={index === (total || 0) - 1}><ArrowDown size={17} /></button></>}
        {job.video_url && <><a href={job.video_url} download><Download size={17} /> הורדה</a><button onClick={share}><Link2 size={17} /> שיתוף</button></>}
        {onSelect && <button className={`select-result ${selectedOrder ? 'active' : ''}`} onClick={onSelect}><Check size={16} /> {selectedOrder ? `נבחר ${selectedOrder}` : 'בחר לחיבור'}</button>}
        {onCancel && <button className="danger" onClick={onCancel}>ביטול</button>}
        {onDelete && <button className="trash" onClick={onDelete} aria-label="מחיקה"><Trash2 size={17} /></button>}
        {job.metrics?.generation_seconds && <span className="elapsed">נוצר תוך {formatDuration(job.metrics.generation_seconds)}</span>}
      </div>
    </div>
  </article>
}

function SequenceCard({ sequence, selectedOrder, onSelect, onDelete, onCancel }: { sequence: Sequence; selectedOrder?: number; onSelect?: () => void; onDelete?: () => void; onCancel?: () => void }) {
  const labels: Record<Status, string> = { queued: 'ממתין', starting: 'מתחיל', running: 'יוצר רצף', verifying: 'מחבר וידאו', completed: 'מוכן', failed: 'נכשל', canceled: 'בוטל' }
  const active = ['starting', 'running', 'verifying'].includes(sequence.status)
  const percent = Math.round(Math.max(0, Math.min(1, sequence.progress || 0)) * 100)
  const width = sequence.width || 736
  const height = sequence.height || 416
  const share = async () => {
    if (!sequence.video_url) return
    const url = new URL(sequence.video_url, location.href).href
    if (navigator.share) await navigator.share({ title: 'H3 Long Video', url })
    else await navigator.clipboard.writeText(url)
  }
  return <article className={`job-card sequence-card ${sequence.status} ${selectedOrder ? 'result-selected' : ''}`}>
    {selectedOrder && <span className="selection-order">{selectedOrder}</span>}
    {sequence.video_url && <video src={sequence.video_url} controls preload="metadata" playsInline style={{ aspectRatio: `${width}/${height}` }} />}
    <div className="job-body">
      <div className="job-head"><span className="status"><i />{labels[sequence.status]}</span><span>{sequence.kind === 'connected' ? 'רצף פרומפטים' : 'חיבור מההיסטוריה'}</span></div>
      <div className="sequence-title"><Route size={17} /><p>{sequence.title}</p></div>
      <div className="job-config"><span>{sequence.total_items} קטעים</span>{sequence.engine && <span>{engineLabel(sequence.engine)}</span>}{sequence.encoder && <span>{encoderLabel(sequence.encoder)}</span>}{sequence.duration && <span>{sequence.duration} שנ׳ לשוט</span>}</div>
      {(active || sequence.status === 'queued') && <div className="progress-shell">
        <div className="progress determinate" role="progressbar" aria-label="התקדמות הרצף" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><span style={{ width: `${percent}%` }} /></div>
        <div className="progress-meta"><span>{sequence.phase === 'assembling' ? 'מחבר את הקטעים' : sequence.current_item ? `שוט ${sequence.current_item}/${sequence.total_items}` : 'ממתין להתחלה'} · {percent}%</span>{sequence.eta_seconds !== null && sequence.eta_seconds !== undefined && <span>נשאר ~{formatDuration(sequence.eta_seconds)}</span>}</div>
      </div>}
      {sequence.error && <div className="job-error">{sequence.error}</div>}
      <div className="job-actions">
        {sequence.video_url && <><a href={sequence.video_url} download><Download size={17} /> הורדה</a><button onClick={share}><Link2 size={17} /> שיתוף</button></>}
        {onSelect && <button className={`select-result ${selectedOrder ? 'active' : ''}`} onClick={onSelect}><Check size={16} /> {selectedOrder ? `נבחר ${selectedOrder}` : 'בחר לחיבור'}</button>}
        {onCancel && <button className="danger" onClick={onCancel}>ביטול</button>}
        {onDelete && <button className="trash" onClick={onDelete} aria-label="מחיקה"><Trash2 size={17} /></button>}
        {sequence.metrics?.assembly_seconds && <span className="elapsed">חובר תוך {formatDuration(sequence.metrics.assembly_seconds)}</span>}
      </div>
    </div>
  </article>
}

function formatDuration(totalSeconds: number) {
  const seconds = Math.max(0, Math.round(totalSeconds))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  if (hours) return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}

function modeLabel(mode: Mode) {
  if (mode === 'text') return 'טקסט'
  if (mode === 'frames') return 'פריים פותח + סוגר'
  if (mode === 'opening') return 'פריים פותח'
  if (mode === 'closing') return 'פריים סוגר'
  return 'רפרנס'
}

function engineLabel(engine: Engine | string) {
  if (engine === 'turbo') return 'Turbo'
  if (engine === 'spectrum') return 'Spectrum'
  return 'רגיל'
}

function encoderLabel(encoder: Encoder | string) {
  return encoder === 'clipproj' ? 'ClipProj 4B' : '32B מקורי'
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => undefined))
}
