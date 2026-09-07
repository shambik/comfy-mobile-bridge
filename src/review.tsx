import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Clapperboard, Eye, FileImage, Film, LoaderCircle, ShieldAlert, XCircle } from 'lucide-react'

const REVIEW_ID = 'shadow_on_the_block_20260901'
// Version the static fallback so a stale bridge process cannot serve an older
// review manifest or storyboard package from the same production URL.
const STATIC_REVIEW_BASE = `/review-packages/${REVIEW_ID}_review_v002`

type ReviewSummary = {
  planned_shots: number
  available_opening_frames: number
  available_image_evidence: number
  available_video_clips: number
  final_master_exists: boolean
  user_rejected_shots: string[]
}

type ReviewImage = {
  path: string
  shot?: string | null
  category: 'opening' | 'evidence' | 'other' | string
  label: string
  revision: string
  status: string
}

type ReviewShot = {
  shot: string
  editorial_window: string
  generation_window: string
  mode: string
  seed: string
  job: string
  status: string
  status_class: string
  images: string[]
  video_files: string[]
}

type IdentityFinding = {
  shot: string
  status: 'pass' | 'hold' | 'reject' | string
  note: string
}

type IdentityAudit = {
  status: string
  scope: string
  method: string
  anchor: string[]
  findings: IdentityFinding[]
  next_gate: string
}

type ReviewManifest = {
  title: string
  production_id: string
  generated_at: string
  review_only: boolean
  reference_image: string
  storyboard_image: string
  storyboard_image_kind?: string
  contact_sheets: string[]
  source_documents: string[]
  summary: ReviewSummary
  identity_audit?: IdentityAudit
  shots: ReviewShot[]
  images: ReviewImage[]
  videos: string[]
}

type ImageFilter = 'all' | 'opening' | 'evidence' | 'other'
type AssetBase = 'api' | 'static'

function assetUrl(path: string, base: AssetBase): string {
  const encodedPath = path.split('/').map(segment => encodeURIComponent(segment)).join('/')
  return base === 'static'
    ? `${STATIC_REVIEW_BASE}/${encodedPath}`
    : `/api/reviews/${REVIEW_ID}/asset/${encodedPath}`
}

function statusTone(value: string): string {
  const status = value.toLowerCase()
  if (status.includes('reject')) return 'reject'
  if (status.includes('approved') || status.includes('pass')) return 'pass'
  if (status.includes('hold')) return 'hold'
  if (status.includes('complete')) return 'complete'
  if (status.includes('retry')) return 'retry'
  if (status.includes('queued')) return 'queued'
  return 'evidence'
}

function AuditIcon({ status }: { status: string }) {
  if (status === 'pass') return <CheckCircle2 size={15} />
  if (status === 'reject') return <XCircle size={15} />
  return <AlertTriangle size={15} />
}

function SummaryCard({ label, value, tone = '' }: { label: string; value: string | number; tone?: string }) {
  return <div className={`review-stat ${tone}`}><strong>{value}</strong><span>{label}</span></div>
}

export function FrameReviewPage() {
  const [manifest, setManifest] = useState<ReviewManifest | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [assetBase, setAssetBase] = useState<AssetBase>('api')
  const [imageFilter, setImageFilter] = useState<ImageFilter>('all')
  const [shotFilter, setShotFilter] = useState('all')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch(`/api/reviews/${REVIEW_ID}/manifest`, { cache: 'no-store' })
      .then(async response => {
        const contentType = response.headers.get('content-type') || ''
        if (response.ok && contentType.includes('application/json')) {
          return { manifest: await response.json() as ReviewManifest, base: 'api' as AssetBase }
        }
        const fallback = await fetch(`${STATIC_REVIEW_BASE}/manifest.json`, { cache: 'no-store' })
        if (!fallback.ok) throw new Error(`Review manifest request failed (${response.status})`)
        return { manifest: await fallback.json() as ReviewManifest, base: 'static' as AssetBase }
      })
      .then(value => {
        if (!cancelled) {
          setManifest(value.manifest)
          setAssetBase(value.base)
          setError('')
        }
      })
      .catch(reason => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'Could not load the review package')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const filteredImages = useMemo(() => {
    if (!manifest) return []
    return manifest.images.filter(image => {
      const matchesType = imageFilter === 'all' || image.category === imageFilter
      const matchesShot = shotFilter === 'all' || image.shot === shotFilter
      return matchesType && matchesShot
    })
  }, [imageFilter, manifest, shotFilter])

  if (loading) {
    return <section className="review-page review-loading" aria-live="polite"><LoaderCircle className="spin" size={22} /> Loading frame review package…</section>
  }

  if (error || !manifest) {
    return <section className="review-page review-error"><ShieldAlert size={22} /><div><h2>Frame review unavailable</h2><p>{error || 'The review package is not available yet.'}</p><small>Build the review package, then refresh this tab.</small></div></section>
  }

  const summary = manifest.summary
  const audit = manifest.identity_audit
  const auditFindings = audit?.findings || []
  const filteredShots = manifest.shots.filter(shot => shotFilter === 'all' || shot.shot === shotFilter)

  return <section className="review-page" dir="ltr">
    <header className="review-page-head">
      <div>
        <span className="eyebrow"><FileImage size={15} /> Frame audit · storyboard gate</span>
        <h2>{manifest.title}</h2>
        <p>Existing evidence only. This page does not start generation or approve footage.</p>
      </div>
      <div className="review-gate-badge"><Eye size={14} /> Review only · no new video</div>
    </header>

    <div className="review-stat-grid" aria-label="Review summary">
      <SummaryCard label="Planned shots" value={summary.planned_shots} />
      <SummaryCard label="Opening frames" value={summary.available_opening_frames} />
      <SummaryCard label="Still evidence" value={summary.available_image_evidence} />
      <SummaryCard label="Video artifacts" value={summary.available_video_clips} />
      <SummaryCard label="Final master" value={summary.final_master_exists ? 'Exists' : 'Not built'} tone={summary.final_master_exists ? 'pass' : 'hold'} />
    </div>

    {audit && <section className={`review-audit-banner ${statusTone(audit.status)}`}>
      <div className="review-audit-banner-icon"><ShieldAlert size={21} /></div>
      <div><strong>Identity gate: {audit.status.toUpperCase()}</strong><p>{audit.next_gate}</p><small>{audit.scope} · {audit.method}</small></div>
    </section>}

    <div className="review-hero-grid">
      <article className="review-panel review-reference-card">
        <header><span><Eye size={15} /> Identity anchor</span><small>Supplied singer reference</small></header>
        <figure><img src={assetUrl(manifest.reference_image, assetBase)} alt="Singer identity reference" /></figure>
        <p className="review-reference-caption">Lock the face, blue-eye read, dreadlock colors, neon paint, black mesh vest, beads, pendant, arm wraps and body. The microphone is an optional performance prop, not an identity requirement.</p>
      </article>

      <article className="review-panel review-storyboard-card">
        <header><span><Clapperboard size={15} /> Director storyboard</span><small>{manifest.storyboard_image_kind === 'director_previsualization_board' ? 'Full-size visual intention board' : 'Opening-frame evidence fallback'}</small></header>
        <figure><img src={assetUrl(manifest.storyboard_image, assetBase)} alt="Full-size director storyboard showing the intended music-video arc" /></figure>
        <p className="review-reference-caption">This board communicates the intended visual arc, performance beats, locations, lighting and edit language. The shot table below remains the timing/source of truth.</p>
      </article>
    </div>

    {audit && <section className="review-panel review-audit-panel">
      <div className="review-panel-head"><div><span className="eyebrow"><ShieldAlert size={15} /> Identity findings</span><h3>Frame-by-frame gate</h3></div><small>Blue eyes must remain readable when the face is visible</small></div>
      <div className="review-finding-grid">
        {auditFindings.map(finding => <div className={`review-finding ${statusTone(finding.status)}`} key={finding.shot}>
          <div className="review-finding-head"><b>{finding.shot}</b><span><AuditIcon status={statusTone(finding.status)} /> {finding.status}</span></div>
          <p>{finding.note}</p>
        </div>)}
      </div>
    </section>}

    <section className="review-panel review-contact-panel">
      <div className="review-panel-head"><div><span className="eyebrow"><Film size={15} /> Quick inspection</span><h3>Opening frames and QC contact sheets</h3></div><small>{manifest.contact_sheets.length} sheets · all indexed stills are below</small></div>
      <div className="review-contact-grid">
        {manifest.contact_sheets.map(path => <figure className="review-contact-card" key={path}><img loading="lazy" src={assetUrl(path, assetBase)} alt={path.split('/').pop() || 'Contact sheet'} /><figcaption>{path.split('/').pop()}</figcaption></figure>)}
      </div>
    </section>

    <section className="review-panel review-shot-panel">
      <div className="review-panel-head"><div><span className="eyebrow"><Clapperboard size={15} /> Planned sequence</span><h3>Shot and transition map</h3></div><small>Generation is still blocked by the identity gate</small></div>
      <div className="review-toolbar">
        <label><span>Filter shot</span><select value={shotFilter} onChange={event => setShotFilter(event.target.value)}><option value="all">All shots</option>{manifest.shots.map(shot => <option key={shot.shot} value={shot.shot}>{shot.shot}</option>)}</select></label>
      </div>
      <div className="review-table-scroll"><table className="review-shot-table"><thead><tr><th>Shot</th><th>Editorial window</th><th>Generation / audio window</th><th>Mode</th><th>Status</th><th>Artifacts</th></tr></thead><tbody>
        {filteredShots.map(shot => <tr key={shot.shot}><td><b>{shot.shot}</b><small>{shot.job || 'no job id'}</small></td><td dir="ltr">{shot.editorial_window}</td><td dir="ltr">{shot.generation_window}</td><td>{shot.mode}</td><td><span className={`review-status ${statusTone(shot.status)}`}>{shot.status}</span></td><td>{shot.images.length} stills · {shot.video_files.length} video</td></tr>)}
      </tbody></table></div>
    </section>

    <section className="review-panel review-gallery-panel">
      <div className="review-panel-head"><div><span className="eyebrow"><FileImage size={15} /> Complete frame gallery</span><h3>All available image evidence</h3></div><small>{filteredImages.length} shown of {manifest.images.length}</small></div>
      <div className="review-gallery-toolbar">
        <div className="review-filter-buttons" role="group" aria-label="Filter frame category">{(['all', 'opening', 'evidence', 'other'] as ImageFilter[]).map(value => <button type="button" className={imageFilter === value ? 'active' : ''} key={value} onClick={() => setImageFilter(value)}>{value === 'all' ? 'All' : value === 'opening' ? 'Opening frames' : value === 'evidence' ? 'QC evidence' : 'Other'}</button>)}</div>
        <span className="review-gallery-note">Lazy-loaded thumbnails · click an image to open full size</span>
      </div>
      <div className="review-gallery">
        {filteredImages.map(image => <a className={`review-frame-card ${statusTone(image.status)}`} href={assetUrl(image.path, assetBase)} target="_blank" rel="noreferrer" key={image.path}>
          <img loading="lazy" decoding="async" src={assetUrl(image.path, assetBase)} alt={`${image.shot || 'Evidence'} ${image.label}`} />
          <div className="review-frame-meta"><strong>{image.shot || 'Other'}</strong><span>{image.category} · {image.revision}</span><small title={image.path}>{image.label}</small></div>
        </a>)}
      </div>
      {!filteredImages.length && <div className="review-empty">No image evidence matches this filter.</div>}
    </section>

    <footer className="review-footer"><span>Source documents: {manifest.source_documents.join(' · ')}</span><span>Generated {new Date(manifest.generated_at).toLocaleString()}</span></footer>
  </section>
}
