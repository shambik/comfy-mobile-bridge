import React, { FormEvent, useEffect, useState } from 'react'
import { Gauge, Sparkles, X } from 'lucide-react'

// Upscale or interpolate a finished video (issue #37). Times and limits come from the lab measurements on the
// RTX 3080 10 GB; the server enforces the same limits and answers with a clear reason when a clip is outside them.
export type PostOperation = 'interpolate' | 'upscale'
export type PostOptions = {
  operation: PostOperation; method: string; source_job_id?: string
  source_width: number; source_height: number; source_fps: number; source_frames: number; source_duration: number
  width: number; height: number; fps: number; frames: number; long_side?: number; audio?: boolean
}
type SourceJob = { id: string; width: number; height: number; duration: number }

const METHODS: Record<PostOperation, { id: string; label: string; detail: string }[]> = {
  interpolate: [
    { id: 'rife', label: 'RIFE 4.26', detail: 'מהיר · כ־20 שניות לשוט של 5 שניות · זיכרון נמוך' },
    { id: 'film', label: 'FILM', detail: 'איטי יותר · כ־80 שניות לשוט של 5 שניות · כ־7GB' },
  ],
  upscale: [
    { id: 'lanczos', label: 'Lanczos', detail: 'מהיר · כ־35 שניות לשוט · מגדיל בלי להמציא פרטים' },
    { id: 'gan', label: 'Real-ESRGAN ×2', detail: 'כ־4 דקות לשוט · מחדד קצוות ומרקמים' },
  ],
}
export const POST_METHOD_LABELS: Record<string, string> = { rife: 'RIFE 4.26', film: 'FILM', lanczos: 'Lanczos', gan: 'Real-ESRGAN ×2' }
const LONG_SIDES = [1920, 2560]

export function upscaleSize(width: number, height: number, longSide: number) {
  const scale = longSide / Math.max(width, height)
  return { width: Math.round(width * scale / 16) * 16, height: Math.round(height * scale / 16) * 16 }
}

export function PostProcessSheet({ job, operation, csrf, onClose, onQueued }: {
  job: SourceJob; operation: PostOperation; csrf: string; onClose: () => void; onQueued: () => void
}) {
  const [method, setMethod] = useState(METHODS[operation][0].id)
  const [longSide, setLongSide] = useState(2560)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose() }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [busy, onClose])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true); setError('')
    try {
      const response = await fetch(`/api/jobs/${job.id}/post-process`, {
        method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
        body: JSON.stringify({ operation, method, long_side: operation === 'upscale' ? longSide : null }),
      })
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

  const title = operation === 'upscale' ? 'הגדלת וידאו' : 'החלקת תנועה · פי 2 פריימים'
  return <div className="dialog-backdrop app-modal-backdrop" onMouseDown={() => { if (!busy) onClose() }}>
    <form className="app-modal post-sheet" role="dialog" aria-modal="true" onSubmit={submit} onMouseDown={event => event.stopPropagation()}>
      <div className="app-modal-head"><div className="app-modal-icon">{operation === 'upscale' ? <Sparkles size={21} /> : <Gauge size={21} />}</div><button type="button" className="app-modal-close" onClick={onClose} disabled={busy} aria-label="סגירה"><X size={17} /></button></div>
      <div><span className="app-modal-eyebrow">עיבוד וידאו מוכן · עבודה חדשה בתור</span><h2>{title}</h2></div>
      <p dir="ltr" className="post-sheet-source">{job.width}×{job.height} · {job.duration.toFixed(2)} s</p>
      <div className="post-sheet-options" role="radiogroup" aria-label="שיטה">
        {METHODS[operation].map(item => <button key={item.id} type="button" role="radio" aria-checked={method === item.id}
          className={method === item.id ? 'active' : ''} onClick={() => setMethod(item.id)}>
          <strong dir="ltr">{item.label}</strong><small>{item.detail}</small>
        </button>)}
      </div>
      {operation === 'upscale' && <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="גודל יעד">
        {LONG_SIDES.map(side => {
          const size = upscaleSize(job.width, job.height, side)
          return <button key={side} type="button" role="radio" aria-checked={longSide === side}
            className={longSide === side ? 'active' : ''} onClick={() => setLongSide(side)}>
            <strong dir="ltr">{size.width}×{size.height}</strong><small>{side === 2560 ? 'הגודל שנבדק במעבדה' : 'צד ארוך 1920'}</small>
          </button>
        })}
      </div>}
      <p className="post-sheet-note">נבדק על שוטים של עד 5 שניות ועד 1.5MP (Lanczos גם על קליפים של 48fps). אפשר להגדיל קליפ אחרי החלקת תנועה ב־Lanczos.</p>
      {error && <p className="post-sheet-error" role="alert">{error}</p>}
      <div className="app-modal-actions"><button type="button" onClick={onClose} disabled={busy}>ביטול</button><button type="submit" className="confirm" disabled={busy}>{busy ? 'מוסיף…' : 'הוסף לתור'}</button></div>
    </form>
  </div>
}
