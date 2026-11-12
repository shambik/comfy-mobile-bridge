import React, { ChangeEvent, MouseEvent, useCallback, useEffect, useRef, useState } from 'react'
import { Download, RefreshCw, Trash2, Upload, Users, X } from 'lucide-react'

// Character swap (backend/character_swap.py, issue #46): Viggle Remake, akatz or Openjutsu (issue #58).
// Manual choosing (user, 2026-11-09): you tap people, pick a character and type who each person is; no AI picks or
// describes anyone. Two modes:
//   A "reference": the character images themselves go to Viggle; render straight away.
//   B "painted":   one painted frame per marked shot: paint it yourself (download, edit anywhere, upload) or let
//                  Codex paint it; then approve and render.
type Character = { id: string; name: string; image_url: string; look: string; status: string }
type Shot = { index: number; start: number; end: number; key_frame: number; frame_url: string; painted_url?: string; painted_by?: string
  scene?: number; window?: number; empty?: boolean }
type Mark = { shot: number; x: number; y: number; character_id: string; description: string }
type Mode = 'reference' | 'painted'
type Engine = 'viggle' | 'akatz' | 'openjutsu'
type OpenjutsuOptions = { resolution: '480p' | '736p'; remove_hair: boolean }
const OPENJUTSU_MAX_SECONDS = 15.1   // tested limit (backend/openjutsu.py)
const OPENJUTSU_MAX_CHARACTERS = 3   // tested: 2 and 3 right, 4 started one person wrong
type Swap = {
  id: string; title: string; status: string; stage: string; error: string | null; frames: number; seconds: number
  trimmed: boolean; shots: Shot[]; marks: Mark[]; job_id: string | null; mode?: Mode; notes?: string
  engine?: Engine; windows?: number[][]; last_output?: string | null; openjutsu?: OpenjutsuOptions; width?: number; height?: number
}

const clock = (frame: number) => { const s = frame / 24; return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}` }

// what each flow does and where it fails (measured 2026-11-09); shown above the parts
const FLOW_INFO: Record<string, string> = {
  'viggle-reference': 'Viggle · תמונת דמות בלבד: Viggle מקבל את הסרטון, את תמונת הדמות ואת התיאור שלך, ומחליט לבד איפה הדמות ואיך היא נראית. בלי ציור. עובד טוב לאדם אחד קרוב למצלמה. חלש כשיש כמה אנשים דומים, או כשהאדם רחוק או קטן: בבדיקה נשאר שם הפרצוף המקורי.',
  'viggle-painted': 'Viggle · פריימים מצוירים: לכל חלק שיש בו מישהו להחליף צריך פריים אחד שבו הדמות מצוירת במקום האדם, באותה תנוחה ובאותו מקום. מציירים בעצמך (הורד, צייר בכל עורך, העלה) או לוחצים על Codex. Viggle נועץ את הפריים ברגע הזה ומשם ממשיך. הכי מדויק: עד 4 אנשים, אנשים רחוקים, אנשים שיוצאים וחוזרים.',
  'openjutsu': 'Openjutsu (D3voz): עד 3 אנשים ברינדור, רק מתמונות הדמויות, בלי ציור. SAM ומודל ראייה (Qwen3-VL 8B) מוצאים כל אדם בכל קטע של 6 שניות לפי התיאור שלך ולפי המקום שבו סימנת אותו, ו־H3 מצייר מחדש רק אותם, לפי בובות אפורות של האנשים המקוריים. קטעים שהם לא נמצאים בהם נשארים כמו במקור, ושאר האנשים לא משתנים. תמונה נקייה אחת לכל דמות: פוסטר עם כמה פרצופים מבלבל אותו. בבדיקה 2 ו־3 דמויות יצאו נכון; עם 4, אחד התחיל לא נכון, לכן המקסימום 3. לדמות קרחת או עם שיער שונה הפעל "הסר את השיער המקורי", אחרת היא מקבלת את קו השיער של האדם המקורי. בבדיקה (The Last Fold, 15 שניות): ברמה של Viggle 1MP בלי ציור; המשקפיים יצאו כהים ולא כמו בתמונה. עד 15 שניות.',
  'akatz': 'akatz: אדם אחד ברינדור, בלי ציור. מוצא את האדם לפי התיאור שלך בכל פריים, אז תאר איך הוא נראה (שיער, בגדים). אם האדם יוצא מהשוט, akatz עלול להחליף מישהו אחר שדומה לתיאור: בבדיקה הוא החליף גם את העוזר בחליפה הכחולה. מתאים כשהאדם נשאר בתמונה כל הסרטון. עד 149 שניות.',
}
const FLOW_COMMON = 'בכל המצבים: הסרטון מחולק לחלקים של ~5 שניות (חלק חדש גם בכל חיתוך). סמן את האנשים בחלק הראשון של כל שוט; החלקים הבאים באותו שוט ממשיכים עם אותם סימונים, אלא אם תסמן מחדש או תלחץ "אין אף אחד להחליף כאן". בכל חלק של Viggle צריך לפחות אדם אחד להחליף. סרטון ארוך מ־18 שניות מרונדר בכמה עבודות שממשיכות זו מזו ומחוברות בסוף עם הסאונד המקורי. פרטים דקים כמו ראסטות וחרוזים עלולים להבהב.'

// the sheet's first guess from where you tapped; it says nothing about who the person is
const DRAFT = /^the person (on the (far )?(left|right)|in the middle)$/

const STATUS_TEXT: Record<string, string> = {
  marking: 'סמן אנשים ובחר דמויות', preparing: 'Codex מצייר', review: 'כל הפריימים מוכנים · בדוק ורנדר',
  rendering: 'בתור ההפקה', done: 'מוכן', failed: 'נכשל',
}

// a first description from where you tapped; you replace it with who the person is
function draftDescription(x: number) {
  const side = x < 0.2 ? 'on the far left' : x < 0.4 ? 'on the left' : x < 0.6 ? 'in the middle' : x < 0.8 ? 'on the right' : 'on the far right'
  return `the person ${side}`
}

async function api<T>(url: string, csrf: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { 'X-CSRF-Token': csrf, ...(init?.headers || {}) } })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'הבקשה נכשלה')
  return data as T
}

export function SwapSheet({ jobId, csrf, onClose, onQueued }: {
  jobId?: string; csrf: string; onClose: () => void; onQueued: () => void
}) {
  const [swap, setSwap] = useState<Swap | null>(null)
  const [recent, setRecent] = useState<Swap[]>([])
  const [characters, setCharacters] = useState<Character[]>([])
  const [marks, setMarks] = useState<Mark[]>([])
  const [mode, setMode] = useState<Mode>('reference')
  const [engine, setEngine] = useState<Engine>('viggle')
  const [oj, setOj] = useState<OpenjutsuOptions>({ resolution: '736p', remove_hair: false })
  const [notes, setNotes] = useState('')
  const [empties, setEmpties] = useState<number[]>([])
  const [splitAt, setSplitAt] = useState<{ part: number; frame: number } | null>(null)
  const [active, setActive] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [newName, setNewName] = useState('')
  const [newLook, setNewLook] = useState('')
  const [editName, setEditName] = useState('')
  const [editLook, setEditLook] = useState('')
  const charFileRef = useRef<HTMLInputElement>(null)
  const started = useRef(false)

  const loadCharacters = useCallback(async () => {
    const data = await api<{ characters: Character[] }>('/api/swap/characters', csrf)
    setCharacters(data.characters)
    setActive(current => current || data.characters[0]?.id || '')
  }, [csrf])

  const run = async (work: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await work() } catch (exc) { setError(exc instanceof Error ? exc.message : 'הבקשה נכשלה') } finally { setBusy(false) }
  }

  const open = (item: Swap) => { setSwap(item); setMarks(item.marks || []); setMode(item.mode || 'reference'); setEngine(item.engine || 'viggle'); setOj(item.openjutsu || { resolution: '736p', remove_hair: false }); setNotes(item.notes || ''); setEmpties(item.shots.filter(s => s.empty).map(s => s.index)) }
  const begin = (form: FormData) => run(async () => open(await api<Swap>('/api/swap', csrf, { method: 'POST', body: form })))

  useEffect(() => { void loadCharacters() }, [loadCharacters])
  useEffect(() => {
    if (started.current) return
    started.current = true
    if (jobId) { const form = new FormData(); form.append('job_id', jobId); void begin(form) }
    else void api<{ swaps: Swap[] }>('/api/swaps', csrf).then(data => setRecent(data.swaps)).catch(() => undefined)
  }, [jobId]) // eslint-disable-line react-hooks/exhaustive-deps

  // follow Codex painting and rendering
  useEffect(() => {
    if (!swap || !['preparing', 'rendering'].includes(swap.status)) return
    const timer = window.setInterval(() => {
      void api<Swap>(`/api/swap/${swap.id}`, csrf).then(setSwap).catch(() => undefined)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [swap, csrf])

  const editable = !!swap && ['marking', 'review', 'failed', 'done'].includes(swap.status)

  const addMark = (shot: number, event: MouseEvent<HTMLImageElement>) => {
    if (!editable) return
    if (!active) { setError('הוסף קודם דמות לספרייה'); return }
    const box = event.currentTarget.getBoundingClientRect()
    const x = (event.clientX - box.left) / box.width
    setMarks(current => [...current, { shot, x, y: (event.clientY - box.top) / box.height, character_id: active,
      description: draftDescription(x) }])
    setEmpties(current => current.filter(i => i !== shot))
  }
  const updateMark = (target: Mark, values: Partial<Mark>) =>
    setMarks(current => current.map(mark => mark === target ? { ...mark, ...values } : mark))

  // the selected character's name and look, editable below the library
  const activeCharacter = characters.find(c => c.id === active)
  useEffect(() => { setEditName(activeCharacter?.name || ''); setEditLook(activeCharacter?.look || '') }, [activeCharacter?.id, activeCharacter?.name, activeCharacter?.look])
  const editChanged = !!activeCharacter && (editName.trim() !== activeCharacter.name || editLook.trim() !== (activeCharacter.look || ''))
  const saveCharacter = () => {
    if (!activeCharacter) return
    if (!editName.trim()) { setError('לדמות חייב להיות שם'); return }
    void run(async () => {
      await api<Character>(`/api/swap/characters/${activeCharacter.id}`, csrf, { method: 'PATCH',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: editName.trim(), look: editLook.trim() }) })
      await loadCharacters()
    })
  }
  const deleteCharacter = (c: Character) => {
    const used = marks.filter(m => m.character_id === c.id).length
    const warn = used ? `\nהיא מסומנת ב־${used} ${used === 1 ? 'אדם' : 'אנשים'} בהחלפה הזו, והסימון יוסר.` : ''
    if (!window.confirm(`למחוק את הדמות "${c.name}"?\nהתמונה והתיאור שלה יימחקו מהספרייה. החלפות שכבר רונדרו לא משתנות.${warn}`)) return
    void run(async () => {
      await api(`/api/swap/characters/${c.id}`, csrf, { method: 'DELETE' })
      setMarks(current => current.filter(m => m.character_id !== c.id))
      if (active === c.id) setActive('')
      await loadCharacters()
    })
  }

  const addCharacter = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!newName.trim()) { setError('תן שם לדמות לפני העלאת התמונה'); return }
    void run(async () => {
      const form = new FormData(); form.append('name', newName.trim()); form.append('look', newLook.trim()); form.append('image', file)
      const added = await api<Character>('/api/swap/characters', csrf, { method: 'POST', body: form })
      setNewName(''); setNewLook(''); setActive(added.id); await loadCharacters()
    })
  }

  const saveMarks = async () => {
    if (!swap) throw new Error('אין החלפה פתוחה')
    const saved = await api<Swap>(`/api/swap/${swap.id}/marks`, csrf, { method: 'PUT',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ marks, mode, notes, engine, empty: empties, openjutsu: oj }) })
    return saved
  }
  const render = () => run(async () => {
    const saved = await saveMarks()
    if (engine === 'viggle' && mode === 'painted') {
      const missing = saved.shots.filter(shot => partMarks(shot.index).marks.length > 0 && !shot.painted_url)
      if (missing.length) throw new Error(`חסר פריים מצויר לחלק ${missing.map(s => s.index + 1).join(', ')}`)
    }
    setSwap(await api<Swap>(`/api/swap/${saved.id}/render`, csrf, { method: 'POST' }))
    onQueued()
  })
  const codexPaint = () => run(async () => {
    await saveMarks()
    if (swap) setSwap(await api<Swap>(`/api/swap/${swap.id}/prepare`, csrf, { method: 'POST' }))
  })
  const codexRepaint = (shot: number) => run(async () => {
    await saveMarks()
    if (swap) setSwap(await api<Swap>(`/api/swap/${swap.id}/shots/${shot}/repaint`, csrf, { method: 'POST' }))
  })
  const uploadPainted = (shot: number, event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !swap) return
    void run(async () => {
      await saveMarks()
      const form = new FormData(); form.append('image', file)
      setSwap(await api<Swap>(`/api/swap/${swap.id}/shots/${shot}/painted`, csrf, { method: 'POST', body: form }))
    })
  }

  // split a part where people change, so each half gets its own frame (saves the marks first: indices move)
  const splitPart = () => run(async () => {
    if (!swap || !splitAt) return
    await saveMarks()
    const saved = await api<Swap>(`/api/swap/${swap.id}/parts/${splitAt.part}/split`, csrf, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frame: splitAt.frame }) })
    setSplitAt(null); open(saved)
  })

  // re-render only from this part's window onward; the finished video before it is kept and stitched
  const rerenderFrom = (part: number, only = false) => run(async () => {
    if (!swap) return
    const saved = await saveMarks()
    setSwap(await api<Swap>(`/api/swap/${saved.id}/rerender`, csrf, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ from_part: part, only }) }))
    onQueued()
  })

  const removeSwap = (item: Swap) => {
    const keeps = item.job_id ? '\nהסרטון שכבר רונדר נשאר בתור.' : ''
    if (!window.confirm(`להסיר את "${item.title}" מהרשימה?\nהסימונים והפריימים של ההחלפה יימחקו.${keeps}`)) return
    void run(async () => {
      await api<{ deleted: boolean }>(`/api/swap/${item.id}`, csrf, { method: 'DELETE' })
      setRecent(current => current.filter(s => s.id !== item.id))
    })
  }

  const shotMarks = (shot: number) => marks.filter(m => m.shot === shot)
  // a part's people: its own marks, or the ones carried over from the part before it in the same shot
  const partMarks = (index: number): { marks: Mark[]; carried: boolean } => {
    const own = shotMarks(index)
    const part = swap?.shots[index]
    if (own.length || !swap || !part || part.scene === undefined || empties.includes(index)) return { marks: own, carried: false }
    const before = swap.shots.slice(0, index).reverse().find(p => p.scene === part.scene)
    return before ? { marks: partMarks(before.index).marks, carried: true } : { marks: [], carried: false }
  }
  const scenes = new Set(swap?.shots.map(s => s.scene ?? s.index)).size
  const windows = swap?.windows?.length || 1
  const jobs = engine === 'viggle' && windows > 4 ? Math.ceil(windows / 4) : 1
  const people = new Set(marks.map(m => m.character_id)).size
  // measured: Openjutsu 15 s in 13-15 min at 480p, 27 min at 736p
  const minutes = swap ? (engine === 'akatz' ? Math.ceil(swap.seconds / 5) * 6
    : engine === 'openjutsu' ? Math.ceil(swap.seconds * (oj.resolution === '480p' ? 1 : 1.9)) : windows * 9) : 0
  const ojTooLong = engine === 'openjutsu' && !!swap && swap.seconds > OPENJUTSU_MAX_SECONDS
  const warnings: string[] = []
  if (marks.some(m => DRAFT.test(m.description.trim())))
    warnings.push('תאר כל אדם במילים שלך: שיער, בגדים, מה הוא עושה. "the person on the left" לבד לא מספיק למודל.')
  if (engine === 'viggle' && mode === 'reference' && people > 1)
    warnings.push('תמונת דמות בלבד עם כמה דמויות לא אמין: בבדיקה עם 4 אחד פוספס, ובבדיקה עם 2 שתי הדמויות התערבבו. פריימים מצוירים עבדו עם 2-4 אנשים.')
  if (engine === 'akatz' && people > 1) warnings.push('akatz מחליף אדם אחד ברינדור: השאר סימון של דמות אחת.')
  if (engine === 'openjutsu' && people > OPENJUTSU_MAX_CHARACTERS) warnings.push(`Openjutsu מחליף עד ${OPENJUTSU_MAX_CHARACTERS} אנשים ברינדור: השאר עד ${OPENJUTSU_MAX_CHARACTERS} דמויות.`)
  if (ojTooLong) warnings.push(`Openjutsu נבדק עד ${OPENJUTSU_MAX_SECONDS} שניות; לסרטון ארוך יותר השתמש ב־Viggle.`)

  return <div className="dialog-backdrop app-modal-backdrop" onMouseDown={() => { if (!busy) onClose() }}>
    <div className="app-modal post-sheet swap-sheet" role="dialog" aria-modal="true" onMouseDown={event => event.stopPropagation()}>
      <div className="app-modal-head"><div className="app-modal-icon"><Users size={21} /></div>
        <button type="button" className="app-modal-close" onClick={onClose} disabled={busy} aria-label="סגירה"><X size={17} /></button></div>
      <div><span className="app-modal-eyebrow">Viggle Remake / akatz / Openjutsu</span><h2>החלפת דמות</h2></div>

      {!swap && !jobId && <>
        <label className="post-sheet-file"><input type="file" accept="video/mp4,video/quicktime,video/webm,video/x-matroska" disabled={busy}
          onChange={event => { const file = event.target.files?.[0]; if (file) { const form = new FormData(); form.append('video', file); void begin(form) } }} />
          <span>{busy ? 'מעלה ומכין…' : 'בחר וידאו (MP4, MOV, WebM, MKV)'}</span></label>
        {recent.length > 0 && <div className="swap-recent"><span>המשך החלפה קודמת</span>
          {recent.map(item => <div className="swap-recent-row" key={item.id}>
            <button type="button" onClick={() => open(item)}>
              <b dir="auto">{item.title}</b><small>{STATUS_TEXT[item.status] || item.status}</small></button>
            <button type="button" className="swap-recent-delete" aria-label="הסר מהרשימה" disabled={busy || item.status === 'preparing'}
              onClick={() => removeSwap(item)}><Trash2 size={15} /></button></div>)}</div>}
      </>}
      {!swap && jobId && <p className="post-sheet-source">{busy ? 'מכין את הסרטון ומחפש חיתוכים…' : ''}</p>}

      {swap && <>
        <p className="post-sheet-source" dir="auto">{swap.title} · <bdi>{swap.seconds} s · {scenes} {scenes === 1 ? 'שוט' : 'שוטים'} · {swap.shots.length} {swap.shots.length === 1 ? 'חלק' : 'חלקים'}</bdi>
          {swap.trimmed && ` · משתמשים ב־${swap.seconds} השניות הראשונות`}
          {jobs > 1 && <> · <bdi>{jobs} רינדורים שממשיכים זה מזה, ואז חיבור</bdi></>}</p>
        <p className="swap-status"><b>{STATUS_TEXT[swap.status] || swap.status}</b>{swap.stage && ` · ${swap.stage}`}</p>

        <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="מנוע">
          {(['viggle', 'akatz', 'openjutsu'] as Engine[]).map(item => <button type="button" key={item} role="radio" aria-checked={engine === item}
            className={engine === item ? 'active' : ''} onClick={() => setEngine(item)} disabled={!editable}>
            <strong>{item === 'viggle' ? 'Viggle Remake' : item === 'akatz' ? 'akatz V1.5' : 'Openjutsu'}</strong>
            <small>{item === 'viggle' ? 'עד 4 אנשים ברינדור · ~9 דקות לכל 5 שניות'
              : item === 'akatz' ? 'אדם אחד ברינדור · מוצא אותו לפי התיאור (SAM) · ~6 דקות לכל 5 שניות'
              : 'עד 3 אנשים · רק תמונות דמויות · עד 15 שניות · ~9 דקות לכל 5 שניות ב־736'}</small>
          </button>)}
        </div>

        {engine === 'openjutsu' && <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="רזולוציה">
          {(['736p', '480p'] as const).map(item => <button type="button" key={item} role="radio" aria-checked={oj.resolution === item}
            className={oj.resolution === item ? 'active' : ''} onClick={() => setOj({ ...oj, resolution: item })} disabled={!editable}>
            <strong>{item === '736p' ? '736 (~1MP)' : '480'}</strong>
            <small>{item === '736p' ? 'כמו Viggle · ~27 דקות ל־15 שניות' : 'טיוטה · ~14 דקות ל־15 שניות'}</small>
          </button>)}
        </div>}
        {engine === 'openjutsu' && <label className="swap-toggle"><input type="checkbox" checked={oj.remove_hair} disabled={!editable}
          onChange={event => setOj({ ...oj, remove_hair: event.target.checked })} />
          <span>הסר את השיער המקורי (לדמות קרחת או עם שיער שונה)</span></label>}

        {engine === 'viggle' && <div className="post-sheet-options post-sheet-sizes" role="radiogroup" aria-label="מצב">
          {(['reference', 'painted'] as Mode[]).map(item => <button type="button" key={item} role="radio" aria-checked={mode === item}
            className={mode === item ? 'active' : ''} onClick={() => setMode(item)} disabled={!editable}>
            <strong>{item === 'reference' ? 'תמונת דמות בלבד' : 'פריימים מצוירים'}</strong>
            <small>{item === 'reference' ? 'בלי ציור · מהיר להכנה · לאדם אחד קרוב' : 'פריים מצויר לכל חלק: שלך או של Codex · הכי מדויק'}</small>
          </button>)}
        </div>}

        <details className="swap-info" open={editable && swap.marks.length === 0}>
          <summary>איך זה עובד ומה זה יודע לעשות</summary>
          <p>{FLOW_INFO[engine === 'viggle' ? `viggle-${mode}` : engine]}</p>
          <p>{FLOW_COMMON}</p>
        </details>

        {editable && <div className="swap-library">
          <span>דמויות · בחר דמות ואז הקש על האדם בתמונה</span>
          <div className="swap-characters">{characters.map(c => <button type="button" key={c.id}
            className={active === c.id ? 'active' : ''} onClick={() => setActive(c.id)} title={c.look}>
            <img src={c.image_url} alt="" /><small dir="auto">{c.name}</small>
            <i role="button" aria-label="מחק דמות" onClick={event => { event.stopPropagation(); if (!busy) deleteCharacter(c) }}><Trash2 size={12} /></i>
          </button>)}</div>
          {activeCharacter && <div className="swap-edit"><span>עריכת הדמות שנבחרה</span>
            <input value={editName} onChange={event => setEditName(event.target.value)} placeholder="שם" aria-label="שם הדמות" />
            <textarea value={editLook} onChange={event => setEditLook(event.target.value)} rows={2} dir="ltr" aria-label="איך היא נראית"
              placeholder="what they look like, in English (optional): bald, round green sunglasses, black three-piece suit" />
            <button type="button" onClick={saveCharacter} disabled={busy || !editChanged}>שמור</button></div>}
          <span>דמות חדשה</span>
          <div className="swap-add"><input value={newName} onChange={event => setNewName(event.target.value)} placeholder="שם דמות חדשה" />
            <input value={newLook} onChange={event => setNewLook(event.target.value)} placeholder="איך היא נראית (באנגלית, לא חובה)" dir="ltr" />
            <button type="button" onClick={() => charFileRef.current?.click()} disabled={busy}><Upload size={14} /> תמונה</button>
            <input ref={charFileRef} type="file" accept="image/*" hidden onChange={addCharacter} /></div>
        </div>}

        <div className="swap-shots">{swap.shots.map(shot => <div className="swap-shot" key={shot.index}>
          <small dir="ltr">Part {shot.index + 1} · {clock(shot.start)}–{clock(shot.end)}{scenes > 1 ? ` · shot ${(shot.scene ?? shot.index) + 1}` : ''}</small>
          <div className="swap-pair">
            <div className="swap-frame"><img src={shot.frame_url} alt="" onClick={event => addMark(shot.index, event)} />
              {partMarks(shot.index).marks.map((mark, i) => <span key={i} className={`swap-mark ${partMarks(shot.index).carried ? 'carried' : ''}`} style={{ left: `${mark.x * 100}%`, top: `${mark.y * 100}%` }}>{i + 1}</span>)}</div>
            {engine === 'viggle' && mode === 'painted' && shot.painted_url && <div className="swap-frame"><img src={shot.painted_url} alt="" />
              <span className="swap-painted-by">{shot.painted_by === 'user' ? 'שלך' : 'Codex'}</span></div>}
          </div>
          {shotMarks(shot.index).map((mark, i) => <div className="swap-mark-row" key={i}>
            <b>{i + 1}</b>
            <select value={mark.character_id} onChange={event => updateMark(mark, { character_id: event.target.value })} disabled={!editable}>
              {characters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            <input dir="ltr" value={mark.description} onChange={event => updateMark(mark, { description: event.target.value })}
              placeholder={engine === 'akatz' ? 'how they look: man with grey hair in a grey suit' : 'who is it: the man on the left in the grey hoodie'} disabled={!editable} />
            {editable && <button type="button" onClick={() => setMarks(current => current.filter(m => m !== mark))}>הסר</button>}
          </div>)}
          {shotMarks(shot.index).length === 0 && partMarks(shot.index).carried && <div className="swap-carried">
            <span>ממשיך מהחלק הקודם: {partMarks(shot.index).marks.map((m, i) => `${i + 1}. ${characters.find(c => c.id === m.character_id)?.name || '?'} במקום ${m.description}`).join(' · ')}</span>
            {editable && <button type="button" onClick={() => setEmpties(current => [...current, shot.index])}>אין אף אחד להחליף כאן</button>}
            <small>אנשים זזו? הקש עליהם בתמונה כדי לסמן מחדש בחלק הזה.</small>
          </div>}
          {empties.includes(shot.index) && <div className="swap-carried">
            <span>אין החלפה בחלק הזה</span>
            {editable && <button type="button" onClick={() => setEmpties(current => current.filter(i => i !== shot.index))}>בטל</button>}
          </div>}
          {editable && engine === 'viggle' && shot.end - shot.start >= 24 && (splitAt?.part === shot.index
            ? <div className="swap-split">
                <input type="range" min={shot.start + 12} max={shot.end - 12} value={splitAt.frame}
                  onChange={event => setSplitAt({ part: shot.index, frame: Number(event.target.value) })} />
                <button type="button" onClick={splitPart} disabled={busy}>פצל ב־{clock(splitAt.frame)}</button>
                <button type="button" onClick={() => setSplitAt(null)}>ביטול</button>
                <small>כל חצי יקבל פריים משלו לסימון ולציור. לשימוש כשאנשים מופיעים ברגעים שונים באותו חלק.</small>
              </div>
            : <button type="button" className="swap-split-open" onClick={() => setSplitAt({ part: shot.index, frame: Math.round((shot.start + shot.end) / 2) })}>פצל את החלק</button>)}
          {editable && engine === 'viggle' && swap.last_output && (shot.window ?? 0) > 0 && <div className="swap-paint-actions">
            <button type="button" disabled={busy} onClick={() => rerenderFrom(shot.index, true)}>רנדר רק את החלון של החלק הזה (~9 דק')</button>
            <button type="button" disabled={busy} onClick={() => rerenderFrom(shot.index)}>רנדר מחדש מכאן עד הסוף</button>
          </div>}
          {engine === 'viggle' && mode === 'painted' && editable && partMarks(shot.index).marks.length > 0 && <div className="swap-paint-actions">
            <a href={shot.frame_url} download={`shot${shot.index + 1}_frame.png`}><Download size={13} /> הורד פריים לציור</a>
            <label><Upload size={13} /> העלה פריים מצויר<input type="file" accept="image/*" hidden onChange={event => uploadPainted(shot.index, event)} /></label>
            {shot.painted_url && <button type="button" onClick={() => codexRepaint(shot.index)} disabled={busy}><RefreshCw size={13} /> Codex יצייר מחדש</button>}
          </div>}
        </div>)}</div>

        {editable && <label className="swap-notes"><span>מה קורה בסרטון (לא חובה, באנגלית)</span>
          <textarea dir="ltr" rows={2} value={notes} onChange={event => setNotes(event.target.value)}
            placeholder="e.g. two friends talk at a rainy bus stop, then laugh" /></label>}

        {editable && warnings.map(text => <p className="post-sheet-note swap-warning" key={text}>{text}</p>)}
        {swap.error && <p className="post-sheet-error" role="alert">{swap.error}</p>}
        {swap.status === 'rendering' && <p className="post-sheet-note">ההחלפה בתור (בערך {minutes} דקות{jobs > 1 ? `, ${jobs} רינדורים ואז חיבור` : ''}). אפשר לסגור את החלון; התוצאה תופיע בתיקייה.</p>}
        {swap.status === 'done' && <p className="post-sheet-note">מוכן · אפשר לשנות סימונים ולרנדר שוב.</p>}
      </>}
      {error && <p className="post-sheet-error" role="alert">{error}</p>}

      <div className="app-modal-actions">
        <button type="button" onClick={onClose} disabled={busy}>סגור</button>
        {swap && editable && engine === 'viggle' && mode === 'painted' && <button type="button" onClick={codexPaint} disabled={busy || marks.length === 0}>Codex יצייר את כולם</button>}
        {swap && editable && <button type="button" className="confirm" onClick={render} disabled={busy || marks.length === 0 || (engine === 'akatz' && people > 1) || (engine === 'openjutsu' && people > OPENJUTSU_MAX_CHARACTERS) || ojTooLong}>רנדר{marks.length ? ` · ~${minutes} דק'` : ''}</button>}
      </div>
    </div>
  </div>
}
