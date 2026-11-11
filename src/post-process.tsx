import React, { FormEvent, useEffect, useState } from 'react'
import { Gauge, Sparkles, Upload, X } from 'lucide-react'

// Upscale or interpolate a finished video or an uploaded one (issue #37). Times and limits come from the lab
// measurements on the RTX 3080 10 GB; the server enforces the same limits and answers with a clear reason when a clip
// is outside them.
export type PostOperation = 'interpolate' | 'upscale'
export type PostOptions = {
  operation: PostOperation | 'edit'; method: string; source_job_id?: string | null; source_filename?: string
  source_width: number; source_height: number; source_fps: number; source_frames: number; source_duration: number
  width: number; height: number; fps: number; frames: number; long_side?: number; crop_percent?: number; audio?: boolean
  detail?: string; detail_label?: string; trimmed_frames?: number; fps_target?: number
  task?: string; task_label?: string; seconds?: number; pad_frames?: number; photos?: string[]  // H3 edit (issue #54)
}
// `method`: set when the source is itself an upscaled card (an RTX VSR 1920 card offers RTX VSR + H3 detail, issue #50).
type SourceJob = { id: string; width: number; height: number; duration: number; method?: string }
type SourceSize = { width: number; height: number; duration: number }

// `visualEnhancer`: runs through the user's own Visual Enhancer VE_CLI.exe (issue #39), not ComfyUI; offered only
// when the server reports it is set up (visual_enhancer_cli in config.local.json).
const METHODS: Record<PostOperation, { id: string; label: string; detail: string; visualEnhancer?: boolean }[]> = {
  interpolate: [
    { id: 'rife', label: 'RIFE 4.26', detail: 'מהיר · כ־20 שניות לשוט של 5 שניות · זיכרון נמוך' },
    { id: 'film', label: 'FILM', detail: 'איטי יותר · כ־80 שניות לשוט של 5 שניות · עד 1.5MP' },
    { id: 'fsr3', label: 'FSR 3', detail: 'הכי מהיר · כ־5 שניות לשוט · בתנועה מהירה עלול להיות שבור · Visual Enhancer', visualEnhancer: true },
  ],
  upscale: [
    { id: 'lanczos', label: 'Lanczos', detail: 'מהיר · כ־25 שניות לשוט · מגדיל בלי להמציא פרטים' },
    { id: 'gan', label: 'Real-ESRGAN ×2', detail: 'כ־4 דקות לשוט · מחדד קצוות ומרקמים' },
    { id: 'rtx', label: 'RTX VSR', detail: 'הכי מהיר · כ־12 שניות לשוט · עור טבעי · Visual Enhancer', visualEnhancer: true },
  ],
}
export const POST_METHOD_LABELS: Record<string, string> = { rife: 'RIFE 4.26', film: 'FILM', lanczos: 'Lanczos', gan: 'Real-ESRGAN ×2', rtx: 'RTX VSR', fsr3: 'FSR 3', h3detail: 'RTX VSR + H3 detail' }
// RTX VSR + H3 detail (issue #50): a short H3 pass with the original clip's prompt and model. Only the strengths the
// lab tested on the RTX 3080 (all rated good); the server enforces the same list and the tested sources.
const H3_DETAIL_LEVELS = [
  { id: 's30', label: 'קל · 0.30', detail: 'הכי קרוב למקור' },
  { id: 's45', label: 'בינוני · 0.45', detail: 'מומלץ · פרטים חדים בלי לשנות פנים' },
  { id: 's60', label: 'חזק · 0.60', detail: 'יותר פרטים · העור מתחיל להיראות מטופל' },
  { id: 's60x3', label: 'חזק · 0.60 · 3 צעדים', detail: 'קצת יותר חד מ־2 צעדים' },
  { id: 's75x3', label: 'הכי חזק · 0.75 · 3 צעדים', detail: 'הכי חד · דוגמאות צבועות מתחילות להשתנות' },
]
// An RTX VSR card at 1920 can take the H3 detail pass.
export function canAddH3Detail(job: { engine?: string; workflow_variant?: string | null; width: number; height: number }) {
  return job.engine === 'post' && job.workflow_variant === 'rtx'
    && ((job.width === 1920 && job.height === 1080) || (job.width === 1080 && job.height === 1920))
}
const LONG_SIDES = [1920, 2560]
// RIFE 60 / 120 fps (issue #52): RIFE x5, 60 keeps every second frame. Tested on 24 fps clips of up to 5.2 s at 1632x928;
// the server refuses anything else with the reason.
const RIFE_RATES = [
  { id: 0, label: '×2 · 48 fps', detail: 'הרגיל · כל קליפ עד 30fps' },
  { id: 60, label: '60 fps', detail: 'חלק מאוד · כ־40 שניות לשוט · קליפ 24fps עד 5.2 שניות' },
  { id: 120, label: '120 fps', detail: 'הכי חלק · כ־40 שניות לשוט · קליפ 24fps עד 5.2 שניות' },
]
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
export function PostProcessSheet({ job, operation: initialOperation, csrf, visualEnhancer = false, onClose, onQueued }: {
  job?: SourceJob; operation: PostOperation; csrf: string; visualEnhancer?: boolean; onClose: () => void; onQueued: () => void
}) {
  const external = !job
  const detailSheet = job?.method === 'rtx'
  const [operation, setOperation] = useState<PostOperation>(initialOperation)
  const [method, setMethod] = useState(detailSheet ? 'h3detail' : METHODS[initialOperation][0].id)
  const [detailLevel, setDetailLevel] = useState('s45')
  const [fpsTarget, setFpsTarget] = useState(0)
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

  const chooseOperation = (next: PostOperation) => { setOperation(next); setMethod(METHODS[next][0].id); setFpsTarget(0); setError('') }
  const showRates = operation === 'interpolate' && method === 'rife' && !detailSheet

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (external && !file) { setError('בחר קובץ וידאו'); return }
    setBusy(true); setError('')
    try {
      let response: Response
      if (job) {
        response = await fetch(`/api/jobs/${job.id}/post-process`, {
          method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
          body: JSON.stringify(detailSheet ? { operation: 'upscale', method: 'h3detail', detail: detailLevel }
            : { operation, method, long_side: operation === 'upscale' ? longSide : null, fps_target: showRates && fpsTarget ? fpsTarget : null }),
        })
      } else {
        const form = new FormData()
        form.append('video', file as File)
        form.append('operation', operation)
        form.append('method', method)
        if (operation === 'upscale') form.append('long_side', String(longSide))
        if (showRates && fpsTarget) form.append('fps_target', String(fpsTarget))
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

  const title = external ? 'עיבוד וידאו חיצוני' : detailSheet ? 'פרטים עם H3' : operation === 'upscale' ? 'הגדלת וידאו' : 'החלקת תנועה · פי 2 פריימים'
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
      {detailSheet ? <div className="post-sheet-options" role="radiogroup" aria-label="עוצמת פרטים">
        {H3_DETAIL_LEVELS.map(item => <button key={item.id} type="button" role="radio" aria-checked={detailLevel === item.id}
          className={detailLevel === item.id ? 'active' : ''} onClick={() => setDetailLevel(item.id)}>
          <strong>{item.label}</strong><small>{item.detail}</small>
        </button>)}
      </div> : <div className="post-sheet-options" role="radiogroup" aria-label="שיטה">
        {METHODS[operation].filter(item => visualEnhancer || !item.visualEnhancer).map(item => <button key={item.id} type="button" role="radio" aria-checked={method === item.id}
          className={method === item.id ? 'active' : ''} onClick={() => { setMethod(item.id); if (item.id !== 'rife') setFpsTarget(0) }}>
          <strong dir="ltr">{item.label}</strong><small>{item.detail}</small>
        </button>)}
      </div>}
      {showRates && <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="קצב פריימים">
        {RIFE_RATES.map(item => <button key={item.id} type="button" role="radio" aria-checked={fpsTarget === item.id}
          className={fpsTarget === item.id ? 'active' : ''} onClick={() => setFpsTarget(item.id)}>
          <strong dir="ltr">{item.label}</strong><small>{item.detail}</small>
        </button>)}
      </div>}
      {operation === 'upscale' && !detailSheet && <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="גודל יעד">
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
      {detailSheet ? <p className="post-sheet-note">H3 מצייר מחדש פרטים (בד, עור, עיניים, שיער) עם הפרומפט והמודל של הקליפ המקורי, ושומר על התנועה, הפנים, השפתיים והסאונד. כ־5.5 דקות לשוט של 5 שניות, עד 15 שניות. נבדק על קליפים של Pika (פריים פתיחה) ושל Turbo v4 (ליפ־סינק). H3 צריך 17n+5 פריימים, אז לפעמים כמה פריימים בסוף נחתכים.</p>
      : <p className="post-sheet-note">קליפים ארוכים עוברים בחלקים בתוך עבודה אחת ומחוברים בסוף (RTX VSR ו־FSR 3 בלי חלוקה). מקורות עד 30fps: הגדלה עד 1080p, החלקה עם RIFE ו־FSR 3 גם על קליפים מוגדלים עד 2560 (FILM עד 1.5MP; Lanczos גם על 60fps). אפשר להגדיל קליפ אחרי החלקת תנועה: Lanczos, או Real-ESRGAN עד 1.5MP.{visualEnhancer && ' RTX VSR ו־FSR 3 רצים ב־Visual Enhancer שלך, על קליפים מקוריים בלבד (לא אחרי החלקה).'}</p>}
      {error && <p className="post-sheet-error" role="alert">{error}</p>}
      <div className="app-modal-actions"><button type="button" onClick={onClose} disabled={busy}>ביטול</button><button type="submit" className="confirm" disabled={busy}>{busy ? (external ? 'מעלה…' : 'מוסיף…') : 'הוסף לתור'}</button></div>
    </form>
  </div>
}
