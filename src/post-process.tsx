import React, { FormEvent, useEffect, useState } from 'react'
import { Gauge, Sparkles, Upload, X } from 'lucide-react'

// Upscale or interpolate a finished video or an uploaded one (issue #37). Times and limits come from the lab
// measurements on the RTX 3080 10 GB; the server enforces the same limits and answers with a clear reason when a clip
// is outside them.
export type PostOperation = 'interpolate' | 'upscale'
export type PostOptions = {
  operation: PostOperation; method: string; source_job_id?: string | null; source_filename?: string
  source_width: number; source_height: number; source_fps: number; source_frames: number; source_duration: number
  width: number; height: number; fps: number; frames: number; long_side?: number; crop_percent?: number; audio?: boolean
}
type SourceJob = { id: string; width: number; height: number; duration: number }
type SourceSize = { width: number; height: number; duration: number }

const METHODS: Record<PostOperation, { id: string; label: string; detail: string }[]> = {
  interpolate: [
    { id: 'rife', label: 'RIFE 4.26', detail: 'מהיר · כ־20 שניות לשוט של 5 שניות · זיכרון נמוך' },
    { id: 'film', label: 'FILM', detail: 'איטי יותר · כ־80 שניות לשוט של 5 שניות · עד 1.5MP' },
  ],
  upscale: [
    { id: 'lanczos', label: 'Lanczos', detail: 'מהיר · כ־25 שניות לשוט · מגדיל בלי להמציא פרטים' },
    { id: 'gan', label: 'Real-ESRGAN ×2', detail: 'כ־4 דקות לשוט · מחדד קצוות ומרקמים' },
  ],
}
export const POST_METHOD_LABELS: Record<string, string> = { rife: 'RIFE 4.26', film: 'FILM', lanczos: 'Lanczos', gan: 'Real-ESRGAN ×2' }
const LONG_SIDES = [1920, 2560]
const UPLOAD_ACCEPT = 'video/mp4,video/quicktime,video/webm,video/x-matroska'

// Mirrors backend/post_process.py upscale_size: near-16:9 / 9:16 sources get the standard sizes with a small crop.
export function upscaleSize(width: number, height: number, longSide: number) {
  const landscape = width >= height
  const standard = landscape ? 16 / 9 : 9 / 16
  if (Math.abs((width / height) / standard - 1) <= 0.04) {
    const short = Math.floor(longSide * 9 / 16)
    return landscape ? { width: longSide, height: short } : { width: short, height: longSide }
  }
  const scale = longSide / Math.max(width, height)
  return { width: Math.round(width * scale / 16) * 16, height: Math.round(height * scale / 16) * 16 }
}

export function cropPercent(width: number, height: number, target: { width: number; height: number }) {
  const ratio = (width / height) / (target.width / target.height)
  return Math.round((1 - Math.min(ratio, 1 / ratio)) * 1000) / 10
}

// Pass `job` for a finished video card, or leave it out to upload an external video.
export function PostProcessSheet({ job, operation: initialOperation, csrf, onClose, onQueued }: {
  job?: SourceJob; operation: PostOperation; csrf: string; onClose: () => void; onQueued: () => void
}) {
  const external = !job
  const [operation, setOperation] = useState<PostOperation>(initialOperation)
  const [method, setMethod] = useState(METHODS[initialOperation][0].id)
  const [longSide, setLongSide] = useState(2560)
  const [file, setFile] = useState<File | null>(null)
  const [fileSize, setFileSize] = useState<SourceSize | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const source: SourceSize | null = job || fileSize

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose() }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [busy, onClose])

  // Read the uploaded clip's size in the browser so the size choices can be shown before upload.
  useEffect(() => {
    setFileSize(null)
    if (!file) return
    const url = URL.createObjectURL(file)
    const video = document.createElement('video')
    video.preload = 'metadata'
    video.onloadedmetadata = () => setFileSize({ width: video.videoWidth, height: video.videoHeight, duration: video.duration })
    video.onerror = () => setFileSize(null)
    video.src = url
    return () => { video.removeAttribute('src'); URL.revokeObjectURL(url) }
  }, [file])

  const chooseOperation = (next: PostOperation) => { setOperation(next); setMethod(METHODS[next][0].id); setError('') }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (external && !file) { setError('בחר קובץ וידאו'); return }
    setBusy(true); setError('')
    try {
      let response: Response
      if (job) {
        response = await fetch(`/api/jobs/${job.id}/post-process`, {
          method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
          body: JSON.stringify({ operation, method, long_side: operation === 'upscale' ? longSide : null }),
        })
      } else {
        const form = new FormData()
        form.append('video', file as File)
        form.append('operation', operation)
        form.append('method', method)
        if (operation === 'upscale') form.append('long_side', String(longSide))
        response = await fetch('/api/post-process', { method: 'POST', headers: { 'X-CSRF-Token': csrf }, body: form })
      }
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        setError(typeof data.detail === 'string' ? data.detail : 'לא ניתן להוסיף לתור')
        return
      }
      onQueued()
    } catch {
      setError('החיבור נכשל, נסה שוב')
    } finally {
      setBusy(false)
    }
  }

  const title = external ? 'עיבוד וידאו חיצוני' : operation === 'upscale' ? 'הגדלת וידאו' : 'החלקת תנועה · פי 2 פריימים'
  return <div className="dialog-backdrop app-modal-backdrop" onMouseDown={() => { if (!busy) onClose() }}>
    <form className="app-modal post-sheet" role="dialog" aria-modal="true" onSubmit={submit} onMouseDown={event => event.stopPropagation()}>
      <div className="app-modal-head"><div className="app-modal-icon">{external ? <Upload size={21} /> : operation === 'upscale' ? <Sparkles size={21} /> : <Gauge size={21} />}</div><button type="button" className="app-modal-close" onClick={onClose} disabled={busy} aria-label="סגירה"><X size={17} /></button></div>
      <div><span className="app-modal-eyebrow">{external ? 'העלאת קובץ · עבודה חדשה בתור' : 'עיבוד וידאו מוכן · עבודה חדשה בתור'}</span><h2>{title}</h2></div>
      {external && <label className="post-sheet-file">
        <input type="file" accept={UPLOAD_ACCEPT} disabled={busy} onChange={event => { setFile(event.target.files?.[0] || null); setError('') }} />
        <span>{file ? file.name : 'בחר וידאו (MP4, MOV, WebM, MKV · עד 500MB)'}</span>
      </label>}
      {external && <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="פעולה">
        {(['upscale', 'interpolate'] as PostOperation[]).map(item => <button key={item} type="button" role="radio" aria-checked={operation === item}
          className={operation === item ? 'active' : ''} onClick={() => chooseOperation(item)} disabled={busy}>
          <strong>{item === 'upscale' ? 'הגדלה' : 'החלקת תנועה'}</strong><small>{item === 'upscale' ? 'לגודל 1920 או 2560' : 'פי 2 פריימים'}</small>
        </button>)}
      </div>}
      {source && <p dir="ltr" className="post-sheet-source">{source.width}×{source.height} · {source.duration.toFixed(2)} s</p>}
      <div className="post-sheet-options" role="radiogroup" aria-label="שיטה">
        {METHODS[operation].map(item => <button key={item.id} type="button" role="radio" aria-checked={method === item.id}
          className={method === item.id ? 'active' : ''} onClick={() => setMethod(item.id)}>
          <strong dir="ltr">{item.label}</strong><small>{item.detail}</small>
        </button>)}
      </div>
      {operation === 'upscale' && <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="גודל יעד">
        {LONG_SIDES.map(side => {
          const size = source ? upscaleSize(source.width, source.height, side) : null
          const crop = source && size ? cropPercent(source.width, source.height, size) : 0
          return <button key={side} type="button" role="radio" aria-checked={longSide === side}
            className={longSide === side ? 'active' : ''} onClick={() => setLongSide(side)}>
            <strong dir="ltr">{size ? `${size.width}×${size.height}` : `${side}px`}</strong>
            <small>{crop >= 0.1 ? `חיתוך ${crop}% מהמרכז להתאמה` : side === 2560 ? 'הגודל שנבדק במעבדה' : 'צד ארוך 1920'}</small>
          </button>
        })}
      </div>}
      <p className="post-sheet-note">נבדק על קליפים של עד 5 שניות, עד 1080p ועד 30fps (FILM עד 1.5MP; Lanczos גם על 60fps). אפשר להגדיל קליפ אחרי החלקת תנועה ב־Lanczos.</p>
      {error && <p className="post-sheet-error" role="alert">{error}</p>}
      <div className="app-modal-actions"><button type="button" onClick={onClose} disabled={busy}>ביטול</button><button type="submit" className="confirm" disabled={busy}>{busy ? (external ? 'מעלה…' : 'מוסיף…') : 'הוסף לתור'}</button></div>
    </form>
  </div>
}
