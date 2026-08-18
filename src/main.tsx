import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ArrowDown, ArrowUp, AudioLines, BrainCircuit, Check, ChevronDown, ChevronLeft, Clapperboard, Combine, Copy, Download, Folder, FolderPlus, Gauge, Image as ImageIcon, Link2, LoaderCircle, Lock, Mic, Minus, Move, Pencil, Play, Plus, Power, RefreshCw, Route, Send, ShieldAlert, SlidersHorizontal, Sparkles, Square, Terminal, Trash2, X, Zap } from 'lucide-react'
import './styles.css'
import { ProductionStudio } from './production'

type Mode = 'text' | 'frames' | 'reference' | 'opening' | 'closing' | 'lip_sync'
type Engine = 'turbo' | 'standard' | 'spectrum'
type Encoder = 'native' | 'clipproj'
type TurboProfile = 'v1' | 'v4'
type Resolution = '512x288' | '736x416' | '864x480' | '768x768' | '1024x768' | '768x1024' | '1344x768' | '768x1344'
type Status = 'queued' | 'starting' | 'running' | 'verifying' | 'completed' | 'failed' | 'canceled'
type Phase = 'queued' | 'starting' | 'sampling' | 'processing' | 'verifying' | 'completed' | 'failed' | 'canceled'
type Page = 'studio' | 'production' | 'comfy'
type Job = {
  id: string; prompt: string; mode: Mode; duration: number; status: Status; progress: number;
  engine: Engine; turbo_profile?: TurboProfile; encoder: Encoder; steps: number; width: number; height: number; megapixels?: number; aspect_ratio?: string; position?: number;
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
  { id: 'frames', label: 'I2V', hint: 'פריים פותח · פריים סוגר אופציונלי' },
  { id: 'reference', label: 'רפרנס', hint: 'זהות וסגנון מהתמונה' },
  { id: 'lip_sync', label: 'דיבוב', hint: 'אודיו מדויק · פריים פותח אופציונלי' },
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
  { id: '1344x768', label: '16:9 טבעי', hint: '1344×768 · 1.03MP', width: 1344, height: 768, aspect: '16:9', megapixels: 1.03 },
  { id: '768x1344', label: '9:16 טבעי', hint: '768×1344 · 1.03MP', width: 768, height: 1344, aspect: '9:16', megapixels: 1.03 },
]
const aspectOptions: Aspect[] = ['1:1', '4:3', '3:4', '16:9', '9:16']

function dimensionsFor(aspect: Aspect, megapixels: number) {
  const ratios: Record<Aspect, number> = { '1:1': 1, '4:3': 4 / 3, '3:4': 3 / 4, '16:9': 16 / 9, '9:16': 9 / 16 }
  const ratio = ratios[aspect]
  const width = Math.max(256, Math.round(Math.sqrt(megapixels * 1_000_000 * ratio) / 32) * 32)
  const height = Math.max(256, Math.round(Math.sqrt(megapixels * 1_000_000 / ratio) / 32) * 32)
  return { width, height, id: `${width}x${height}` as Resolution }
}

type LibraryFolder = { id: string; project_id: string; name: string }
type LibraryProject = { id: string; name: string; asset_count: number; folders: LibraryFolder[] }
type AssetAssignment = { source_type: 'job'|'sequence'; source_id: string; project_id: string; project_name: string; folder_id?: string|null; folder_name?: string|null; filename?: string|null }
type AssetLibrary = { root: string; projects: LibraryProject[]; assignments: AssetAssignment[] }
type ResultAsset =
  | { kind: 'job'; id: string; created_at: string; job: Job }
  | { kind: 'sequence'; id: string; created_at: string; sequence: Sequence }

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
  label?: string
  hint?: string
  disabled?: boolean
}

function AudioDropzone({ file, onChange, label = 'הוסף אודיו לרפרנס', hint = 'WAV, MP3, M4A, AAC, FLAC, OGG או WebM · עד 50MB', disabled = false }: AudioDropzoneProps) {
  return <label className={`dropzone audio-dropzone ${file ? 'has-audio' : ''}`}>
    <input type="file" disabled={disabled} accept="audio/wav,audio/x-wav,audio/mpeg,audio/mp4,audio/x-m4a,audio/aac,audio/flac,audio/ogg,audio/webm" onChange={e => onChange(e.target.files?.[0] || null)} />
    {file ? <><AudioLines size={24} /><strong dir="auto">{file.name}</strong><span>{(file.size / 1024 / 1024).toFixed(1)}MB</span><button type="button" aria-label="הסרת אודיו" onClick={e => { e.preventDefault(); e.stopPropagation(); onChange(null) }}><X size={17} /></button></> : <><AudioLines size={24} /><strong>{label}</strong><span>{hint}</span></>}
  </label>
}

function MultiImageDropzone({ files, onChange }: { files: File[]; onChange: (files: File[]) => void }) {
  return <label className={`dropzone multi-dropzone ${files.length ? 'has-image' : ''}`}>
    <input type="file" multiple accept="image/jpeg,image/png,image/webp" onChange={event => onChange(Array.from(event.target.files || []))} />
    {files.length ? <><ImageIcon size={24} /><strong>{files.length} תמונות רפרנס</strong><span>עד 9 תמונות · JPG, PNG או WebP</span><button type="button" aria-label="הסרת תמונות" onClick={event => { event.preventDefault(); event.stopPropagation(); onChange([]) }}><X size={17} /></button></> : <><ImageIcon size={24} /><strong>הוסף תמונות רפרנס</strong><span>אפשר לבחור עד 9 תמונות</span></>}
  </label>
}

function VideoDropzone({ files, onChange }: { files: File[]; onChange: (files: File[]) => void }) {
  return <label className={`dropzone multi-dropzone ${files.length ? 'has-image' : ''}`}>
    <input type="file" multiple accept="video/mp4,video/quicktime,video/webm,video/x-matroska,video/mpeg" onChange={event => onChange(Array.from(event.target.files || []))} />
    {files.length ? <><Clapperboard size={24} /><strong>{files.length} סרטוני רפרנס</strong><span>עד 3 סרטונים · 2–15 שניות לכל סרטון</span><button type="button" aria-label="הסרת סרטונים" onClick={event => { event.preventDefault(); event.stopPropagation(); onChange([]) }}><X size={17} /></button></> : <><Clapperboard size={24} /><strong>הוסף סרטוני רפרנס</strong><span>אפשר לבחור עד 3 סרטונים · 2–15 שניות</span></>}
  </label>
}

type ComfyPageProps = { running: boolean; busy: boolean; lines: string[]; error: string; onRefresh: () => void }

function ComfyPage({ running, busy, lines, error, onRefresh, onClear }: ComfyPageProps & { onClear: () => void }) {
  return <section className="comfy-page">
    <div className="comfy-page-heading"><div><span className="eyebrow"><Terminal size={15} /> ComfyUI</span><h2>ComfyUI logs</h2></div><div className="log-actions"><button className="icon-button" onClick={onClear} aria-label="Clear visible log" title="Clear visible log"><Trash2 size={17} /></button><button className="icon-button" onClick={onRefresh} aria-label="Refresh log" title="Refresh log"><RefreshCw size={18} /></button></div></div>
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
  const [referenceImages, setReferenceImages] = useState<File[]>([])
  const [referenceVideos, setReferenceVideos] = useState<File[]>([])
  const [referenceAudio, setReferenceAudio] = useState<File | null>(null)
  const [lipSyncAudio, setLipSyncAudio] = useState<File | null>(null)
  const [lipSyncAudioDuration, setLipSyncAudioDuration] = useState<number | null>(null)
  const [lipSyncAudioPreview, setLipSyncAudioPreview] = useState('')
  const [audioTrimStart, setAudioTrimStart] = useState(0)
  const lipSyncAudioElementRef = useRef<HTMLAudioElement | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [recordingSeconds, setRecordingSeconds] = useState(0)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const recordingStreamRef = useRef<MediaStream | null>(null)
  const recordingChunksRef = useRef<Blob[]>([])
  const recordingStartedAtRef = useRef(0)
  const discardRecordingRef = useRef(false)
  const [openingFrame, setOpeningFrame] = useState<File | null>(null)
  const [closingFrame, setClosingFrame] = useState<File | null>(null)
  const [openingPreview, setOpeningPreview] = useState('')
  const [closingPreview, setClosingPreview] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [referenceReady, setReferenceReady] = useState(false)
  const [reference10Ready, setReference10Ready] = useState(false)
  const [spectrumReady, setSpectrumReady] = useState(false)
  const [clipprojReady, setClipprojReady] = useState(false)
  const [turboV4Ready, setTurboV4Ready] = useState(false)
  const [referenceTurboReady, setReferenceTurboReady] = useState(false)
  const [audioLockReady, setAudioLockReady] = useState(false)
  const [gpuConflict, setGpuConflict] = useState(false)
  const [gpuBusy, setGpuBusy] = useState(false)
  const [noAudio, setNoAudio] = useState(false)
  const [selectedResults, setSelectedResults] = useState<string[]>([])
  const [joining, setJoining] = useState(false)
  const [comfyRunning, setComfyRunning] = useState(false)
  const [comfyBusy, setComfyBusy] = useState(false)
  const [comfyLogs, setComfyLogs] = useState<string[]>([])
  const [comfyLogCleared, setComfyLogCleared] = useState(false)
  const [comfyError, setComfyError] = useState('')
  const [library, setLibrary] = useState<AssetLibrary>({ root: '', projects: [], assignments: [] })
  const [destinationProject, setDestinationProject] = useState('')
  const [destinationFolder, setDestinationFolder] = useState('')
  const [libraryProject, setLibraryProject] = useState('all')
  const [libraryFolder, setLibraryFolder] = useState('all')
  const [editingAsset, setEditingAsset] = useState<{ type: 'job'|'sequence'; id: string; label: string } | null>(null)
  const [editProject, setEditProject] = useState('')
  const [editFolder, setEditFolder] = useState('')
  const [editFilename, setEditFilename] = useState('')
  const [collapsedAssetGroups, setCollapsedAssetGroups] = useState<Record<string, boolean>>({})

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
      setReferenceTurboReady(data.reference_turbo_ready)
      setAudioLockReady(Boolean(data.audio_lock_ready))
      setGpuConflict(Boolean(data.gpu_conflict))
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
        setJobs(data.jobs); setSequences(data.sequences || []); setLibrary(data.library || { root: '', projects: [], assignments: [] }); setReferenceReady(data.reference_ready); setReference10Ready(data.reference_10s_ready); setSpectrumReady(data.spectrum_ready); setClipprojReady(data.clipproj_ready); setTurboV4Ready(data.turbo_v4_ready); setReferenceTurboReady(data.reference_turbo_ready); setGpuConflict(Boolean(data.gpu_conflict))
        setAudioLockReady(Boolean(data.audio_lock_ready))
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

  const loadComfy = async (forceLogs = false) => {
    try {
      const [statusResponse, logsResponse] = await Promise.all([
        fetch('/api/comfy/status', { cache: 'no-store' }),
        fetch('/api/comfy/logs?tail=400', { cache: 'no-store' }),
      ])
      if (!statusResponse.ok || !logsResponse.ok) throw new Error('ComfyUI status unavailable')
      const status = await statusResponse.json()
      const logs = await logsResponse.json()
      setComfyRunning(Boolean(status.running))
      if (forceLogs || !comfyLogCleared) setComfyLogs(Array.isArray(logs.lines) ? logs.lines : [])
      setComfyError('')
    } catch {
      setComfyError('Unable to read ComfyUI status')
    }
  }

  const releaseRecordingStream = () => {
    recordingStreamRef.current?.getTracks().forEach(track => track.stop())
    recordingStreamRef.current = null
  }

  const stopRecording = () => {
    const recorder = recorderRef.current
    if (!recorder) return
    if (recorder.state === 'inactive') {
      releaseRecordingStream()
      recorderRef.current = null
      setIsRecording(false)
      return
    }
    recorder.stop()
  }

  const cancelRecording = () => {
    discardRecordingRef.current = true
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
      return
    }
    releaseRecordingStream()
    recorderRef.current = null
    setIsRecording(false)
    setRecordingSeconds(0)
  }

  const startRecording = async () => {
    if (isRecording) return
    setError('')
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('הדפדפן הזה לא תומך בהקלטה מהמיקרופון')
      return
    }
    let stream: MediaStream | null = null
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeCandidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg']
      const mimeType = mimeCandidates.find(candidate => MediaRecorder.isTypeSupported(candidate)) || ''
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      const recordedMimeType = mimeType || 'audio/webm'
      recordingChunksRef.current = []
      recordingStartedAtRef.current = Date.now()
      discardRecordingRef.current = false
      recordingStreamRef.current = stream
      recorderRef.current = recorder
      recorder.ondataavailable = event => {
        if (event.data.size > 0) recordingChunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        const shouldDiscard = discardRecordingRef.current
        discardRecordingRef.current = false
        const chunks = recordingChunksRef.current
        recordingChunksRef.current = []
        const seconds = Math.min(60, Math.max(0, (Date.now() - recordingStartedAtRef.current) / 1000))
        const baseMimeType = (recorder.mimeType || recordedMimeType).split(';')[0] || 'audio/webm'
        recorderRef.current = null
        releaseRecordingStream()
        setIsRecording(false)
        setRecordingSeconds(seconds)
        if (shouldDiscard) return
        if (seconds < 0.5 || !chunks.length) {
          setError('ההקלטה קצרה מדי. הקליטי לפחות חצי שנייה')
          return
        }
        const blob = new Blob(chunks, { type: baseMimeType })
        const extension = baseMimeType.includes('ogg') ? 'ogg' : 'webm'
        const file = new File([blob], `lip-sync-recording-${Date.now()}.${extension}`, { type: baseMimeType })
        setLipSyncAudio(file)
        setAudioTrimStart(0)
        setError('')
      }
      recorder.onerror = () => {
        discardRecordingRef.current = true
        setError('ההקלטה נכשלה. בדקי שהמיקרופון זמין ונסי שוב')
        if (recorder.state !== 'inactive') recorder.stop()
      }
      recorder.start(250)
      setRecordingSeconds(0)
      setIsRecording(true)
    } catch {
      stream?.getTracks().forEach(track => track.stop())
      setError('אין גישה למיקרופון. אפשרי הרשאת מיקרופון בדפדפן ונסי שוב')
    }
  }

  useEffect(() => {
    if (!isRecording) return
    const timer = window.setInterval(() => {
      const elapsed = (Date.now() - recordingStartedAtRef.current) / 1000
      if (elapsed >= 59.8) {
        setRecordingSeconds(60)
        stopRecording()
        return
      }
      setRecordingSeconds(elapsed)
    }, 200)
    return () => window.clearInterval(timer)
  }, [isRecording])

  useEffect(() => () => {
    discardRecordingRef.current = true
    if (recorderRef.current && recorderRef.current.state !== 'inactive') recorderRef.current.stop()
    releaseRecordingStream()
  }, [])

  useEffect(() => {
    void loadComfy()
    const timer = window.setInterval(() => { void loadComfy() }, 2000)
    return () => window.clearInterval(timer)
  }, [comfyLogCleared])

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
    if (!lipSyncAudio) {
      setLipSyncAudioPreview('')
      setLipSyncAudioDuration(null)
      setAudioTrimStart(0)
      return
    }
    const url = URL.createObjectURL(lipSyncAudio)
    setLipSyncAudioPreview(url)
    const probe = new Audio()
    probe.preload = 'metadata'
    probe.onloadedmetadata = () => {
      if (Number.isFinite(probe.duration) && probe.duration > 0) {
        const nextDuration = Math.max(0.5, Math.min(60, probe.duration))
        setLipSyncAudioDuration(probe.duration)
        setDuration(current => Math.min(current, Math.round(nextDuration * 10) / 10))
      }
    }
    probe.src = url
    return () => {
      probe.removeAttribute('src')
      probe.load()
      URL.revokeObjectURL(url)
    }
  }, [lipSyncAudio])

  useEffect(() => {
    if (mode !== 'lip_sync' || !lipSyncAudioDuration) return
    const maxStart = Math.max(0, lipSyncAudioDuration - duration)
    setAudioTrimStart(current => Math.min(Math.max(0, current), maxStart))
  }, [mode, lipSyncAudioDuration, duration])

  const audioPreviewIsTrimmed = mode === 'lip_sync' && !!lipSyncAudioDuration && lipSyncAudioDuration > duration + 0.08
  const audioPreviewEnd = audioPreviewIsTrimmed && lipSyncAudioDuration
    ? Math.min(lipSyncAudioDuration, audioTrimStart + duration)
    : null
  const syncLipSyncAudioPreview = () => {
    const audio = lipSyncAudioElementRef.current
    if (!audio || !audioPreviewIsTrimmed || audioPreviewEnd === null) return
    if (audio.currentTime < audioTrimStart || audio.currentTime >= audioPreviewEnd) audio.currentTime = audioTrimStart
  }
  const stopAtLipSyncAudioPreviewEnd = () => {
    const audio = lipSyncAudioElementRef.current
    if (!audio || !audioPreviewIsTrimmed || audioPreviewEnd === null) return
    if (audio.currentTime >= audioPreviewEnd - 0.02) {
      audio.pause()
      audio.currentTime = audioTrimStart
    }
  }

  useEffect(() => {
    const audio = lipSyncAudioElementRef.current
    if (!audio || mode !== 'lip_sync') return
    audio.pause()
    if (audioPreviewIsTrimmed) audio.currentTime = audioTrimStart
  }, [mode, lipSyncAudioPreview, audioPreviewIsTrimmed, audioTrimStart, duration])

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
  const effectiveEngine: Engine = mode === 'lip_sync' ? 'standard' : mode === 'reference' && preferences.engine === 'turbo' && !referenceTurboReady ? 'standard' : preferences.engine
  const effectiveEncoder: Encoder = mode === 'lip_sync' ? 'native' : preferences.encoder
  const generationSteps = mode === 'reference' && effectiveEngine === 'turbo' ? 4 : effectiveEngine === 'turbo' ? preferences.turboSteps : effectiveEngine === 'spectrum' ? preferences.spectrumSteps : preferences.standardSteps
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
  const assignmentFor = (type: 'job'|'sequence', id: string) => library.assignments.find(item => item.source_type === type && item.source_id === id)
  const assetVisible = (type: 'job'|'sequence', id: string) => {
    const assignment = assignmentFor(type, id)
    if (libraryProject === 'all') return true
    if (libraryProject === 'unassigned') return !assignment
    if (assignment?.project_id !== libraryProject) return false
    return libraryFolder === 'all' || (libraryFolder === 'root' ? !assignment.folder_id : assignment.folder_id === libraryFolder)
  }
  const visibleHistory = history.filter(job => assetVisible('job', job.id))
  const visibleSequenceHistory = sequenceHistory.filter(sequence => assetVisible('sequence', sequence.id))
  const visibleResultAssets: ResultAsset[] = [
    ...visibleHistory.map(job => ({ kind: 'job' as const, id: job.id, created_at: job.created_at, job })),
    ...visibleSequenceHistory.map(sequence => ({ kind: 'sequence' as const, id: sequence.id, created_at: sequence.created_at, sequence })),
  ].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
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

  const jsonBody = (value: unknown) => new Blob([JSON.stringify(value)], { type: 'application/json' })

  const createStudioProject = async () => {
    const name = window.prompt('Project name — this exact name will be used for its Windows folder:')?.trim()
    if (!name) return
    try {
      const created = await mutate('/api/library/projects', 'POST', jsonBody({ name }))
      setLibraryProject(created.id); setLibraryFolder('all'); setDestinationProject(created.id); setDestinationFolder('')
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not create project') }
  }

  const createStudioFolder = async (projectId: string) => {
    const name = window.prompt('Folder name — this exact name will be used on disk:')?.trim()
    if (!name) return
    try { await mutate(`/api/library/projects/${projectId}/folders`, 'POST', jsonBody({ name })) }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not create folder') }
  }

  const renameStudioProject = async (project: LibraryProject) => {
    const name = window.prompt('Rename project and its filesystem folder:', project.name)?.trim()
    if (!name || name === project.name) return
    try { await mutate(`/api/library/projects/${project.id}`, 'PATCH', jsonBody({ name })) }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not rename project') }
  }

  const renameStudioFolder = async (project: LibraryProject, folder: LibraryFolder) => {
    const name = window.prompt('Rename folder on disk:', folder.name)?.trim()
    if (!name || name === folder.name) return
    try { await mutate(`/api/library/projects/${project.id}/folders/${folder.id}`, 'PATCH', jsonBody({ name })) }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not rename folder') }
  }

  const deleteStudioProject = async (project: LibraryProject) => {
    if (!window.confirm(`Delete the empty project “${project.name}” and its filesystem folder?`)) return
    try { await mutate(`/api/library/projects/${project.id}`, 'DELETE'); setLibraryProject('all'); setLibraryFolder('all') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not delete project') }
  }

  const deleteStudioFolder = async (project: LibraryProject, folder: LibraryFolder) => {
    if (!window.confirm(`Delete the empty folder “${folder.name}” from project “${project.name}”?`)) return
    try { await mutate(`/api/library/projects/${project.id}/folders/${folder.id}`, 'DELETE'); setLibraryFolder('all') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not delete folder') }
  }

  const openAssetEditor = (type: 'job'|'sequence', id: string, label: string) => {
    const assignment = assignmentFor(type, id)
    setEditingAsset({ type, id, label })
    setEditProject(assignment?.project_id || '')
    setEditFolder(assignment?.folder_id || '')
    setEditFilename(assignment?.filename?.replace(/\.mp4$/i, '') || '')
  }

  const saveAssetLocation = async () => {
    if (!editingAsset) return
    try {
      const original = assignmentFor(editingAsset.type, editingAsset.id)
      const currentBase = original?.filename?.replace(/\.mp4$/i, '') || ''
      await mutate(`/api/library/assets/${editingAsset.type}/${editingAsset.id}/location`, 'PATCH', jsonBody({ project_id: editProject || null, folder_id: editProject ? editFolder || null : null }))
      if (editProject && editFilename.trim() && editFilename.trim() !== currentBase) {
        await mutate(`/api/library/assets/${editingAsset.type}/${editingAsset.id}/name`, 'PATCH', jsonBody({ name: editFilename.trim() }))
      }
      setEditingAsset(null)
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not organize asset') }
  }

  const deleteGeneratedAsset = async (type: 'job'|'sequence', id: string, label: string) => {
    if (!window.confirm(`Delete “${label}”? This permanently deletes the actual video file from disk.`)) return
    try { await mutate(type === 'job' ? `/api/jobs/${id}` : `/api/sequences/${id}`, 'DELETE') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not delete asset') }
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

  const closeFortnite = async () => {
    if (gpuBusy || !window.confirm('Close Fortnite to free the GPU for ComfyUI?')) return
    setGpuBusy(true)
    try {
      const sessionToken = csrf || await loadSession()
      if (!sessionToken) throw new Error('The server session is not ready')
      const response = await fetch('/api/gpu/fortnite/stop', { method: 'POST', headers: { 'X-CSRF-Token': sessionToken } })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || 'Fortnite could not be closed')
      setGpuConflict(Boolean(data.gpu_conflict))
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fortnite could not be closed')
    } finally { setGpuBusy(false) }
  }

  const lockComputer = async () => {
    if (!window.confirm('Lock this Windows PC now?')) return
    try {
      const sessionToken = csrf || await loadSession()
      if (!sessionToken) throw new Error('The server session is not ready')
      const response = await fetch('/api/system/lock', { method: 'POST', headers: { 'X-CSRF-Token': sessionToken } })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || 'The PC could not be locked')
    } catch (e) { setError(e instanceof Error ? e.message : 'The PC could not be locked') }
  }

  const selectMode = (next: Mode) => {
    if (next === 'lip_sync' && !audioLockReady) {
      setError('מצב דיבוב עדיין לא מוכן. הפעילי מחדש את ComfyUI אחרי התקנת Native AudioLock')
      return
    }
    if (next !== 'lip_sync' && isRecording) cancelRecording()
    setMode(next)
    setError('')
    if (next !== 'text') setConnected(false)
    if (next !== 'lip_sync') setLipSyncAudio(null)
    if (next === 'frames') { setReferenceImages([]); setReferenceVideos([]); setReferenceAudio(null); setLipSyncAudio(null) }
    else if (next === 'opening') {
      setClosingFrame(null)
      setReferenceImages([]); setReferenceVideos([]); setReferenceAudio(null); setLipSyncAudio(null)
    }
    else if (next === 'lip_sync') {
      setClosingFrame(null)
      setReferenceImages([]); setReferenceVideos([]); setReferenceAudio(null); setNoAudio(false)
      setPreferences(current => ({ ...current, engine: 'standard', encoder: 'native', aspect: '16:9', megapixels: Math.max(current.megapixels, 0.41) }))
      setBatch(false)
    }
    else if (next === 'reference') {
      setOpeningFrame(null)
      setClosingFrame(null)
      setLipSyncAudio(null)
    } else if (next === 'text') {
      setReferenceImages([])
      setReferenceVideos([])
      setReferenceAudio(null)
      setOpeningFrame(null)
      setClosingFrame(null)
      setLipSyncAudio(null)
    }
  }

  const selectEngine = (engine: Engine) => {
    if (mode === 'lip_sync') return
    if (mode === 'reference' && engine === 'turbo' && !referenceTurboReady) return
    if (engine === 'spectrum' && !spectrumReady) return
    setPreferences(current => ({ ...current, engine }))
  }

  const selectEncoder = (encoder: Encoder) => {
    if (mode === 'lip_sync') return
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
    if (!prompt.trim() && mode !== 'lip_sync') return setError('צריך לכתוב פרומפט')
    if (mode === 'frames' && !openingFrame) return setError('צריך לצרף פריים פותח')
    if (mode === 'lip_sync' && !audioLockReady) return setError('Native AudioLock עדיין לא נטען ב־ComfyUI')
    if (mode === 'lip_sync' && !lipSyncAudio) return setError('צריך לצרף אודיו לדיבוב')
    if (mode === 'lip_sync' && lipSyncAudioDuration && audioTrimStart + duration > lipSyncAudioDuration + 0.08) return setError('הקטע שנבחר קצר מדי למשך הג׳נרוט')
    if (mode === 'reference' && !referenceImages.length && !referenceVideos.length) return setError('צריך לצרף לפחות תמונת או סרטון רפרנס')
    if (batch && paragraphCount > 20) return setError('אפשר להוסיף עד 20 פרומפטים יחד')
    if (connected && (!batch || mode !== 'text' || paragraphCount < 2)) return setError('רצף מחובר דורש לפחות שני פרומפטים במצב טקסט')
    if (effectiveEncoder === 'clipproj' && !clipprojReady) return setError('ClipProj עדיין לא מוכן להפעלה')
    if (!confirmed && needsConfirmation) { setConfirming(true); return }
    const sessionToken = csrf || await loadSession()
    if (!sessionToken) return setError('החיבור לשרת עדיין מתחבר. נסי שוב בעוד רגע')
    const form = new FormData()
    const requestPrompt = prompt.trim() || 'Use the supplied audio with natural, precise lip-sync. Keep the face and camera stable.'
    form.set('prompt', requestPrompt); form.set('mode', mode); form.set('duration', String(duration)); form.set('batch', String(batch && mode !== 'lip_sync'))
    form.set('engine', effectiveEngine); form.set('encoder', effectiveEncoder); form.set('steps', String(generationSteps)); form.set('megapixels', String(preferences.megapixels)); form.set('aspect_ratio', preferences.aspect); form.set('connected', String(connected)); form.set('no_audio', String(noAudio))
    if (destinationProject) { form.set('project_id', destinationProject); if (destinationFolder) form.set('folder_id', destinationFolder) }
    if (effectiveEngine === 'turbo' && mode !== 'reference') form.set('turbo_profile', preferences.turboProfile)
    if (mode === 'frames') {
      form.set('first_frame', openingFrame!)
      if (closingFrame) form.set('last_frame', closingFrame)
    } else if (mode === 'lip_sync') {
      if (openingFrame) form.set('first_frame', openingFrame)
      form.set('audio', lipSyncAudio!)
      form.set('audio_start', String(audioTrimStart))
    } else if (mode === 'reference') {
      referenceImages.forEach(file => form.append('reference_images', file))
      referenceVideos.forEach(file => form.append('reference_videos', file))
      if (referenceAudio) form.set('reference_audio', referenceAudio)
    }
    setConfirming(false)
    setSending(true)
    try {
      await mutate('/api/jobs', 'POST', form, sessionToken)
      setPrompt(''); setReferenceImages([]); setReferenceVideos([]); setReferenceAudio(null); setLipSyncAudio(null); setOpeningFrame(null); setClosingFrame(null); setBatch(false); setConnected(false); setAudioTrimStart(0)
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

  const toggleAssetGroup = (key: string) => setCollapsedAssetGroups(current => ({ ...current, [key]: !current[key] }))

  const renderResultAsset = (asset: ResultAsset) => {
    if (asset.kind === 'sequence') {
      const { sequence } = asset
      const reference = `sequence:${sequence.id}`
      const order = selectedResults.indexOf(reference) + 1
      return <SequenceCard key={reference} sequence={sequence} assignment={assignmentFor('sequence', sequence.id)} selectedOrder={order || undefined} onSelect={sequence.status === 'completed' ? () => toggleResult(reference) : undefined} onManage={sequence.status === 'completed' ? () => openAssetEditor('sequence', sequence.id, sequence.title) : undefined} onDelete={() => { void deleteGeneratedAsset('sequence', sequence.id, sequence.title) }} />
    }
    const { job } = asset
    const reference = `job:${job.id}`
    const order = selectedResults.indexOf(reference) + 1
    return <JobCard key={reference} job={job} assignment={assignmentFor('job', job.id)} selectedOrder={order || undefined} onSelect={job.status === 'completed' ? () => toggleResult(reference) : undefined} onManage={job.status === 'completed' ? () => openAssetEditor('job', job.id, job.prompt.slice(0, 100)) : undefined} onDelete={() => { void deleteGeneratedAsset('job', job.id, job.prompt.slice(0, 80)) }} />
  }

  const renderAssetContainer = (key: string, title: string, assets: ResultAsset[], level: 'project'|'folder'|'unassigned', children?: React.ReactNode) => {
    const collapsed = !!collapsedAssetGroups[key]
    return <section className={`asset-result-container ${level}`} key={key}>
      <button type="button" className="asset-container-toggle" onClick={() => toggleAssetGroup(key)} aria-expanded={!collapsed}>
        {collapsed ? <ChevronLeft size={17}/> : <ChevronDown size={17}/>}
        <Folder size={17}/><strong>{title}</strong><span>{assets.length} נכסים</span>
      </button>
      {!collapsed && <div className="asset-container-content">{children || assets.map(renderResultAsset)}</div>}
    </section>
  }

  const renderProjectResults = (project: LibraryProject, assets: ResultAsset[]) => {
    const rootAssets = assets.filter(asset => { const assignment = assignmentFor(asset.kind, asset.id); return assignment?.project_id === project.id && !assignment.folder_id })
    const folderGroups = project.folders.map(folder => ({ folder, assets: assets.filter(asset => assignmentFor(asset.kind, asset.id)?.folder_id === folder.id) }))
      .filter(group => group.assets.length || libraryProject === project.id)
    const content = <>
      {!!rootAssets.length && renderAssetContainer(`root:${project.id}`, 'שורש הפרויקט', rootAssets, 'folder')}
      {folderGroups.map(group => renderAssetContainer(`folder:${group.folder.id}`, group.folder.name, group.assets, 'folder'))}
      {!rootAssets.length && !folderGroups.length && <div className="asset-container-empty">אין נכסים בפרויקט הזה.</div>}
    </>
    return renderAssetContainer(`project:${project.id}`, project.name, assets, 'project', content)
  }

  return <main className={`shell ${page === 'production' ? 'production-shell-host' : ''}`}>
    <header className="topbar">
      <div className="brand-mark"><Clapperboard size={22} /></div>
      <div><h1>H3 Studio</h1><p>יוצרים וידאו מהמחשב שלך</p></div>
      <div className="topbar-actions">
        <button className={`comfy-status-button ${comfyRunning ? 'running' : ''}`} onClick={() => setPage('comfy')}><i /> <span>{comfyRunning ? 'ComfyUI running' : 'ComfyUI stopped'}</span></button>
        <button className="comfy-control-button" onClick={() => { void controlComfy(comfyRunning ? 'stop' : 'start') }} disabled={comfyBusy} aria-label={comfyRunning ? 'Stop ComfyUI' : 'Start ComfyUI'}>{comfyBusy ? <LoaderCircle className="spin" size={16} /> : comfyRunning ? <Square size={15} /> : <Power size={16} />}</button>
        <button className="comfy-control-button lock-button" onClick={() => { void lockComputer() }} aria-label="Lock Windows PC" title="Lock Windows PC"><Lock size={15} /></button>
        <button className="icon-button" onClick={() => { if (page === 'comfy') { setComfyLogCleared(false); void loadComfy(true) } else { void loadSession(); void load() } }} aria-label="רענון"><RefreshCw size={18} /></button>
      </div>
    </header>
    <nav className="page-tabs" aria-label="Navigation"><button className={page === 'studio' ? 'active' : ''} onClick={() => setPage('studio')}><Clapperboard size={15} /> Studio</button><button className={page === 'production' ? 'active' : ''} onClick={() => setPage('production')}><Sparkles size={15} /> Production</button><button className={page === 'comfy' ? 'active' : ''} onClick={() => setPage('comfy')}><Terminal size={15} /> ComfyUI logs</button></nav>
    {gpuConflict && <div className="gpu-conflict-note"><ShieldAlert size={16} /><div><span>Fortnite is running and may use the GPU. Generation can become slow or stall; close Fortnite before starting ComfyUI jobs.</span><button type="button" className="gpu-close-button" onClick={() => { void closeFortnite() }} disabled={gpuBusy}>{gpuBusy ? 'Closing…' : 'Close Fortnite'}</button></div></div>}
    {page === 'comfy' ? <ComfyPage running={comfyRunning} busy={comfyBusy} lines={comfyLogs} error={comfyError} onClear={() => { setComfyLogCleared(true); setComfyLogs([]) }} onRefresh={() => { setComfyLogCleared(false); void loadComfy(true) }} /> : page === 'production' ? <ProductionStudio csrf={csrf} /> : <>

    <section className="asset-library-panel">
      <div className="asset-library-head"><div><span className="eyebrow"><Folder size={15}/> Asset library</span><h2>Projects and folders</h2><small dir="ltr">{library.root || 'state/projects'}</small></div><button type="button" onClick={() => { void createStudioProject() }}><FolderPlus size={16}/> New project</button></div>
      <div className="asset-library-toolbar"><label><span>Show assets</span><select value={libraryProject} onChange={event => { setLibraryProject(event.target.value); setLibraryFolder('all') }}><option value="all">All assets</option><option value="unassigned">Unassigned</option>{library.projects.map(project => <option key={project.id} value={project.id}>{project.name} ({project.asset_count})</option>)}</select></label>{!['all','unassigned'].includes(libraryProject) && <label><span>Folder</span><select value={libraryFolder} onChange={event => setLibraryFolder(event.target.value)}><option value="all">All folders</option><option value="root">Project root</option>{library.projects.find(project => project.id === libraryProject)?.folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label>}</div>
      {!['all','unassigned'].includes(libraryProject) && (() => { const project=library.projects.find(item=>item.id===libraryProject); return project ? <div className="asset-project-detail"><div className="asset-project-title"><div className="asset-project-label"><b>{project.name}</b><span>{project.asset_count} assets</span></div><div className="asset-project-actions"><button onClick={() => { void createStudioFolder(project.id) }}><FolderPlus size={14}/> Folder</button><button onClick={() => { void renameStudioProject(project) }}><Pencil size={13}/> Rename</button><button className="danger" onClick={() => { void deleteStudioProject(project) }}><Trash2 size={13}/></button></div></div><div className="asset-folder-list">{project.folders.map(folder => <div key={folder.id}><div className="asset-folder-name"><Folder size={14}/><span>{folder.name}</span></div><div className="asset-folder-actions"><button onClick={() => { void renameStudioFolder(project,folder) }}><Pencil size={12}/></button><button onClick={() => { void deleteStudioFolder(project,folder) }}><Trash2 size={12}/></button></div></div>)}{!project.folders.length && <small>No folders yet. Assets can still be stored in the project root.</small>}</div></div> : null })()}
    </section>

    <section className="composer">
      <div className="eyebrow"><Sparkles size={15} /> יצירה חדשה</div>
      <div className="generation-destination"><Folder size={16}/><label><span>Save new results in project</span><select value={destinationProject} onChange={event => { setDestinationProject(event.target.value); setDestinationFolder('') }}><option value="">Unassigned · ComfyUI output</option>{library.projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><label><span>Folder</span><select value={destinationFolder} disabled={!destinationProject} onChange={event => setDestinationFolder(event.target.value)}><option value="">Project root</option>{library.projects.find(project => project.id === destinationProject)?.folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label>{destinationProject && <button type="button" onClick={() => { void createStudioFolder(destinationProject) }}><FolderPlus size={15}/> New folder</button>}</div>
      <textarea value={prompt} onChange={e => setPrompt(e.target.value)} maxLength={batch ? 80000 : 4000}
        placeholder={batch ? 'הדבק כמה פרומפטים. השאר שורה ריקה בין כל אחד…' : mode === 'lip_sync' ? 'אופציונלי: תאר את ההופעה, המצלמה וההבעה…' : 'תאר את הסרטון שאתה רוצה ליצור…'} />
      <div className="composer-meta"><span>{prompt.length.toLocaleString()} תווים</span><label className="batch-toggle"><input type="checkbox" checked={batch} disabled={mode === 'lip_sync'} onChange={e => { setBatch(e.target.checked); if (!e.target.checked) setConnected(false) }} /><span>כמה פרומפטים</span></label></div>
      {batch && <div className="batch-note">כל פסקה היא שוט אחד · {paragraphCount} שוטים</div>}
      {batch && mode === 'text' && <div className="sequence-choice" aria-label="אופן עיבוד הפרומפטים">
        <button type="button" className={!connected ? 'active' : ''} onClick={() => setConnected(false)}><Clapperboard size={17} /><span><strong>נפרדים</strong><small>כל פרומפט הוא תוצאה</small></span></button>
        <button type="button" className={connected ? 'active connected' : ''} onClick={() => setConnected(true)}><Route size={17} /><span><strong>רצף מחובר</strong><small>סוף שוט הופך לפתיחת הבא</small></span></button>
      </div>}
      {connected && <div className="connected-note"><Route size={14} /><span>האפליקציה תייצר לפי הסדר, תבדוק כל שוט, תחלץ את הפריים האחרון ותחבר MP4 סופי אחד.</span></div>}

      <div className="mode-grid">
        {modes.map(item => <button key={item.id} type="button" disabled={item.id === 'lip_sync' && !audioLockReady} className={`mode-card ${mode === item.id ? 'selected' : ''}`} onClick={() => selectMode(item.id)}>
          <span className="mode-check">{mode === item.id && <Check size={13} />}</span>
          <strong>{item.label}</strong><small>{item.id === 'lip_sync' && !audioLockReady ? 'ממתין ל־Native AudioLock' : item.hint}</small>
        </button>)}
      </div>

      {mode === 'frames' && <div className="frame-grid">
        <ImageDropzone label="הוסף פריים פותח · חובה" hint="התמונה הראשונה · JPG, PNG או WebP עד 20MB" preview={openingPreview} onChange={setOpeningFrame} />
        <ImageDropzone label="הוסף פריים סוגר · אופציונלי" hint="אם מצורף, H3 יכוון את הסרטון גם לתמונה הזו" preview={closingPreview} onChange={setClosingFrame} />
      </div>}
      {mode === 'lip_sync' && <div className="lip-sync-inputs">
        <ImageDropzone label="פריים פותח · אופציונלי" hint="הדמות שאותה תרצה לדובב · JPG, PNG או WebP עד 20MB" preview={openingPreview} onChange={setOpeningFrame} />
        <div className="lip-sync-audio-box">
          <AudioDropzone file={lipSyncAudio} onChange={setLipSyncAudio} disabled={isRecording} label="הוסף אודיו לדיבוב · חובה" hint="WAV, MP3, M4A, AAC, FLAC, OGG או WebM · עד 50MB" />
          <div className="recording-controls">
            {!isRecording ? <button type="button" className="record-button" onClick={() => { void startRecording() }} disabled={sending}>
              <Mic size={17} /><span>התחל הקלטה</span><small>מיקרופון · עד 60 שניות</small>
            </button> : <button type="button" className="record-button recording" onClick={stopRecording}>
              <Square size={15} /><span>עצור הקלטה</span><b dir="ltr">{formatClipTime(recordingSeconds)}</b>
            </button>}
            {!isRecording && <span className="recording-alternative"><Mic size={13} /> או הקלט מהמיקרופון במקום להעלות קובץ</span>}
          </div>
          {lipSyncAudioPreview && <audio ref={lipSyncAudioElementRef} className="lip-sync-audio-player" controls preload="metadata" src={lipSyncAudioPreview} onLoadedMetadata={syncLipSyncAudioPreview} onPlay={syncLipSyncAudioPreview} onSeeking={syncLipSyncAudioPreview} onTimeUpdate={stopAtLipSyncAudioPreviewEnd} />}
          {lipSyncAudio && lipSyncAudioDuration && lipSyncAudioDuration > duration + 0.08 && <div className="audio-trim-box">
            <div className="audio-trim-heading"><span>חיתוך אודיו</span><small>נבחר קטע של {duration.toFixed(1)} שנ׳ מתוך {lipSyncAudioDuration.toFixed(1)} שנ׳</small></div>
            <input className="audio-trim-range" dir="ltr" type="range" min="0" max={Math.max(0, lipSyncAudioDuration - duration)} step="0.1" value={audioTrimStart} onChange={event => setAudioTrimStart(Number(event.target.value))} aria-label="נקודת התחלה באודיו" />
            <div className="audio-trim-times" dir="ltr"><span>{formatClipTime(audioTrimStart)}</span><span>{formatClipTime(audioTrimStart + duration)}</span></div>
            <small className="audio-trim-note">הנגן יעצור בסוף הקטע, ולרינדור יישלח הקטע החתוך בלבד.</small>
          </div>}
          {lipSyncAudio && lipSyncAudioDuration && lipSyncAudioDuration <= duration + 0.08 && <div className="reference-audio-note"><AudioLines size={14} /><span>האודיו קצר או שווה למשך הג׳נרוט, ולכן לא צריך חיתוך.</span></div>}
        </div>
      </div>}
      {mode === 'reference' && <>
        <div className="reference-grid">
          <MultiImageDropzone files={referenceImages} onChange={setReferenceImages} />
          <VideoDropzone files={referenceVideos} onChange={setReferenceVideos} />
          <AudioDropzone file={referenceAudio} onChange={setReferenceAudio} />
        </div>
        <div className="reference-limits-note"><ImageIcon size={14} /><span>תמונות: עד 9 קבצים, עד 20MB לכל תמונה · סרטונים: עד 3 קבצים, עד 500MB לכל סרטון, באורך 2–15 שניות</span></div>
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
              <button type="button" className={effectiveEngine === 'turbo' ? 'active' : ''} aria-pressed={effectiveEngine === 'turbo'} disabled={mode === 'lip_sync' || mode === 'reference' && !referenceTurboReady} onClick={() => selectEngine('turbo')}>
                <Zap size={16} /><span><strong>Turbo</strong><small>מהיר</small></span>
              </button>
              <button type="button" className={effectiveEngine === 'standard' ? 'active' : ''} aria-pressed={effectiveEngine === 'standard'} onClick={() => selectEngine('standard')}>
                <Gauge size={16} /><span><strong>רגיל</strong><small>מדויק</small></span>
              </button>
              <button type="button" className={effectiveEngine === 'spectrum' ? 'active' : ''} aria-pressed={effectiveEngine === 'spectrum'} disabled={mode === 'lip_sync' || !spectrumReady} onClick={() => selectEngine('spectrum')}>
                <Sparkles size={16} /><span><strong>Spectrum</strong><small>native + מהיר</small></span>
              </button>
            </div>
            {mode === 'reference' && !referenceTurboReady && <p className="setting-note">Ref2VA Turbo יופיע אחרי הורדת ה־LoRA הייעודית</p>}
            {mode === 'reference' && referenceTurboReady && <p className="setting-note">Ref2VA Turbo משתמש ב־4 סטפים וב־LoRA ייעודית</p>}
            {mode === 'lip_sync' && <p className="setting-note">דיבוב משתמש ב־Native AudioLock · Standard · 32B כדי לשמור את האודיו שהועלה מדויק.</p>}
            {!spectrumReady && <p className="setting-note">Spectrum יופיע אחרי שה־ComfyUI עם התוסף יופעל מחדש</p>}
            {effectiveEngine === 'turbo' && mode !== 'reference' && <>
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
              <button type="button" className={effectiveEncoder === 'clipproj' ? 'active' : ''} aria-pressed={effectiveEncoder === 'clipproj'} disabled={mode === 'lip_sync' || !clipprojReady} onClick={() => selectEncoder('clipproj')}>
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

          <div className="setting-block audio-setting-block">
            <div className="setting-title"><span>אודיו</span><small>ערוץ שמע בתוצאה</small></div>
            {mode === 'lip_sync' ? <div className="audio-output-toggle fixed-audio"><AudioLines size={17} /><span>האודיו שהועלה</span><small>יישמר מדויק בתוצאה</small></div> : <label className="audio-output-toggle"><input type="checkbox" checked={!noAudio} onChange={event => setNoAudio(!event.target.checked)} /><span>{noAudio ? 'ללא אודיו' : 'כולל אודיו'}</span><small>{noAudio ? 'MP4 ללא ערוץ שמע' : 'H3 ייצור וימזג אודיו'}</small></label>}
          </div>

          <div className="setting-block resolution-block">
            <div className="setting-title"><span>רזולוציה</span><small>כפולות 32 שמתאימות ל־H3</small></div>
            <div className="aspect-grid">{aspectOptions.map(aspect => <button type="button" key={aspect} className={preferences.aspect === aspect ? 'active' : ''} onClick={() => setPreferences(current => ({ ...current, aspect }))}>{aspect}</button>)}</div>
            <label className="numeric-control"><span>Megapixels</span><input dir="ltr" type="number" min="0.1" max="2" step="0.01" value={preferences.megapixels} onChange={event => setPreferences(current => ({ ...current, megapixels: Math.max(0.1, Math.min(2, Number(event.target.value) || 0.1)) }))} /><small>׳׳×׳¨׳•׳× 0.1–2.0 · H3 מעגל לכפולות 32</small></label>
            <div className="calculated-resolution">{calculatedResolution.id} · {(calculatedResolution.width * calculatedResolution.height / 1_000_000).toFixed(2)} MP בפועל</div>
          </div>
        </div>

        <div className="generation-summary">
          <div className="profile-summary"><b dir="ltr">{engineLabel(effectiveEngine)}</b>{effectiveEngine === 'turbo' && mode !== 'reference' && <><i>·</i><b dir="ltr">{preferences.turboProfile.toUpperCase()}</b></>}<i>·</i><b dir="ltr">{encoderLabel(effectiveEncoder)}</b><i>·</i><b>{generationSteps} סטפים</b><i>·</i><b dir="ltr">{calculatedResolution.id}</b></div>
          <small>{loadLevel === 'normal' ? 'מוכן ליצירה' : 'לפני השליחה יוצג אישור עומס'}</small>
        </div>
      </div>

      <div className="final-row">
        <label className="duration-input"><span>משך בשניות</span><input dir="ltr" type="number" min="0.5" max="60" step="0.1" value={duration} onChange={event => { const value = Math.max(0.5, Math.min(60, Number(event.target.value) || 0.5)); setDuration(mode === 'lip_sync' && lipSyncAudioDuration ? Math.min(value, lipSyncAudioDuration) : value) }} /><small>{mode === 'lip_sync' ? 'האודיו ייחתך לאורך הזה' : 'H3 מעגל אוטומטית לפריים הקרוב'}</small></label>
        <button className="create-button" onClick={() => { void submit() }} disabled={sending || isRecording} aria-busy={sending}><span>{sending ? 'שולח…' : connected ? `צור רצף של ${paragraphCount} שוטים` : batch ? `הוסף ${paragraphCount} לתור` : 'צור וידאו'}</span>{sending ? <LoaderCircle className="spin" size={19} /> : connected ? <Route size={18} /> : <Send size={18} />}</button>
      </div>
      {mode === 'reference' && !referenceReady && <p className="quiet-warning">מודל הרפרנס עדיין בהתקנה. פריימים וטקסט זמינים כרגיל.</p>}
      {mode === 'reference' && referenceReady && !reference10Ready && <p className="quiet-warning">רפרנס מעל 5 שניות ייפתח רק אחרי בדיקת עומס מוצלחת.</p>}
      {error && <div className="error-banner">{error}</div>}
    </section>

    <section className="queue-section">
      <div className="section-heading"><div><span>התור שלך</span><h2>{active.length || activeSequences.length ? 'היצירה בתנועה' : queued.length || queuedSequences.length ? 'ממתין ליצירה' : 'הכול שקט כרגע'}</h2></div><span className="queue-count">{active.length + queued.length + activeSequences.length + queuedSequences.length}</span></div>
      {!active.length && !queued.length && !activeSequences.length && !queuedSequences.length && <div className="empty"><div><Play size={22} /></div><p>הסרטון הבא שלך מתחיל בפרומפט למעלה</p></div>}
      {activeSequences.map(sequence => <SequenceCard key={sequence.id} sequence={sequence} assignment={assignmentFor('sequence',sequence.id)} onCancel={() => mutate(`/api/sequences/${sequence.id}/cancel`)} />)}
      {active.map(j => <JobCard key={j.id} job={j} assignment={assignmentFor('job',j.id)} onCancel={() => mutate(`/api/jobs/${j.id}/cancel`)} />)}
      {queuedTasks.map(task => task.kind === 'sequence'
        ? <SequenceCard key={task.sequence.id} sequence={task.sequence} assignment={assignmentFor('sequence',task.sequence.id)} onCancel={() => mutate(`/api/sequences/${task.sequence.id}/cancel`)} />
        : <JobCard key={task.job.id} job={task.job} assignment={assignmentFor('job',task.job.id)} index={queued.indexOf(task.job)} total={queued.length} onUp={() => move(task.job.id, -1)} onDown={() => move(task.job.id, 1)} onDelete={() => { void deleteGeneratedAsset('job',task.job.id,task.job.prompt.slice(0,80)) }} />)}
    </section>

    {(!!history.length || !!sequenceHistory.length) && <section className="results-section">
      <div className="section-heading"><div><span>תוצאות</span><h2>הסרטונים האחרונים</h2></div><span className="selection-hint">בחר לפי סדר לחיבור</span></div>
      {!!selectedResults.length && <div className="join-dock">
        <div className="join-dock-head"><div><Combine size={18} /><span><strong>{selectedResults.length} קטעים נבחרו</strong><small>זה יהיה סדר החיבור</small></span></div><button type="button" onClick={() => setSelectedResults([])}>נקה</button></div>
        <div className="join-order">{selectedResults.map((reference, index) => <div className="join-chip" key={reference}><b>{index + 1}</b><span>{selectedResultLabel(reference)}</span><button type="button" onClick={() => moveSelectedResult(index, -1)} disabled={index === 0}><ArrowUp size={14} /></button><button type="button" onClick={() => moveSelectedResult(index, 1)} disabled={index === selectedResults.length - 1}><ArrowDown size={14} /></button><button type="button" onClick={() => toggleResult(reference)}><X size={14} /></button></div>)}</div>
        <button type="button" className="join-button" disabled={selectedResults.length < 2 || joining} onClick={() => { void joinSelected() }}>{joining ? <LoaderCircle className="spin" size={17} /> : <Combine size={17} />} {joining ? 'מוסיף לתור…' : 'חבר לסרטון אחד'}</button>
      </div>}
      <div className="asset-results-tree">
        {(() => {
          const unassigned = visibleResultAssets.filter(asset => !assignmentFor(asset.kind, asset.id))
          const selectedProjects = libraryProject === 'all' ? library.projects : library.projects.filter(project => project.id === libraryProject)
          return <>
            {(libraryProject === 'all' || libraryProject === 'unassigned') && !!unassigned.length && renderAssetContainer('unassigned', 'ללא פרויקט', unassigned, 'unassigned')}
            {libraryProject !== 'unassigned' && selectedProjects.map(project => {
              const assets = visibleResultAssets.filter(asset => assignmentFor(asset.kind, asset.id)?.project_id === project.id)
              return assets.length || libraryProject === project.id ? renderProjectResults(project, assets) : null
            })}
          </>
        })()}
      </div>
      {!visibleSequenceHistory.length && !visibleHistory.length && <div className="empty"><div><Folder size={22}/></div><p>No generated videos are stored in this location.</p></div>}
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
          {effectiveEngine === 'turbo' && mode !== 'reference' && <span>{preferences.turboProfile.toUpperCase()}</span>}
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
    {editingAsset && <div className="dialog-backdrop asset-dialog-backdrop" onMouseDown={() => setEditingAsset(null)}><section className="asset-dialog" role="dialog" aria-modal="true" aria-labelledby="asset-dialog-title" onMouseDown={event => event.stopPropagation()}><div className="asset-dialog-head"><div><span>ארגון קובץ</span><h2 id="asset-dialog-title">העברה או שינוי שם</h2></div><button onClick={() => setEditingAsset(null)} aria-label="סגירה"><X size={17}/></button></div><p>{editingAsset.label}</p><label><span>פרויקט</span><select value={editProject} onChange={event => { setEditProject(event.target.value); setEditFolder('') }}><option value="">ללא פרויקט · חזרה לפלט של ComfyUI</option>{library.projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><label><span>תיקייה</span><select value={editFolder} disabled={!editProject} onChange={event => setEditFolder(event.target.value)}><option value="">שורש הפרויקט</option>{library.projects.find(project => project.id === editProject)?.folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select></label><label><span>שם הקובץ</span><div className="asset-filename"><input value={editFilename} disabled={!editProject} onChange={event => setEditFilename(event.target.value)} placeholder="השארת שם הקובץ הנוכחי"/><b>.mp4</b></div></label><small>העברה או שינוי שם כאן משנים את הקובץ בפועל ושומרים על הקישור ב־Studio.</small><div className="asset-dialog-actions"><button onClick={() => setEditingAsset(null)}>ביטול</button><button className="confirm" onClick={() => { void saveAssetLocation() }}><Move size={15}/> שמירת שינויים</button></div></section></div>}
    </>}
  </main>
}

function JobCard({ job, assignment, index, total, selectedOrder, onSelect, onManage, onUp, onDown, onDelete, onCancel }: { job: Job; assignment?: AssetAssignment; index?: number; total?: number; selectedOrder?: number; onSelect?: () => void; onManage?: () => void; onUp?: () => void; onDown?: () => void; onDelete?: () => void; onCancel?: () => void }) {
  const labels: Record<Status, string> = { queued: 'ממתין', starting: 'מפעיל מנוע', running: 'יוצר עכשיו', verifying: 'בודק וידאו', completed: 'מוכן', failed: 'נכשל', canceled: 'בוטל' }
  const phaseLabels: Record<Phase, string> = { queued: 'ממתין', starting: 'מפעיל מנוע', sampling: 'יוצר פריימים', processing: 'מעבד וידאו', verifying: 'בודק וידאו', completed: 'מוכן', failed: 'נכשל', canceled: 'בוטל' }
  const active = ['starting', 'running', 'verifying'].includes(job.status)
  const engine = job.engine || (job.mode === 'reference' ? 'standard' : 'turbo')
  const steps = job.steps || (engine === 'turbo' ? 4 : engine === 'spectrum' ? 16 : 20)
  const width = job.width || 736
  const height = job.height || 416
  const megapixels = job.megapixels
  const [now, setNow] = useState(() => Date.now())
  const [promptExpanded, setPromptExpanded] = useState(false)
  const [promptCopied, setPromptCopied] = useState(false)
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
  const copyPrompt = async () => {
    await navigator.clipboard.writeText(job.prompt)
    setPromptCopied(true)
    window.setTimeout(() => setPromptCopied(false), 1600)
  }
  return <article className={`job-card ${job.status} ${selectedOrder ? 'result-selected' : ''}`}>
    {selectedOrder && <span className="selection-order">{selectedOrder}</span>}
    {job.video_url && <video src={job.video_url} controls preload="metadata" playsInline style={{ aspectRatio: `${width}/${height}` }} />}
    <div className="job-body">
      <div className="job-head"><span className="status"><i />{labels[job.status]}</span><span>{job.duration} שנ׳ · {modeLabel(job.mode)}</span></div>
      {assignment && <div className="asset-location" dir="ltr"><Folder size={13}/><span>{assignment.project_name}{assignment.folder_name ? ` / ${assignment.folder_name}` : ''}</span><b>{assignment.filename}</b></div>}
      <div className={`prompt-card ${promptExpanded ? 'expanded' : ''}`}><p>{job.prompt}</p></div>
      <div className="prompt-actions"><button type="button" onClick={() => setPromptExpanded(current => !current)}>{promptExpanded ? 'הסתר פרומפט' : 'הצג פרומפט מלא'}</button><button type="button" onClick={() => { void copyPrompt() }}><Copy size={14} /> {promptCopied ? 'הועתק' : 'העתק'}</button></div>
      <div className="job-config"><span>{engineLabel(engine)}</span>{engine === 'turbo' && <span>{(job.turbo_profile || 'v1').toUpperCase()}</span>}<span>{encoderLabel(job.encoder || 'native')}</span><span>{steps} סטפים</span><span>{width}×{height}</span>{megapixels !== undefined && <span>{megapixels.toFixed(2)} MP</span>}</div>
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
        {onManage && <button onClick={onManage}><Folder size={16}/> ארגון</button>}
        {onCancel && <button className="danger" onClick={onCancel}>ביטול</button>}
        {onDelete && <button className="trash" onClick={onDelete} aria-label="מחיקה"><Trash2 size={17} /></button>}
        {job.metrics?.generation_seconds && <span className="elapsed">נוצר תוך {formatDuration(job.metrics.generation_seconds)}</span>}
      </div>
    </div>
  </article>
}

function SequenceCard({ sequence, assignment, selectedOrder, onSelect, onManage, onDelete, onCancel }: { sequence: Sequence; assignment?: AssetAssignment; selectedOrder?: number; onSelect?: () => void; onManage?: () => void; onDelete?: () => void; onCancel?: () => void }) {
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
      {assignment && <div className="asset-location" dir="ltr"><Folder size={13}/><span>{assignment.project_name}{assignment.folder_name ? ` / ${assignment.folder_name}` : ''}</span><b>{assignment.filename}</b></div>}
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
        {onManage && <button onClick={onManage}><Folder size={16}/> ארגון</button>}
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

function formatClipTime(totalSeconds: number) {
  const value = Math.max(0, totalSeconds)
  const minutes = Math.floor(value / 60)
  const seconds = Math.floor(value % 60)
  const tenths = Math.floor((value - Math.floor(value)) * 10)
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${tenths}`
}

function modeLabel(mode: Mode) {
  if (mode === 'text') return 'טקסט'
  if (mode === 'frames') return 'I2V'
  if (mode === 'opening') return 'פריים פותח'
  if (mode === 'closing') return 'פריים סוגר'
  if (mode === 'lip_sync') return 'דיבוב'
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
