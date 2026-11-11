import React, { FormEvent, useEffect, useState } from 'react'
import { Wand2, X } from 'lucide-react'

// Edit a finished or uploaded video with the H3 edit LoRAs (issue #54). Sizes, lengths and times come from the lab
// runs on the RTX 3080 10 GB; the server enforces the same limits (backend/video_edit.py) and answers with the reason.
type Task = 'vfx' | 'outfit' | 'style' | 'head'
type SourceJob = { id: string; width: number; height: number; duration: number }

const TASKS: { id: Task; label: string; detail: string }[] = [
  { id: 'vfx', label: 'שינוי בטקסט', detail: 'משנה דבר אחד לפי משפט: בגד, שיער, כובע, משקפיים, חפץ בחדר' },
  { id: 'outfit', label: 'בגדים מתמונות', detail: 'מלביש את הבגדים מהתמונות שלך · 480 בלבד · לפעמים לא נקלט: הרץ שוב' },
  { id: 'style', label: 'סגנון מצויר', detail: 'מצייר מחדש את כל הסרטון: אנימה, קומיקס, מנגה, קרטון' },
  { id: 'head', label: 'החלפת ראש', detail: 'ראש ופנים מתמונה · הגוף, התנועה והקול נשארים' },
]
const STYLES = [
  { id: 'anime', label: 'אנימה' }, { id: 'comic', label: 'קומיקס' }, { id: 'manga', label: 'מנגה (שחור־לבן)' },
  { id: 'cel', label: 'קרטון' }, { id: 'custom', label: 'משלי' },
]
// Lab times on the RTX 3080 with the models loaded (the first run of a session also loads ~35 GB of models).
const SIZES = [
  { id: '480', label: '480×864', detail: 'ברירת מחדל · כ־2 דקות ל־5 שניות · כ־5 דקות ל־10' },
  { id: '704', label: '704×1280', detail: 'חד יותר · כ־5.5 דקות ל־5 שניות · 5 שניות בלבד' },
]
const UPLOAD_ACCEPT = 'video/mp4,video/quicktime,video/webm,video/x-matroska'
const PHOTO_ACCEPT = 'image/jpeg,image/png,image/webp'

export function VideoEditSheet({ job, csrf, onClose, onQueued }: {
  job?: SourceJob; csrf: string; onClose: () => void; onQueued: () => void
}) {
  const [task, setTask] = useState<Task>('vfx')
  const [size, setSize] = useState('480')
  const [seconds, setSeconds] = useState(5)
  const [prompt, setPrompt] = useState('')
  const [style, setStyle] = useState('anime')
  const [face, setFace] = useState('')
  const [photos, setPhotos] = useState<(File | null)[]>([null, null])
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose() }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [busy, onClose])

  const only480 = task === 'outfit'
  const chooseTask = (next: Task) => {
    setTask(next); setError(''); setPhotos([null, null])
    if (next === 'outfit') setSize('480')
  }
  const chooseSize = (next: string) => { setSize(next); if (next !== '480') setSeconds(5) }
  const photoSlots = task === 'outfit' ? 2 : task === 'head' ? 1 : 0
  const setPhoto = (index: number, next: File | null) => setPhotos(current => current.map((item, i) => i === index ? next : item))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!job && !file) { setError('בחר וידאו'); return }
    const chosen = photos.slice(0, photoSlots).filter((item): item is File => Boolean(item))
    if (task === 'head' && chosen.length !== 1) { setError('צרף תמונה אחת של הראש'); return }
    if (task === 'outfit' && !chosen.length) { setError('צרף תמונה אחת או שתיים של הבגדים'); return }
    setBusy(true); setError('')
    try {
      const form = new FormData()
      if (job) form.append('source_job_id', job.id)
      else form.append('video', file as File)
      form.append('task', task)
      form.append('size', size)
      form.append('seconds', String(seconds))
      form.append('prompt', prompt)
      form.append('style', task === 'style' ? style : '')
      form.append('face', task === 'head' ? face : '')
      chosen.forEach(photo => form.append('photos', photo))
      const response = await fetch('/api/edit', { method: 'POST', headers: { 'X-CSRF-Token': csrf }, body: form })
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

  const promptHint = task === 'outfit'
    ? 'Change his shirt into the leather jacket from @1 and put the cap from @2 on his head, while preserving his face, gestures, lip movements, the room and the camera.'
    : 'Change the man\'s navy polo shirt into a red and black checked flannel shirt, while preserving his face, gestures, lip movements, the room and the camera.'
  return <div className="dialog-backdrop app-modal-backdrop" onMouseDown={() => { if (!busy) onClose() }}>
    <form className="app-modal post-sheet" role="dialog" aria-modal="true" onSubmit={submit} onMouseDown={event => event.stopPropagation()}>
      <div className="app-modal-head"><div className="app-modal-icon"><Wand2 size={21} /></div><button type="button" className="app-modal-close" onClick={onClose} disabled={busy} aria-label="סגירה"><X size={17} /></button></div>
      <div><span className="app-modal-eyebrow">{job ? 'עריכת וידאו מוכן · עבודה חדשה בתור' : 'העלאת קובץ · עבודה חדשה בתור'}</span><h2>עריכת וידאו עם H3</h2></div>
      {!job && <label className="post-sheet-file">
        <input type="file" accept={UPLOAD_ACCEPT} disabled={busy} onChange={event => { setFile(event.target.files?.[0] || null); setError('') }} />
        <span>{file ? file.name : 'בחר וידאו (MP4, MOV, WebM, MKV · עד 500MB)'}</span>
      </label>}
      {job && <p dir="ltr" className="post-sheet-source">{job.width}×{job.height} · {job.duration.toFixed(2)} s</p>}
      <div className="post-sheet-options" role="radiogroup" aria-label="סוג עריכה">
        {TASKS.map(item => <button key={item.id} type="button" role="radio" aria-checked={task === item.id}
          className={task === item.id ? 'active' : ''} onClick={() => chooseTask(item.id)} disabled={busy}>
          <strong>{item.label}</strong><small>{item.detail}</small>
        </button>)}
      </div>
      {task === 'style' && <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="סגנון">
        {STYLES.map(item => <button key={item.id} type="button" role="radio" aria-checked={style === item.id}
          className={style === item.id ? 'active' : ''} onClick={() => setStyle(item.id)} disabled={busy}><strong>{item.label}</strong></button>)}
      </div>}
      {(task === 'vfx' || task === 'outfit' || (task === 'style' && style === 'custom')) && <label className="edit-sheet-field">
        <span>{task === 'style' ? 'תאר את הסגנון במשפט אחד (באנגלית): הקווים, הצבעים וההצללה' : 'המשפט (באנגלית): מה לשנות, ומה לשמור'}</span>
        <textarea dir="ltr" rows={4} value={prompt} disabled={busy} onChange={event => setPrompt(event.target.value)}
          placeholder={task === 'style' ? 'Transform this video into a watercolor painting with soft wet edges and pastel colours.' : promptHint} />
      </label>}
      {photoSlots > 0 && <div className="edit-sheet-photos">
        {Array.from({ length: photoSlots }, (_, index) => <label key={index} className="post-sheet-file">
          <input type="file" accept={PHOTO_ACCEPT} disabled={busy} onChange={event => setPhoto(index, event.target.files?.[0] || null)} />
          <span>{photos[index]?.name || (task === 'head' ? 'תמונת הראש (כל הראש, מהשיער עד הסנטר)' : `תמונה ${index + 1}${index ? ' (לא חובה)' : ''} · @${index + 1} · פריט אחד על רקע נקי`)}</span>
        </label>)}
      </div>}
      {task === 'head' && <label className="edit-sheet-field">
        <span>תאר את הפנים שבתמונה בכמה מילים (באנגלית)</span>
        <input dir="ltr" value={face} disabled={busy} onChange={event => setFace(event.target.value)}
          placeholder="Male, oval face, fair skin, blue-grey eyes, short blond hair, trimmed light brown beard, no glasses" />
      </label>}
      <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="גודל">
        {SIZES.map(item => <button key={item.id} type="button" role="radio" aria-checked={size === item.id}
          className={size === item.id ? 'active' : ''} onClick={() => chooseSize(item.id)} disabled={busy || (only480 && item.id !== '480')}>
          <strong dir="ltr">{item.label}</strong><small>{only480 && item.id !== '480' ? 'בגדים מתמונות לא נקלטו ב־704 בבדיקות' : item.detail}</small>
        </button>)}
      </div>
      <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="אורך">
        {[5, 10].map(value => <button key={value} type="button" role="radio" aria-checked={seconds === value}
          className={seconds === value ? 'active' : ''} onClick={() => setSeconds(value)} disabled={busy || (value === 10 && size !== '480')}>
          <strong>{value} שניות</strong><small>{value === 10 ? (size === '480' ? 'מתחילת הקליפ' : 'ב־480 בלבד') : 'מתחילת הקליפ'}</small>
        </button>)}
      </div>
      <p className="post-sheet-note">H3 עם LoRA עריכה ו־LoRA מהירות (4 צעדים). התנועה, הפנים, השפתיים והסאונד של המקור נשמרים. כל הרצה מקבלת seed חדש: אם העריכה לא נקלטה או הוסיפה משהו מוזר, הרץ שוב. קליפ לרוחב מקבל את אותם גדלים לרוחב. כדי לחדד תוצאה של 480: הגדלה עם RTX VSR מהכרטיס שלה.{task === 'head' && ' רק פנים שיש לך זכות להשתמש בהן: שלך, דמות מומצאת, או מי שהסכים.'}</p>
      {error && <p className="post-sheet-error" role="alert">{error}</p>}
      <div className="app-modal-actions"><button type="button" onClick={onClose} disabled={busy}>ביטול</button><button type="submit" className="confirm" disabled={busy}>{busy ? (job ? 'מוסיף…' : 'מעלה…') : 'הוסף לתור'}</button></div>
    </form>
  </div>
}
