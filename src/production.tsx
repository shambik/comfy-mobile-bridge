import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive, Bot, Check, ChevronLeft, Clapperboard, Copy, Download, Expand, FileArchive, FolderPlus, ImagePlus,
  Gauge, LoaderCircle, MessageSquare, Pause, Pencil, Play, RefreshCw, RotateCcw, Send, Settings,
  ShieldCheck, Sparkles, Square, Trash2, Upload, UserRound, X,
} from 'lucide-react'
import { AppModal, useAppModal } from './app-modal'
import { FeedbackToast, useFeedback } from './feedback'

type ModelOption = { id: string; name: string; efforts: string[] }
type MegapixelRule = { max_duration: number; megapixels: number }
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
  agy_effort: string; generation_turbo_profile: string; generation_steps: number; generation_megapixels: number;
  generation_aspect_ratio?: string; generation_megapixel_rules?: MegapixelRule[];
  skills: string[]; progress: number; error?: string;
  controller_active?: boolean;
  agent_activity?: AgentActivity | null;
  generation_progress?: GenerationProgress;
  created_at: string; archived?: boolean; messages?: Message[]; message_total?: number;
  message_oldest_sequence?: number | null; messages_has_older?: boolean;
  decisions?: Decision[]; shots?: Shot[]; artifacts?: Artifact[]; references?: ReferenceMedia[]
}
type GenerationProgress = {
  job_id: string; status: string; phase: string; progress: number; step: number; total_steps: number;
  eta_seconds?: number | null; shot_id?: string | null; shot_index?: number | null; shot_title?: string | null;
}
type AgentActivity = {
  participant?: 'codex'|'agy'; runtime?: string; model?: string; effort?: string; state?: string;
  elapsed_seconds: number; idle_seconds: number; last_event?: string; process_alive: boolean; pid?: number | null;
}
type ShotAttempt = { id: string; attempt: number; job_id?: string; status: string; opening_frame_path?: string; output_path?: string; frames?: string[]; error?: string }
type Shot = {
  id: string; shot_index: number; title: string; prompt: string;
  mode: 'text'|'opening'|'reference'; continuity: 'hard_cut'|'sequential';
  audio_mode: 'silent'|'lip_sync'; audio_source: 'song'|'reference'; audio_start: number;
  audio_duration?: number; audio_reference_id?: string | null;
  duration: number; megapixels: number; aspect_ratio: string; steps: number; engine: string;
  turbo_profile: string; reference_ids: string[]; status: string; accepted_attempt?: number; attempts: ShotAttempt[]
}
type Artifact = { id: string; kind: string; url: string; metadata?: Record<string, unknown> }
type ReferenceMedia = { id: string; kind: 'image'|'video'|'audio'; name: string; notes: string; url: string; thumbnail_url?: string }
type RegularJob = { id: string; prompt: string; duration: number; status: string; mode: string; output_url?: string }

const effortLabels: Record<string, string> = { none: 'None', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', ultra: 'Ultra', max: 'Maximum' }
const defaultGates = ['treatment', 'references', 'prompts', 'shots', 'final']
const productionMessagePageSize = 60
const defaultMegapixelRules: MegapixelRule[] = [
  { max_duration: 5, megapixels: 1.5 },
  { max_duration: 8, megapixels: 1.0 },
  { max_duration: 10, megapixels: 0.7 },
  { max_duration: 11, megapixels: 0.6 },
  { max_duration: 15, megapixels: 0.5 },
]
const resolutionOptions = [
  { value: '16:9', label: '16:9 · Widescreen' },
  { value: '1:1', label: '1:1 · Square' },
  { value: '9:16', label: '9:16 · Portrait' },
  { value: '4:3', label: '4:3 · Standard' },
  { value: '3:4', label: '3:4 · Portrait standard' },
]

function copyMegapixelRules(rules?: MegapixelRule[]) {
  return (rules?.length ? rules : defaultMegapixelRules).map(rule => ({ ...rule }))
}

function mergeProductionMessagePage(current: Production | null, next: Production): Production {
  if (!current || current.id !== next.id || !next.messages?.length) return next
  const messages = new Map<number, Message>()
  for (const message of [...(current.messages || []), ...next.messages]) messages.set(message.sequence, message)
  const merged = [...messages.values()].sort((left, right) => left.sequence - right.sequence)
  const total = next.message_total ?? current.message_total
  return {
    ...next,
    messages: merged,
    message_total: total,
    message_oldest_sequence: merged[0]?.sequence ?? null,
    messages_has_older: typeof total === 'number' ? merged.length < total : next.messages_has_older,
  }
}

function MegapixelRulesEditor({ rules, onChange }: { rules?: MegapixelRule[]; onChange: (rules: MegapixelRule[]) => void }) {
  const current = copyMegapixelRules(rules)
  return <div className="ps-mp-rules">
    <div className="ps-mp-rules-heading"><div><b>MP by shot duration</b><small>The first matching rule is sent to ComfyUI as the requested one-decimal MP value. The workflow calculates exact dimensions.</small></div></div>
    <div className="ps-mp-rule-list">
      {current.map((rule, index) => {
        const start = index === 0 ? 1 : current[index - 1].max_duration + 1
        const minimum = index === 0 ? 1 : current[index - 1].max_duration + 1
        const maximum = index === current.length - 1 ? 15 : current[index + 1].max_duration - 1
        return <div className="ps-mp-rule" key={index}>
          <span>{start}–{rule.max_duration} sec</span>
          <label><span>Up to (seconds)</span><input type="number" min={minimum} max={maximum} step="1" value={rule.max_duration} onChange={event => { const value = Math.min(maximum, Math.max(minimum, Number.parseInt(event.target.value || String(rule.max_duration), 10) || rule.max_duration)); onChange(current.map((item, itemIndex) => itemIndex === index ? { ...item, max_duration: value } : item)) }} /></label>
          <label><span>Requested MP</span><input type="number" min="0.1" max="2" step="0.1" value={rule.megapixels} onChange={event => { const value = Math.min(2, Math.max(0.1, Number(Number.parseFloat(event.target.value || String(rule.megapixels)).toFixed(1)))); onChange(current.map((item, itemIndex) => itemIndex === index ? { ...item, megapixels: value } : item)) }} /></label>
        </div>
      })}
    </div>
  </div>
}
const benignTracePattern = /\bwarn(?:ing)?\b|shell_snapshot: failed to create shell snapshot|shell snapshot not supported yet for powershell|falling back to http|after_agent hook failed; continuing|codex_skills::interface: ignoring interface\.icon_(small|large)|icon path with '\.\.' must resolve under plugin assets\/|failed to refresh cached remote plugin catalog|remote plugin catalog request|codex_core_plugins::manager|event: item\.completed/i
const provisionalAgentErrorPattern = /reported an error:\s*agent execution terminated due to error\.?/i

function isBenignTrace(message: Message) {
  return message.kind === 'agent_trace'
    && message.metadata?.stream === 'stderr'
    && benignTracePattern.test(message.content)
}

const protocolTracePattern = /event:\s*(?:init|item\.completed|thread\.(?:started|completed)|session\.(?:started|completed)|turn\.(?:started|completed))\.?$|reported progress\.?$|returned status:\s*success\.?$|started via .* CLI.*$|started a work session\.?$|completed a work session\.?$|prepared its structured response\.?$|streaming its response…?$/i

function isNonMeaningfulTrace(message: Message) {
  if (message.kind !== 'agent_trace') return false
  if (provisionalAgentErrorPattern.test(message.content)) return true
  // These records were generated by the bridge, not spoken by an agent. The
  // completed structured agent card is the single authoritative response.
  if (message.metadata?.stream === 'response' || message.metadata?.heartbeat) return true
  const eventType = String(message.metadata?.event_type || '')
  if (eventType && !['reasoning_summary', 'tool_activity', 'agent_update', 'task_started', 'provider_wait'].includes(eventType)) return true
  return protocolTracePattern.test(message.content.trim())
}

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

function formatAgentDetail(value: unknown) {
  if (typeof value === 'string') return value
  try { return JSON.stringify(value, null, 2) }
  catch { return String(value) }
}

function parseAgentValue(value: unknown): unknown {
  if (typeof value !== 'string') return value
  const text = value.trim()
  if (!text.startsWith('{') && !text.startsWith('[')) return value
  try {
    const parsed: unknown = JSON.parse(text)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const entries = Object.entries(parsed as Record<string, unknown>)
      if (entries.length === 1 && ['text', 'content', 'output_text'].includes(entries[0][0]) && typeof entries[0][1] === 'string') {
        return parseAgentValue(entries[0][1])
      }
    }
    return parsed
  } catch {
    return value
  }
}

function humanizeAgentKey(key: string) {
  const acronyms = new Set(['id', 'url', 'uri', 'mp', 'fps', 'qc', 'agy', 'codex', 't2v', 'i2v', 'r2v', 'cli', 'api', 'bpm', 'sha256'])
  return key
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .map(word => acronyms.has(word.toLowerCase()) ? word.toUpperCase() : `${word.charAt(0).toUpperCase()}${word.slice(1)}`)
    .join(' ')
}

function isAgentComplex(value: unknown) {
  const parsed = parseAgentValue(value)
  return Array.isArray(parsed) || (!!parsed && typeof parsed === 'object')
}

function agentValuePreview(value: unknown) {
  const parsed = parseAgentValue(value)
  if (parsed === null || parsed === undefined) return 'Not provided'
  if (Array.isArray(parsed)) return `${parsed.length} item${parsed.length === 1 ? '' : 's'}`
  if (typeof parsed === 'object') {
    const count = Object.keys(parsed as Record<string, unknown>).length
    return `${count} field${count === 1 ? '' : 's'}`
  }
  const text = String(parsed).replace(/\s+/g, ' ').trim()
  return text.length > 130 ? `${text.slice(0, 130)}…` : text
}

function isAgentSchemaPlaceholder(value: unknown) {
  const parsed = parseAgentValue(value)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return false
  const entries = Object.entries(parsed as Record<string, unknown>)
  if (entries.length !== 1 || entries[0][0] !== 'type') return false
  const descriptor = entries[0][1]
  return descriptor === 'string' || descriptor === 'number' || (
    Array.isArray(descriptor) && descriptor.length > 0 && descriptor.every(item => ['string', 'number', 'null'].includes(String(item)))
  )
}

function isAgentSchemaEcho(message: Message) {
  const values = [
    message.content,
    message.metadata?.summary,
    message.metadata?.decision,
    message.metadata?.content,
    message.metadata?.next_action,
  ]
  return values.some(value => isAgentSchemaPlaceholder(value))
    || JSON.stringify(message.metadata?.issues || '') === JSON.stringify([{ type: ['string', 'null'] }])
}

function concreteAgentIssues(value: unknown) {
  const parsed = parseAgentValue(value)
  if (!Array.isArray(parsed)) return []
  return parsed.filter(item => !isAgentSchemaPlaceholder(item))
}

function agentSummaryFromValue(value: unknown) {
  const parsed = parseAgentValue(value)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return ''
  const record = parsed as Record<string, unknown>
  for (const key of ['reply', 'summary', 'analysis', 'assessment', 'findings', 'corrections']) {
    if (typeof record[key] === 'string' && record[key].trim()) return record[key].trim()
  }
  return ''
}

function agentVisibleSummary(message: Message, structuredContent: unknown) {
  if (isAgentSchemaEcho(message)) {
    return 'AGY returned the response schema instead of the requested analysis. This attempt is not usable and is retried once with a fresh AGY session.'
  }
  for (const candidate of [structuredContent, message.metadata?.content]) {
    const summary = agentSummaryFromValue(candidate)
    if (summary) return summary
  }
  return message.content
}

function agentStatusTone(key: string, value: unknown) {
  const name = key.toLowerCase().replace(/[_-]+/g, ' ')
  const text = typeof value === 'string' ? value.toLowerCase() : ''
  if (name === 'decision' || name === 'approval') {
    const head = text.split(/[.:\n]/, 1)[0].trim()
    if (/^(approve|approved|accept|accepted|pass|passed)\b/.test(head)) return 'positive'
    if (/^(reject|rejected|revise|regenerate|retry|fail|failed|blocked|request)\b/.test(head)) return 'negative'
    return 'warning'
  }
  if (name.includes('issue') || name.includes('error') || name.includes('failure')) return 'negative'
  if (name.includes('severity') || name.includes('priority')) {
    if (/critical|high|severe|blocker|error|urgent/.test(text)) return 'negative'
    if (/medium|moderate|warning|attention/.test(text)) return 'warning'
    if (/low|minor|info|notice/.test(text)) return 'info'
    if (/none|clear|resolved|ok|pass/.test(text)) return 'positive'
  }
  if (name.includes('next') || name.includes('intent') || name.includes('action')) return 'info'
  if (name.includes('requires user')) return value === true ? 'warning' : 'positive'
  if (name.includes('decision') || name.includes('status') || name.includes('approval') || name.includes('review')) {
    if (/reject|fail|error|invalid|blocked/.test(text)) return 'negative'
    if (/revise|pending|wait|needs|review/.test(text)) return 'warning'
    if (/approve|approved|complete|usable|ready|success|pass/.test(text)) return 'positive'
  }
  return ''
}

function agentDecisionTone(value: unknown) {
  const text = typeof value === 'string' ? value.trim().toLowerCase() : ''
  const head = text.split(/[.:\n]/, 1)[0].trim()
  if (/^(approve|approved|accept|accepted|pass|passed)\b/.test(head)) return 'positive'
  if (/^(reject|rejected|revise|regenerate|retry|fail|failed|blocked|request)\b/.test(head)) return 'negative'
  return agentStatusTone('decision', text)
}

function AgentReadableValue({ value, depth = 0 }: { value: unknown; depth?: number }) {
  const parsed = parseAgentValue(value)
  if (parsed === null || parsed === undefined) return <span className="ps-agent-null">Not provided</span>
  if (typeof parsed === 'string' || typeof parsed === 'number' || typeof parsed === 'boolean') {
    return <span className={`ps-agent-value${typeof parsed === 'string' && parsed.length > 180 ? ' long' : ''}`}>{String(parsed)}</span>
  }
  if (Array.isArray(parsed)) {
    return <div className="ps-agent-array">{parsed.length ? parsed.map((item, index) => isAgentComplex(item) ? <details className="ps-agent-array-item ps-agent-array-item-collapsible" key={`${depth}-${index}`}><summary><span className="ps-agent-item-label">Item {index + 1}</span><span className="ps-agent-field-preview">{agentValuePreview(item)}</span></summary><div className="ps-agent-array-item-content"><AgentReadableValue value={item} depth={depth + 1} /></div></details> : <div className="ps-agent-array-item" key={`${depth}-${index}`}><span className="ps-agent-item-label">Item {index + 1}</span><AgentReadableValue value={item} depth={depth + 1} /></div>) : <span className="ps-agent-null">None</span>}</div>
  }
  if (typeof parsed === 'object') {
    const entries = Object.entries(parsed as Record<string, unknown>)
    return <div className={`ps-agent-object${depth === 0 ? ' root' : ''}`}>{entries.length ? entries.map(([key, item]) => { const tone = agentStatusTone(key, item); return isAgentComplex(item) ? <details className={`ps-agent-field ps-agent-field-collapsible ${tone}`} key={`${depth}-${key}`}><summary><b>{humanizeAgentKey(key)}</b><span className="ps-agent-field-preview">{agentValuePreview(item)}</span></summary><div className="ps-agent-field-content"><AgentReadableValue value={item} depth={depth + 1} /></div></details> : <div className={`ps-agent-field ${tone}`} key={`${depth}-${key}`}><b>{humanizeAgentKey(key)}</b><AgentReadableValue value={item} depth={depth + 1} /></div> }) : <span className="ps-agent-null">No details</span>}</div>
  }
  return <span className="ps-agent-value">{String(parsed)}</span>
}

function AgentReadableDetail({ value }: { value: unknown }) {
  return <div className="ps-agent-readable"><AgentReadableValue value={value} /></div>
}

function SessionReferenceCard({ reference, onOpen }: { reference: ReferenceMedia; onOpen: (reference: ReferenceMedia) => void }) {
  const previewable = reference.kind === 'image' || reference.kind === 'video' || reference.kind === 'audio'
  return <article className="ps-session-reference">
    <button type="button" className={`ps-session-reference-preview ${reference.kind}`} onClick={() => onOpen(reference)} aria-label={`Open ${reference.name} in full view`}>
      {reference.kind === 'image' && <img src={reference.thumbnail_url || reference.url} alt={reference.name} loading="lazy" />}
      {reference.kind === 'video' && <video src={reference.url} muted preload="none" />}
      {reference.kind === 'audio' && <span>{reference.kind.toUpperCase()}</span>}
      {previewable && <i><Expand size={14} /></i>}
    </button>
    <div className="ps-session-reference-info"><b>{reference.kind}</b><span title={reference.name}>{reference.name}</span></div>
    <a href={reference.url} target="_blank" rel="noreferrer" aria-label={`Open ${reference.name} in a new tab`}>Open</a>
  </article>
}

function shotSceneReference(shot: Shot): ReferenceMedia | null {
  const accepted = shot.accepted_attempt
    ? shot.attempts.find(attempt => attempt.attempt === shot.accepted_attempt)
    : undefined
  const attempt = (accepted?.opening_frame_path ? accepted : undefined)
    || [...shot.attempts].reverse().find(item => item.opening_frame_path)
  if (!attempt?.opening_frame_path) return null
  return {
    id: `scene-frame-${attempt.id}`,
    kind: 'image',
    name: `Shot ${shot.shot_index} · scene opening frame · attempt ${attempt.attempt}`,
    notes: 'Generated scene reference used as the I2V opening frame.',
    url: attempt.opening_frame_path,
  }
}

function ShotReferenceTile({ reference, onOpen, scene = false }: {
  reference: ReferenceMedia; onOpen: (reference: ReferenceMedia) => void; scene?: boolean
}) {
  return <button type="button" className={`ps-shot-reference-tile${scene ? ' scene' : ''}`} onClick={() => onOpen(reference)} title={`Open ${reference.name}`}>
    <span className="ps-shot-reference-tile-media">
      {reference.kind === 'image' && <img src={reference.thumbnail_url || reference.url} alt={reference.name} loading="lazy" />}
      {reference.kind === 'video' && <video src={reference.url} muted preload="none" />}
      {reference.kind === 'audio' && <span className="ps-shot-reference-audio">AUDIO</span>}
      <i><Expand size={12} /></i>
    </span>
    <span className="ps-shot-reference-tile-label">{reference.name}</span>
  </button>
}

function ShotReferenceAssignments({ shot, references, onOpen }: {
  shot: Shot; references: ReferenceMedia[]; onOpen: (reference: ReferenceMedia) => void
}) {
  const assignedReferences = references.filter(reference => (shot.reference_ids || []).includes(reference.id))
  const sceneReference = shotSceneReference(shot)
  return <div className="ps-shot-assignment-preview">
    <div className="ps-shot-reference-heading"><b>Selected planning references</b><span>{assignedReferences.length ? 'Used to compose the actual scene' : 'None selected yet'}</span></div>
    {assignedReferences.length > 0 && <div className="ps-shot-reference-strip">{assignedReferences.map(reference => <ShotReferenceTile key={reference.id} reference={reference} onOpen={onOpen} />)}</div>}
    {sceneReference ? <div className="ps-shot-scene-reference"><div className="ps-shot-reference-heading"><b>Actual scene reference</b><span>Generated opening frame · sent to I2V</span></div><div className="ps-shot-reference-strip"><ShotReferenceTile reference={sceneReference} onOpen={onOpen} scene /></div></div> : <div className="ps-shot-scene-pending">No generated scene frame exists for this shot yet. The selected references are creative anchors; the agents compose a shot-specific opening frame before I2V.</div>}
  </div>
}

function ShotPlanModal({ shots, references, active, autonomous, onClose, onEdit, onRetry, onOpenReference }: {
  shots: Shot[]; references: ReferenceMedia[]; active: boolean; autonomous: boolean; onClose: () => void; onEdit: (shot: Shot) => void;
  onRetry: (shot: Shot) => void; onOpenReference: (reference: ReferenceMedia) => void
}) {
  return <div className="ps-modal-backdrop" role="presentation" onClick={onClose}>
    <section className="ps-panel ps-shot-plan-modal" role="dialog" aria-modal="true" aria-labelledby="shot-plan-title" onClick={event => event.stopPropagation()}>
      <div className="ps-panel-title">
        <Clapperboard size={18} />
        <div><h3 id="shot-plan-title">Shot plan</h3><p>{shots.length} planned shots · prompts, timing, continuity and attempts</p></div>
        <button type="button" aria-label="Close shot plan" onClick={onClose}><X size={17} /></button>
      </div>
      <div className="ps-shot-plan-list">
        {shots.map(shot => {
          const assignedReferences = references.filter(reference => (shot.reference_ids || []).includes(reference.id))
          const sceneReference = shotSceneReference(shot)
          return <article className="ps-shot-plan-card" key={shot.id}>
            <header>
              <div><span>Shot {shot.shot_index}</span><h4>{shot.title}</h4></div>
              <i className={shot.status}>{shot.status}</i>
            </header>
            <div className="ps-shot-plan-meta">
              <span>{shot.mode.toUpperCase()}</span>
              <span>{shot.continuity === 'sequential' ? 'SEQUENTIAL' : 'HARD CUT'}</span>
              <span>{shot.duration}s</span>
              <span>{shot.megapixels} MP</span>
              <span>{shot.aspect_ratio}</span>
              <span>{shot.steps} STEPS</span>
              <span>{shot.engine}</span>
              <span>{shot.turbo_profile}</span>
              {assignedReferences.length > 0 && <span>{assignedReferences.length} REF{assignedReferences.length === 1 ? '' : 'S'}</span>}
              {shot.audio_mode === 'lip_sync' && <span>LIP-SYNC</span>}
            </div>
            <div className="ps-shot-reference-summary">
              <div className="ps-shot-reference-heading"><b>Assigned creative refs</b><span>{assignedReferences.length ? 'Used to build this shot’s scene' : 'None assigned'}</span></div>
              {assignedReferences.length > 0 && <div className="ps-shot-reference-strip">{assignedReferences.map(reference => <ShotReferenceTile key={reference.id} reference={reference} onOpen={onOpenReference} />)}</div>}
              {sceneReference ? <div className="ps-shot-scene-reference"><div className="ps-shot-reference-heading"><b>Actual scene reference</b><span>Opening frame sent to I2V</span></div><div className="ps-shot-reference-strip"><ShotReferenceTile reference={sceneReference} onOpen={onOpenReference} scene /></div></div> : <div className="ps-shot-scene-pending">The shot-specific opening frame will appear here after scene preparation.</div>}
            </div>
            <details className="ps-shot-plan-details">
              <summary>Prompt and attempts</summary>
              <p>{shot.prompt}</p>
              {shot.audio_mode === 'lip_sync' && <p className="ps-shot-audio-note">Audio: {shot.audio_source === 'reference' ? 'reference audio' : 'song'} · starts at {Number(shot.audio_start || 0).toFixed(2)}s</p>}
              {shot.attempts.length > 0 && <div className="ps-shot-plan-attempts">{shot.attempts.map(attempt => <div key={attempt.id}>Attempt {attempt.attempt}: {attempt.status}{attempt.opening_frame_path && <> · <a href={attempt.opening_frame_path} target="_blank" rel="noreferrer">Opening frame</a></>}{attempt.output_path && <> · <a href={attempt.output_path} target="_blank" rel="noreferrer">Open video</a></>}</div>)}</div>}
            </details>
            <div className="ps-shot-plan-actions">
              <button type="button" onClick={() => onEdit(shot)}><Pencil size={13} /> Shot settings</button>
              {autonomous
                ? <span className="ps-shot-auto-retry"><RotateCcw size={13} /> Automatic regeneration after review</span>
                : <button type="button" onClick={() => onRetry(shot)} disabled={active}><RotateCcw size={13} /> Retry shot</button>}
            </div>
          </article>
        })}
      </div>
    </section>
  </div>
}

function extractStructuredAgentContent(value: string): unknown | null {
  const trimmed = value.trim()
  const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i)
  const candidate = fenced?.[1]?.trim() || trimmed
  if (!candidate.startsWith('{') && !candidate.startsWith('[')) return null
  const parsed = parseAgentValue(candidate)
  return parsed && typeof parsed === 'object' ? parsed : null
}

function compactAgentText(value: unknown, limit = 220) {
  const text = typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : formatAgentDetail(value).replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

function SectionError({ message, onDismiss, className = '' }: { message?: string; onDismiss: () => void; className?: string }) {
  if (!message) return null
  return <div className={`ps-error ${className}`} role="alert"><span>{message}</span><button type="button" onClick={onDismiss} aria-label="Dismiss error"><X size={14} /></button></div>
}

export function ProductionStudio({ csrf }: { csrf: string }) {
  const appModal = useAppModal()
  const feedback = useFeedback()
  const [view, setView] = useState<'room' | 'settings'>('room')
  const [models, setModels] = useState<Record<Runtime, ModelOption[]>>({ codex: [], agy: [] })
  const [modelsFetchedAt, setModelsFetchedAt] = useState('')
  const [modelsRefreshing, setModelsRefreshing] = useState(false)
  const [settings, setSettings] = useState<AgentSettings>({ codex_runtime: 'codex', codex_model: 'gpt-5.6-sol', codex_effort: 'high', agy_runtime: 'agy', agy_model: 'gemini-3.1-pro-high', agy_effort: 'high' })
  const [skills, setSkills] = useState<Skill[]>([])
  const [productions, setProductions] = useState<Production[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [production, setProduction] = useState<Production | null>(null)
  const [productionsLoading, setProductionsLoading] = useState(true)
  const [jobsLoading, setJobsLoading] = useState(true)
  const [agentCatalogLoading, setAgentCatalogLoading] = useState(true)
  const [productionLoading, setProductionLoading] = useState(false)
  const [productionLoadError, setProductionLoadError] = useState('')
  const productionRequestRef = useRef(0)
  const productionAbortRef = useRef<AbortController | null>(null)
  const productionLoadInFlightRef = useRef<{ id: string; controller: AbortController } | null>(null)
  const productionRefreshQueuedRef = useRef(false)
  const productionRefreshTimerRef = useRef<number | null>(null)
  const [olderMessagesLoading, setOlderMessagesLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  type ErrorScope = 'system' | 'intake' | 'controls' | 'chat' | 'settings' | 'skills' | 'references' | 'shots' | 'shotModal' | 'config' | 'library'
  const [sectionErrors, setSectionErrors] = useState<Partial<Record<ErrorScope, string>>>({})
  const setSectionError = (scope: ErrorScope, message = '') => setSectionErrors(current => ({ ...current, [scope]: message }))
  const clearSectionError = (scope: ErrorScope) => setSectionErrors(current => ({ ...current, [scope]: '' }))
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
  const [generationTurboProfile, setGenerationTurboProfile] = useState<'v1'|'v4'>('v1')
  const [generationSteps, setGenerationSteps] = useState(4)
  const [generationAspectRatio, setGenerationAspectRatio] = useState('16:9')
  const [generationMegapixelRules, setGenerationMegapixelRules] = useState<MegapixelRule[]>(copyMegapixelRules())
  const [selectedSkills, setSelectedSkills] = useState<string[]>([])
  const [intervention, setIntervention] = useState('')
  const [recipient, setRecipient] = useState('both')
  const [registerPath, setRegisterPath] = useState('')
  const [editingShot, setEditingShot] = useState<Shot | null>(null)
  const [showShotPlan, setShowShotPlan] = useState(false)
  const [returnToShotPlan, setReturnToShotPlan] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)
  const [configDraft, setConfigDraft] = useState<Production | null>(null)
  const [importIds, setImportIds] = useState('')
  const [regularJobs, setRegularJobs] = useState<RegularJob[]>([])
  const [referenceName, setReferenceName] = useState('')
  const [referencePrompt, setReferencePrompt] = useState('')
  const [referenceProvider, setReferenceProvider] = useState<'auto'|'codex'|'agy'>('auto')
  const [referenceGenerating, setReferenceGenerating] = useState(false)
  const [previewReference, setPreviewReference] = useState<ReferenceMedia | null>(null)
  const [showLivePrints, setShowLivePrints] = useState(() => {
    try { return window.localStorage.getItem('production-show-live-prints') === 'true' }
    catch { return false }
  })
  const messagesRef = useRef<HTMLDivElement | null>(null)
  const messageScrollRestoreRef = useRef<{ height: number; top: number } | null>(null)

  const headers = useMemo(() => ({ 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' }), [csrf])

  const loadCatalog = async (refreshModels = false) => {
    setProductionsLoading(true)
    setJobsLoading(true)
    setAgentCatalogLoading(true)

    // These requests are independent. Resolve and render each area as soon as
    // its own data arrives instead of making the production room wait for the
    // full jobs history or the CLI model discovery call.
    const productionTask = (async () => {
      try {
        const data = await jsonResponse(await fetch('/api/productions', { cache: 'no-store' }))
        setProductions(data.productions || [])
        if (!selectedId && data.productions?.length) setSelectedId(data.productions[0].id)
      } catch (reason) {
        setSectionError('system', reason instanceof Error ? reason.message : 'Unable to load productions')
      } finally {
        setProductionsLoading(false)
      }
    })()

    const jobsTask = (async () => {
      try {
        const data = await jsonResponse(await fetch('/api/jobs?limit=20&status=completed&include_library=false&include_sequences=false', { cache: 'no-store' }))
        setRegularJobs((data.jobs || []).filter((job: RegularJob) => job.status === 'completed'))
      } catch (reason) {
        setSectionError('system', reason instanceof Error ? reason.message : 'Unable to load generation history')
      } finally {
        setJobsLoading(false)
      }
    })()

    const settingsTask = (async () => {
      try {
        const data = await jsonResponse(await fetch('/api/settings/agents', { cache: 'no-store' }))
        setSettings(data)
      } catch (reason) {
        setSectionError('settings', reason instanceof Error ? reason.message : 'Unable to load agent settings')
      }
    })()

    const skillsTask = (async () => {
      try {
        const data = await jsonResponse(await fetch('/api/skills', { cache: 'no-store' }))
        setSkills(data.skills || [])
        setSelectedSkills(current => current.length ? current : (data.skills || []).filter((item: Skill) => item.enabled && item.valid).map((item: Skill) => item.id))
      } catch (reason) {
        setSectionError('skills', reason instanceof Error ? reason.message : 'Unable to load skills')
      }
    })()

    const modelsTask = (async () => {
      try {
        const data = await jsonResponse(await fetch(`/api/agents/models${refreshModels ? '?refresh=true' : ''}`, { cache: 'no-store' }))
        setModels({ codex: data.codex || [], agy: data.agy || [] })
        setModelsFetchedAt(data.fetched_at ? new Date(data.fetched_at * 1000).toLocaleTimeString() : '')
      } catch (reason) {
        setSectionError('settings', reason instanceof Error ? reason.message : 'Unable to load agent models')
      }
    })()

    try {
      await Promise.all([settingsTask, skillsTask, modelsTask])
    } finally {
      setAgentCatalogLoading(false)
      setModelsRefreshing(false)
    }
    await Promise.all([productionTask, jobsTask])
  }

  const refreshModels = async () => {
    setModelsRefreshing(true)
    await loadCatalog(true)
  }

  const loadProduction = async (
    id = selectedId, options: { force?: boolean; messageBefore?: number } = {},
  ) => {
    if (!id) { setProduction(null); setProductionLoading(false); return }
    const olderPage = options.messageBefore !== undefined
    const existing = productionLoadInFlightRef.current
    if (existing) {
      if (!options.force && existing.id === id) {
        if (!olderPage) productionRefreshQueuedRef.current = true
        return
      }
      existing.controller.abort()
    }
    const requestId = ++productionRequestRef.current
    const controller = new AbortController()
    productionAbortRef.current = controller
    productionLoadInFlightRef.current = { id, controller }
    setProductionLoadError('')
    if (!olderPage) setProductionLoading(!production || production.id !== id)
    try {
      const params = new URLSearchParams({ message_limit: String(productionMessagePageSize) })
      if (olderPage) params.set('message_before', String(options.messageBefore))
      const data = await jsonResponse(await fetch(`/api/productions/${id}?${params.toString()}`, { cache: 'no-store', signal: controller.signal }))
      if (requestId !== productionRequestRef.current) return
      setProduction(current => mergeProductionMessagePage(current, data))
      setProductions(current => current.map(item => item.id === data.id ? {
        ...item, status: data.status, stage: data.stage, progress: data.progress,
        error: data.error, archived: data.archived,
      } : item))
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      if (requestId === productionRequestRef.current) {
        const message = reason instanceof Error ? reason.message : 'Unable to load production'
        if (!olderPage && !production) setProductionLoadError(message)
        setSectionError('system', message)
      }
    } finally {
      if (requestId === productionRequestRef.current && !olderPage) setProductionLoading(false)
      if (productionAbortRef.current === controller) productionAbortRef.current = null
      if (productionLoadInFlightRef.current?.controller === controller) {
        productionLoadInFlightRef.current = null
        if (!olderPage && productionRefreshQueuedRef.current) {
          productionRefreshQueuedRef.current = false
          scheduleProductionRefresh(id)
        }
      }
    }
  }

  function scheduleProductionRefresh(id: string) {
    if (!id || productionRefreshTimerRef.current !== null) return
    productionRefreshTimerRef.current = window.setTimeout(() => {
      productionRefreshTimerRef.current = null
      void loadProduction(id)
    }, 300)
  }

  const loadOlderMessages = async () => {
    if (!production || olderMessagesLoading || !production.messages_has_older) return
    const before = production.messages?.[0]?.sequence
    if (!before) return
    if (messagesRef.current) {
      messageScrollRestoreRef.current = {
        height: messagesRef.current.scrollHeight,
        top: messagesRef.current.scrollTop,
      }
    }
    setOlderMessagesLoading(true)
    try {
      await loadProduction(production.id, { messageBefore: before })
    } finally {
      setOlderMessagesLoading(false)
    }
  }

  useEffect(() => { void loadCatalog(false) }, [])
  useEffect(() => {
    if (view === 'settings') void loadCatalog(false)
  }, [view])
  useEffect(() => {
    if (!selectedId) return
    void loadProduction(selectedId, { force: true })
    const events = new EventSource(`/api/productions/${selectedId}/events`)
    events.onmessage = () => { scheduleProductionRefresh(selectedId) }
    const refresh = () => { scheduleProductionRefresh(selectedId) }
    const eventNames = ['message.created', 'decision.created', 'decision.resolved', 'production.started', 'production.failed', 'production.recovered', 'production.reference_generation_retryable', 'production.reference_generation_retry_requested', 'shots.planned', 'shot.queued', 'shot.progress', 'shot.reviewing']
    eventNames.forEach(name => events.addEventListener(name, refresh))
    return () => {
      if (productionRefreshTimerRef.current !== null) window.clearTimeout(productionRefreshTimerRef.current)
      productionRefreshTimerRef.current = null
      productionRefreshQueuedRef.current = false
      events.close()
      productionAbortRef.current?.abort()
    }
  }, [selectedId])
  useEffect(() => {
    if (!selectedId) return
    const activeStatus = ['running', 'pausing', 'retrying', 'stopping', 'queued'].includes(production?.status || '')
      || Boolean(production?.controller_active)
    // SSE refreshes immediately on real changes. This timer is only a safety
    // net, so inactive/completed productions should not be downloaded every
    // five seconds while somebody is simply reading the room.
    const timer = window.setInterval(
      () => scheduleProductionRefresh(selectedId), activeStatus ? 10000 : 30000,
    )
    return () => window.clearInterval(timer)
  }, [selectedId, production?.status, production?.controller_active])
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
  useEffect(() => {
    const container = messagesRef.current
    if (!container) return
    const restore = messageScrollRestoreRef.current
    if (restore) {
      messageScrollRestoreRef.current = null
      window.requestAnimationFrame(() => {
        container.scrollTop = container.scrollHeight - restore.height + restore.top
      })
      return
    }
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
  }, [production?.id, production?.messages?.length, showLivePrints])

  const mutate = async (url: string, method = 'POST', body?: BodyInit) => {
    if (!csrf) throw new Error('Session is still connecting')
    const response = await fetch(url, { method, headers: body instanceof FormData ? { 'X-CSRF-Token': csrf } : headers, body })
    return jsonResponse(response)
  }

  const create = async () => {
    clearSectionError('intake')
    if (!title.trim() || !lyrics.trim() || !song) return setSectionError('intake', 'Title, song file and lyrics are required.')
    setBusy(true)
    try {
      const form = new FormData()
      form.set('title', title.trim()); form.set('lyrics', lyrics.trim()); form.set('song', song)
      referenceFiles.forEach(file => form.append('reference_files', file))
      form.set('concept', concept.trim()); form.set('participation_mode', participation); form.set('continuity_mode', continuity)
      form.set('generation_turbo_profile', generationTurboProfile)
      form.set('generation_steps', String(generationSteps))
      form.set('generation_megapixels', '0.7')
      form.set('generation_aspect_ratio', generationAspectRatio)
      form.set('generation_megapixel_rules_json', JSON.stringify(generationMegapixelRules))
      form.set('codex_runtime', 'codex')
      form.set('codex_model', codexModel); form.set('codex_effort', codexEffort)
      form.set('agy_runtime', agyRuntime)
      form.set('agy_model', agyModel); form.set('agy_effort', agyEffort)
      form.set('skills_json', JSON.stringify(selectedSkills)); form.set('approval_gates_json', JSON.stringify(participation === 'interactive' ? defaultGates : ['final']))
      const created = await mutate('/api/productions', 'POST', form)
      setProductions(current => [created, ...current]); setSelectedId(created.id); setProduction(created); setNewProject(false)
      setTitle(''); setLyrics(''); setConcept(''); setSong(null); setReferenceFiles([])
      setGenerationTurboProfile('v1'); setGenerationSteps(4); setGenerationAspectRatio('16:9'); setGenerationMegapixelRules(copyMegapixelRules())
      feedback.notify('success', `Production “${created.title}” created`)
    } catch (reason) { setSectionError('intake', reason instanceof Error ? reason.message : 'Unable to create production') }
    finally { setBusy(false) }
  }

  const control = async (action: 'start' | 'pause' | 'resume' | 'stop') => {
    if (!production) return
    setBusy(true); clearSectionError('controls')
    try {
      const body = action === 'stop' ? JSON.stringify({ cancel_generation: true }) : undefined
      const updated = await mutate(`/api/productions/${production.id}/${action}`, 'POST', body)
      setProduction(updated)
      feedback.notify('success', `Production ${action === 'stop' ? 'stopped' : action === 'start' ? 'started' : action === 'pause' ? 'paused' : 'resumed'}`)
    } catch (reason) { setSectionError('controls', reason instanceof Error ? reason.message : 'Control failed') }
    finally { setBusy(false) }
  }

  const retryReferenceGeneration = async () => {
    if (!production) return
    if (!await appModal.askConfirm({
      title: 'Retry reference generation',
      message: 'Retry only the unfinished reference handoff from the saved checkpoint? Existing approved references and numbered attempts will be preserved.',
      confirmLabel: 'Retry references',
    })) return
    setBusy(true); clearSectionError('references')
    try {
      setProduction(await mutate(`/api/productions/${production.id}/references/retry`, 'POST'))
      feedback.notify('success', 'Reference retry queued')
    } catch (reason) { setSectionError('references', reason instanceof Error ? reason.message : 'Reference retry failed') }
    finally { setBusy(false) }
  }

  const sendIntervention = async () => {
    if (!production || !intervention.trim()) return
    setBusy(true)
    try {
      const data = await mutate(`/api/productions/${production.id}/interventions`, 'POST', JSON.stringify({ content: intervention.trim(), recipient }))
      setProduction(data.production); setIntervention(''); feedback.notify('success', 'Intervention sent to the selected agent session')
    } catch (reason) { setSectionError('chat', reason instanceof Error ? reason.message : 'Message failed') }
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
      feedback.notify('success', action === 'approve' ? 'Decision approved' : 'Revision request sent')
    } catch (reason) { setSectionError('shots', reason instanceof Error ? reason.message : 'Decision failed') }
    finally { setBusy(false) }
  }

  const saveSettings = async () => {
    setBusy(true)
    try {
      const updated = await mutate('/api/settings/agents', 'PATCH', JSON.stringify(settings))
      setSettings(updated)
      feedback.notify('success', 'Agent defaults saved')
    } catch (reason) { setSectionError('settings', reason instanceof Error ? reason.message : 'Settings failed') }
    finally { setBusy(false) }
  }

  const toggleSkill = async (skill: Skill) => {
    try {
      const updated = await mutate(`/api/skills/${skill.id}`, 'PATCH', JSON.stringify({ enabled: !skill.enabled }))
      setSkills(current => current.map(item => item.id === updated.id ? updated : item))
      feedback.notify('success', `${skill.name} ${updated.enabled ? 'enabled' : 'disabled'}`)
    } catch (reason) { setSectionError('skills', reason instanceof Error ? reason.message : 'Skill update failed') }
  }

  const registerSkillFolder = async () => {
    if (!registerPath.trim()) return
    try {
      const added = await mutate('/api/skills/register', 'POST', JSON.stringify({ path: registerPath.trim() }))
      setSkills(current => [...current.filter(item => item.id !== added.id), added]); setRegisterPath('')
      feedback.notify('success', `Skill “${added.name}” registered`)
    } catch (reason) { setSectionError('skills', reason instanceof Error ? reason.message : 'Skill registration failed') }
  }

  const uploadSkill = async (file: File | null) => {
    if (!file) return
    const form = new FormData(); form.set('package', file)
    try {
      const added = await mutate('/api/skills/upload', 'POST', form)
      setSkills(current => [...current.filter(item => item.id !== added.id), added])
      feedback.notify('success', `Skill “${added.name}” uploaded`)
    } catch (reason) { setSectionError('skills', reason instanceof Error ? reason.message : 'Skill upload failed') }
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
      feedback.notify('success', mode === 'complete' ? `Skill “${skill.name}” and its files deleted` : `Skill “${skill.name}” unregistered`)
    } catch (reason) { setSectionError('skills', reason instanceof Error ? reason.message : 'Skill removal failed') }
  }

  const uploadReference = async (file: File | null) => {
    if (!file || !production) return
    const form = new FormData(); form.set('media', file)
    setBusy(true)
    try { await mutate(`/api/productions/${production.id}/references`, 'POST', form); await loadProduction(); feedback.notify('success', 'Reference uploaded') }
    catch (reason) { setSectionError('references', reason instanceof Error ? reason.message : 'Reference upload failed') }
    finally { setBusy(false) }
  }

  const generateReference = async () => {
    if (!production || !referenceName.trim() || !referencePrompt.trim()) return
    setReferenceGenerating(true); clearSectionError('references')
    try {
      const data = await mutate(
        `/api/productions/${production.id}/references/generate`, 'POST',
        JSON.stringify({ name: referenceName.trim(), prompt: referencePrompt.trim(), provider: referenceProvider }),
      )
      setProduction(data.production); setReferenceName(''); setReferencePrompt(''); feedback.notify('success', 'Reference generated and queued for review')
    } catch (reason) { setSectionError('references', reason instanceof Error ? reason.message : 'Reference generation failed') }
    finally { setReferenceGenerating(false) }
  }

  const removeReference = async (reference: ReferenceMedia) => {
    if (!production || !await appModal.askConfirm({
      title: 'מחיקת רפרנס',
      message: `למחוק את הרפרנס „${reference.name}”?`,
      confirmLabel: 'מחיקה',
      danger: true,
    })) return
    try { await mutate(`/api/productions/${production.id}/references/${reference.id}`, 'DELETE'); await loadProduction(); feedback.notify('success', `Reference “${reference.name}” deleted`) }
    catch (reason) { setSectionError('references', reason instanceof Error ? reason.message : 'Reference removal failed') }
  }

  const openShotEditor = (shot: Shot) => {
    setReturnToShotPlan(showShotPlan)
    setShowShotPlan(false)
    setEditingShot({
      ...shot,
      engine: shot.engine || 'turbo',
      steps: shot.steps || 4,
      turbo_profile: shot.turbo_profile || 'v1',
      audio_mode: shot.audio_mode || 'silent',
      audio_source: shot.audio_source || 'song',
      audio_start: shot.audio_start || 0,
      audio_duration: shot.audio_duration || shot.duration,
      reference_ids: [...shot.reference_ids],
    })
  }

  const setEditingTurboProfile = (profile: 'v1' | 'v4') => {
    setEditingShot(current => {
      if (!current) return current
      const maxSteps = profile === 'v4' ? 8 : 12
      const currentSteps = Number(current.steps) || 4
      return { ...current, turbo_profile: profile, steps: Math.min(maxSteps, Math.max(4, currentSteps)) }
    })
  }

  const setEditingSteps = (value: string) => {
    setEditingShot(current => {
      if (!current) return current
      const maxSteps = current.turbo_profile === 'v4' ? 8 : 12
      const parsed = Number.parseInt(value || '4', 10)
      return { ...current, steps: Math.min(maxSteps, Math.max(4, Number.isFinite(parsed) ? parsed : 4)) }
    })
  }

  const closeShotEditor = () => {
    const reopenShotPlan = returnToShotPlan
    setEditingShot(null)
    setReturnToShotPlan(false)
    clearSectionError('shotModal')
    if (reopenShotPlan) setShowShotPlan(true)
  }

  const saveShot = async () => {
    if (!production || !editingShot) return
    clearSectionError('shotModal')
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
      const reopenShotPlan = returnToShotPlan
      setProduction(updated); setEditingShot(null); setReturnToShotPlan(false)
      if (reopenShotPlan) setShowShotPlan(true)
      feedback.notify('success', `Shot ${editingShot.shot_index} saved`)
    } catch (reason) { setSectionError('shotModal', reason instanceof Error ? reason.message : 'Shot update failed') }
    finally { setBusy(false) }
  }

  const retryShot = async (shot: Shot) => {
    if (!production || !await appModal.askConfirm({
      title: 'יצירת ניסיון חדש',
      message: `להכניס לתור ניסיון חדש עבור השוט „${shot.title}”?`,
      confirmLabel: 'הכנס לתור',
    })) return
    setBusy(true)
    try { setProduction(await mutate(`/api/productions/${production.id}/shots/${shot.id}/retry`, 'POST', JSON.stringify({ regenerate_downstream: true }))); feedback.notify('success', `Shot ${shot.shot_index} retry queued`) }
    catch (reason) { setSectionError('shots', reason instanceof Error ? reason.message : 'Retry failed') }
    finally { setBusy(false) }
  }

  const saveProductionConfig = async () => {
    if (!production || !configDraft) return
    setBusy(true)
    try {
      const updated = await mutate(`/api/productions/${production.id}/settings`, 'PATCH', JSON.stringify({
        participation_mode: configDraft.participation_mode, continuity_mode: configDraft.continuity_mode,
        generation_turbo_profile: configDraft.generation_turbo_profile,
        generation_steps: Number(configDraft.generation_steps),
        generation_megapixels: Number(Number(configDraft.generation_megapixels || 0.7).toFixed(1)),
        generation_aspect_ratio: configDraft.generation_aspect_ratio || '16:9',
        generation_megapixel_rules: copyMegapixelRules(configDraft.generation_megapixel_rules),
        codex_runtime: 'codex', codex_model: configDraft.codex_model,
        codex_effort: configDraft.codex_effort, agy_runtime: 'agy', agy_model: configDraft.agy_model,
        agy_effort: configDraft.agy_effort, skills: configDraft.skills,
        reason: 'Updated from Production Room',
      }))
      setProduction(updated); setConfigOpen(false); feedback.notify('success', 'Production configuration saved as a revision')
    } catch (reason) { setSectionError('config', reason instanceof Error ? reason.message : 'Production settings failed') }
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
      feedback.notify('success', action === 'duplicate' ? 'Production duplicated' : action === 'archive' ? (production.archived ? 'Production unarchived' : 'Production archived') : 'Production deleted')
    } catch (reason) { setSectionError('library', reason instanceof Error ? reason.message : `${action} failed`) }
    finally { setBusy(false) }
  }

  const importJobs = async () => {
    if (!production) return
    const ids = importIds.split(/[\s,]+/).map(value => value.trim()).filter(Boolean)
    if (!ids.length) return
    setBusy(true)
    try { setProduction(await mutate(`/api/productions/${production.id}/imports/jobs`, 'POST', JSON.stringify({ job_ids: ids }))); setImportIds(''); feedback.notify('success', `${ids.length} completed job${ids.length === 1 ? '' : 's'} imported`) }
    catch (reason) { setSectionError('library', reason instanceof Error ? reason.message : 'Import failed') }
    finally { setBusy(false) }
  }

  const active = production && ['queued', 'running', 'pausing', 'retrying', 'stopping'].includes(production.status)
  const controllerMissing = !!production && ['running', 'pausing', 'retrying', 'stopping'].includes(production.status) && production.controller_active === false
  const generationProgress = production?.generation_progress
  const generationIsActive = !!generationProgress && ['queued', 'starting', 'running', 'verifying'].includes(generationProgress.status)
  const referenceRetryable = production && production.stage === 'reference_generation'
    && ['awaiting_user', 'failed', 'paused', 'stopped'].includes(production.status)
  const cleanMessages = production?.messages?.filter(message => !isBenignTrace(message) && !isNonMeaningfulTrace(message)) || []
  const agentActivity = production?.agent_activity
  const agentActivityText = agentActivity
    ? `${(agentActivity.participant || agentActivity.runtime || 'agent').toUpperCase()} CLI is ${agentActivity.state || 'working'} · elapsed ${Math.round(agentActivity.elapsed_seconds)}s · quiet ${Math.round(agentActivity.idle_seconds)}s${agentActivity.last_event ? ` · last real event: ${agentActivity.last_event}` : ''}`
    : ''
  const generationProgressText = generationProgress
    ? `${generationProgress.shot_title || 'Current shot'} · ${(generationProgress.phase || generationProgress.status).replaceAll('_', ' ')} · ${generationProgress.step > 0 && generationProgress.total_steps > 0 ? `step ${generationProgress.step}/${generationProgress.total_steps}` : `${Math.round(generationProgress.progress * 100)}%`}${generationProgress.eta_seconds ? ` · ETA ${Math.max(1, Math.round(generationProgress.eta_seconds))}s` : ''}`
    : ''
  const conversationMessages = cleanMessages.filter(message => message.kind !== 'agent_trace' || showLivePrints)
  const pendingDecisions = production?.decisions?.filter(item => item.status === 'pending') || []
  const finalVideo = [...(production?.artifacts || [])].reverse().find(item => item.kind === 'final_video')
  const selectedProductionReady = !!production && production.id === selectedId
  const showProductionLoading = !newProject && !selectedProductionReady && (productionsLoading || productionLoading || (!!selectedId && !productionLoadError))
  const showProductionError = !newProject && !!selectedId && !selectedProductionReady && !productionsLoading && !productionLoading && !!productionLoadError

  const toggleLivePrints = () => {
    setShowLivePrints(current => {
      const next = !current
      try { window.localStorage.setItem('production-show-live-prints', String(next)) } catch { /* optional preference */ }
      return next
    })
  }

  if (view === 'settings') return <section className="ps-root">
    <header className="ps-page-head"><button className="ps-icon" onClick={() => setView('room')}><ChevronLeft size={19} /></button><div><span>Production Studio</span><h2>Agent & skill settings</h2></div><button className="ps-icon" onClick={() => void refreshModels()} disabled={modelsRefreshing}><RefreshCw className={modelsRefreshing ? 'spin' : ''} size={18} /></button></header>
    <SectionError message={sectionErrors.settings} onDismiss={() => clearSectionError('settings')} />
    <div className="ps-settings-grid">
      <section className="ps-panel"><div className="ps-panel-title"><Bot size={18} /><div><h3>Agent defaults</h3><p>Used by new productions. Active projects keep their frozen configuration.</p></div></div>
        <div className="ps-agent-grid">
          <AgentSelect label="CODEX" catalogs={models} runtime={settings.codex_runtime} model={settings.codex_model} effort={settings.codex_effort} onRuntime={value => setSettings(current => ({ ...current, codex_runtime: value }))} onModel={value => setSettings(current => ({ ...current, codex_model: value }))} onEffort={value => setSettings(current => ({ ...current, codex_effort: value }))} />
          <AgentSelect label="AGY" catalogs={models} runtime="agy" model={settings.agy_model} effort={settings.agy_effort} runtimeLocked onRuntime={() => {}} onModel={value => setSettings(current => ({ ...current, agy_model: value }))} onEffort={value => setSettings(current => ({ ...current, agy_effort: value }))} />
        </div><div className="ps-model-status"><span>{agentCatalogLoading ? 'Loading agent catalogs…' : `Models queried from the installed CLIs${modelsFetchedAt ? ` · ${modelsFetchedAt}` : ''}`}</span><button className="ps-secondary" onClick={() => void refreshModels()} disabled={modelsRefreshing}>{modelsRefreshing ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />} Refresh models</button></div><button className="ps-primary" onClick={() => void saveSettings()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <Check size={17} />} Save defaults</button>
      </section>
      <section className="ps-panel ps-skills-panel"><div className="ps-panel-title"><Sparkles size={18} /><div><h3>Production skills</h3><p>Enabled skills become available to new productions.</p></div></div>
        <SectionError message={sectionErrors.skills} className="ps-section-error" onDismiss={() => clearSectionError('skills')} />
        <div className="ps-add-skill"><input value={registerPath} onChange={event => setRegisterPath(event.target.value)} placeholder="Existing skill folder path" /><button onClick={() => void registerSkillFolder()}><FolderPlus size={16} /> Register</button><label><FileArchive size={16} /> Upload ZIP<input type="file" accept=".zip,application/zip" onChange={event => { void uploadSkill(event.target.files?.[0] || null); event.currentTarget.value = '' }} /></label></div>
        <div className="ps-skill-list">{skills.map(skill => <article key={skill.id} className={`ps-skill ${!skill.valid ? 'invalid' : ''}`}>
          <label className="ps-switch"><input type="checkbox" checked={skill.enabled} disabled={!skill.valid} onChange={() => void toggleSkill(skill)} /><span /></label>
          <div><h4>{skill.name}</h4><p>{skill.error || skill.description || 'No description'}</p><small>{skill.source} · {skill.agents.join(' + ')}</small></div>
          <div className="ps-skill-actions"><button onClick={() => void deleteSkill(skill, 'unregister')}>Unregister</button>{skill.managed && <button className="danger" onClick={() => void deleteSkill(skill, 'complete')}><Trash2 size={14} /> Delete files</button>}</div>
        </article>)}</div>
      </section>
    </div>
    <FeedbackToast feedback={feedback.feedback} onDismiss={feedback.dismiss} />
    <AppModal modal={appModal.modal} value={appModal.value} onValueChange={appModal.setValue} onResolve={appModal.resolveModal} />
  </section>

  return <section className="ps-root">
    <header className="ps-page-head"><div className="ps-brand"><Sparkles size={20} /></div><div><span>Codex + AGY + You</span><h2>Production Room</h2></div><button className="ps-icon" onClick={() => setView('settings')} aria-label="Production settings"><Settings size={19} /></button></header>
    <SectionError message={sectionErrors.system} className="ps-section-error" onDismiss={() => clearSectionError('system')} />
    <div className="ps-project-bar"><select value={selectedId} onChange={event => { setSelectedId(event.target.value); setNewProject(false) }}><option value="">Select a production</option>{productions.map(item => <option key={item.id} value={item.id}>{item.archived ? '[Archived] ' : ''}{item.title} · {item.status}</option>)}</select><button className="ps-new" onClick={() => setNewProject(true)}>+ New production</button></div>

    {showProductionLoading ? <section className="ps-panel ps-loading-panel" role="status" aria-live="polite"><LoaderCircle className="spin" size={25} /><div><h3>Loading production</h3><p>The production room is loading independently. Other app sections remain available while the selected production data arrives.</p></div></section> : showProductionError ? <section className="ps-panel ps-loading-panel ps-loading-error" role="alert"><X size={25} /><div><h3>Production could not be loaded</h3><p>{productionLoadError}</p><button className="ps-secondary" onClick={() => void loadProduction(selectedId)}>Retry production</button></div></section> : (newProject || !production) ? <section className="ps-create ps-panel">
      <SectionError message={sectionErrors.intake} className="ps-section-error" onDismiss={() => clearSectionError('intake')} />
      <div className="ps-panel-title"><Clapperboard size={20} /><div><h3>New music-video production</h3><p>The pipeline is music-video only for this POC.</p></div></div>
      <div className="ps-form-grid"><label><span>Project title</span><input value={title} onChange={event => setTitle(event.target.value)} placeholder="Belly of the Beast" /></label><label><span>Song file</span><input type="file" accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg" onChange={event => setSong(event.target.files?.[0] || null)} /></label></div>
      <label><span>Lyrics</span><textarea value={lyrics} onChange={event => setLyrics(event.target.value)} placeholder="Paste the complete lyrics…" /></label>
      <label><span>Creative direction (optional)</span><textarea value={concept} onChange={event => setConcept(event.target.value)} placeholder="Characters, locations, visual style, story ideas, constraints…" /></label>
      <label className="ps-reference-upload ps-intake-references"><Upload size={16} /><span>Optional source references · characters, locations, props, video or audio</span><input type="file" multiple accept="image/*,video/*,audio/*" onChange={event => { setReferenceFiles(Array.from(event.target.files || [])); event.currentTarget.value = '' }} /></label>
      {!!referenceFiles.length && <div className="ps-intake-file-list">{referenceFiles.map(file => <span key={`${file.name}-${file.size}`}>{file.name}</span>)}</div>}
      <p className="ps-form-note">References are optional and can be partial. Codex and AGY will use the files you provide, then create only the missing visual references.</p>
      <div className="ps-choice-row"><div><span>Production mode</span><div className="ps-segment"><button className={participation === 'autonomous' ? 'active' : ''} onClick={() => setParticipation('autonomous')}>Autonomous</button><button className={participation === 'interactive' ? 'active' : ''} onClick={() => setParticipation('interactive')}>Interactive</button></div></div><label><span>Continuity</span><select value={continuity} onChange={event => setContinuity(event.target.value)}><option value="hybrid">Hybrid</option><option value="sequential">Sequential</option><option value="hard_cut">Hard cuts</option><option value="segmented">Segmented</option></select></label></div>
       <div className="ps-generation-defaults">
         <div className="ps-field-title"><Gauge size={15} /><span>Generation defaults</span></div>
         <p>Choose the generation policy before planning. Each shot receives the MP rule for its duration; the workflow calculates final dimensions from MP and the selected resolution shape.</p>
         <div className="ps-form-grid">
           <label><span>Turbo profile</span><select value={generationTurboProfile} onChange={event => { const value = event.target.value as 'v1'|'v4'; setGenerationTurboProfile(value); if (value === 'v4' && generationSteps > 8) setGenerationSteps(8) }}><option value="v1">Turbo v1</option><option value="v4">Turbo v4</option></select></label>
           <label><span>Steps · whole number</span><input type="number" min="4" max={generationTurboProfile === 'v4' ? 8 : 12} step="1" value={generationSteps} onChange={event => setGenerationSteps(Math.min(generationTurboProfile === 'v4' ? 8 : 12, Math.max(4, Number.parseInt(event.target.value || '4', 10) || 4)))} /></label>
           <label><span>Resolution shape</span><select value={generationAspectRatio} onChange={event => setGenerationAspectRatio(event.target.value)}>{resolutionOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
         </div>
         <MegapixelRulesEditor rules={generationMegapixelRules} onChange={setGenerationMegapixelRules} />
         <small>Turbo v4 supports 4–8 steps. MP remains the requested value; it is not replaced by the rounded pixel product shown after dimension calculation.</small>
       </div>
      <details className="ps-advanced-settings"><summary>Advanced settings (optional)</summary>
      <div className="ps-agent-grid"><AgentSelect label="CODEX" catalogs={models} runtime={codexRuntime} model={codexModel} effort={codexEffort} onRuntime={setCodexRuntime} onModel={setCodexModel} onEffort={setCodexEffort} /><AgentSelect label="AGY" catalogs={models} runtime="agy" model={agyModel} effort={agyEffort} runtimeLocked onRuntime={() => {}} onModel={setAgyModel} onEffort={setAgyEffort} /></div>
      <div className="ps-project-skills"><div className="ps-field-title"><Sparkles size={15} /><span>Enabled skills</span></div><div>{skills.filter(item => item.valid && item.enabled).map(skill => <label key={skill.id}><input type="checkbox" checked={selectedSkills.includes(skill.id)} onChange={() => setSelectedSkills(current => current.includes(skill.id) ? current.filter(id => id !== skill.id) : [...current, skill.id])} />{skill.name}</label>)}</div></div>
      </details>
      <div className="ps-create-actions">{newProject && production && <button className="ps-secondary" onClick={() => setNewProject(false)}>Cancel</button>}<button className="ps-primary" onClick={() => void create()} disabled={busy}>{busy ? <LoaderCircle className="spin" size={18} /> : <Sparkles size={18} />} Create production</button></div>
    </section> : <>
      <section className="ps-production-head ps-panel"><div><span className={`ps-status ${production.status}`}>{production.status}</span><h3>{production.title}</h3><p>{production.stage.replaceAll('_', ' ')} · {production.participation_mode} · {production.continuity_mode} · Turbo {(production.generation_turbo_profile || 'v1').toUpperCase()} · {production.generation_steps || 4} steps · {production.generation_aspect_ratio || '16:9'} · MP by duration</p></div><div className="ps-controls">
        {['draft', 'stopped', 'failed'].includes(production.status) && !referenceRetryable && <button className="primary" onClick={() => void control('start')} disabled={busy}><Play size={17} /> Start</button>}
        {referenceRetryable && <button className="primary" onClick={() => void retryReferenceGeneration()} disabled={busy}><RotateCcw size={17} /> Retry references</button>}
        {production.status === 'paused' && <button className="primary" onClick={() => void control('resume')} disabled={busy}><Play size={17} /> Resume</button>}
        {active && <button onClick={() => void control('pause')} disabled={busy || production.status === 'pausing'}><Pause size={17} /> Pause</button>}
        {!['stopped', 'completed'].includes(production.status) && <button className="danger" onClick={() => void control('stop')} disabled={busy}><Square size={15} /> Stop</button>}
        <button onClick={() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })}><MessageSquare size={15} /> Intervene</button>
        <details className="ps-head-more"><summary>More</summary><div>
         <button onClick={() => { setConfigDraft({ ...production, generation_turbo_profile: production.generation_turbo_profile || 'v1', generation_steps: production.generation_steps || 4, generation_megapixels: production.generation_megapixels || 0.7, generation_aspect_ratio: production.generation_aspect_ratio || '16:9', generation_megapixel_rules: copyMegapixelRules(production.generation_megapixel_rules) }); setConfigOpen(true) }} disabled={busy || !!active}><Settings size={15} /> Configure</button>
        <button onClick={() => void lifecycle('duplicate')} disabled={busy}><Copy size={15} /> Duplicate</button>
        <button onClick={() => void lifecycle('archive')} disabled={busy || !!active}><Archive size={15} /> {production.archived ? 'Unarchive' : 'Archive'}</button>
        <a className="ps-control-link" href={`/api/productions/${production.id}/export`}><Download size={15} /> Export</a>
        <button className="danger" onClick={() => void lifecycle('delete')} disabled={busy || !!active}><Trash2 size={15} /> Delete</button>
        </div></details>
      </div><div className="ps-stage-progress"><span style={{ width: `${Math.round((production.progress || 0) * 100)}%` }} /></div></section>
      <SectionError message={sectionErrors.controls} className="ps-section-error" onDismiss={() => clearSectionError('controls')} />
      <SectionError message={sectionErrors.config} className="ps-section-error" onDismiss={() => clearSectionError('config')} />
      <SectionError message={sectionErrors.references} className="ps-section-error" onDismiss={() => clearSectionError('references')} />

      {configOpen && configDraft && <section className="ps-panel ps-project-config"><div className="ps-panel-title"><Settings size={18} /><div><h3>Production configuration</h3><p>Available while the production is not running. Saving creates a revision.</p></div></div><div className="ps-choice-row"><label><span>Mode</span><select value={configDraft.participation_mode} onChange={event => setConfigDraft(current => current && ({ ...current, participation_mode: event.target.value }))}><option value="autonomous">Autonomous</option><option value="interactive">Interactive</option></select></label><label><span>Continuity</span><select value={configDraft.continuity_mode} onChange={event => setConfigDraft(current => current && ({ ...current, continuity_mode: event.target.value }))}><option value="hybrid">Hybrid</option><option value="sequential">Sequential</option><option value="hard_cut">Hard cuts</option><option value="segmented">Segmented</option></select></label></div><div className="ps-generation-defaults ps-config-generation"><div className="ps-field-title"><Gauge size={15} /><span>Generation defaults</span></div><p>These settings are used when the next shot plan is created. Final dimensions are calculated by the workflow.</p><div className="ps-form-grid"><label><span>Turbo profile</span><select value={configDraft.generation_turbo_profile || 'v1'} onChange={event => setConfigDraft(current => current && ({ ...current, generation_turbo_profile: event.target.value, generation_steps: event.target.value === 'v4' ? Math.min(8, current.generation_steps || 4) : (current.generation_steps || 4) }))}><option value="v1">Turbo v1</option><option value="v4">Turbo v4</option></select></label><label><span>Steps · whole number</span><input type="number" min="4" max={configDraft.generation_turbo_profile === 'v4' ? 8 : 12} step="1" value={configDraft.generation_steps || 4} onChange={event => setConfigDraft(current => current && ({ ...current, generation_steps: Math.min((current.generation_turbo_profile || 'v1') === 'v4' ? 8 : 12, Math.max(4, Number.parseInt(event.target.value || '4', 10) || 4)) }))} /></label><label><span>Resolution shape</span><select value={configDraft.generation_aspect_ratio || '16:9'} onChange={event => setConfigDraft(current => current && ({ ...current, generation_aspect_ratio: event.target.value }))}>{resolutionOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label></div><MegapixelRulesEditor rules={configDraft.generation_megapixel_rules} onChange={rules => setConfigDraft(current => current && ({ ...current, generation_megapixel_rules: rules }))} /><small>Turbo v4 supports 4–8 steps. Each shot uses the first MP rule covering its duration.</small></div><div className="ps-agent-grid"><AgentSelect label="CODEX" catalogs={models} runtime={configDraft.codex_runtime} model={configDraft.codex_model} effort={configDraft.codex_effort} onRuntime={value => { const first=models[value][0]; setConfigDraft(current => current && ({...current,codex_runtime:value,codex_model:first?.id || '',codex_effort:first?.efforts[0] || 'medium'})) }} onModel={value => setConfigDraft(current => current && ({...current,codex_model:value}))} onEffort={value => setConfigDraft(current => current && ({...current,codex_effort:value}))} /><AgentSelect label="AGY" catalogs={models} runtime="agy" model={configDraft.agy_model} effort={configDraft.agy_effort} onRuntime={value => setConfigDraft(current => current && ({...current,agy_runtime:value}))} onModel={value => setConfigDraft(current => current && ({...current,agy_model:value}))} onEffort={value => setConfigDraft(current => current && ({...current,agy_effort:value}))} /></div><div className="ps-project-skills"><div className="ps-field-title"><Sparkles size={15}/><span>Skills used by this production</span></div><div>{skills.filter(item => item.valid && item.enabled).map(skill => <label key={skill.id}><input type="checkbox" checked={configDraft.skills.includes(skill.id)} onChange={() => setConfigDraft(current => current && ({...current,skills:current.skills.includes(skill.id)?current.skills.filter(id=>id!==skill.id):[...current.skills,skill.id]}))}/>{skill.name}</label>)}</div></div><div className="ps-create-actions"><button className="ps-secondary" onClick={() => setConfigOpen(false)}>Cancel</button><button className="ps-primary" onClick={() => void saveProductionConfig()}>Save revision</button></div></section>}

      <details className="ps-panel ps-reference-manager"><summary className="ps-panel-title"><Upload size={18} /><div><h3>Reference media</h3><p>Images, videos, and audio can be assigned to current T2V/I2V production shots. R2V remains available elsewhere in the app for future production support. Generated stills are jointly reviewed by Codex and AGY.</p></div></summary><div className="ps-reference-generator"><div className="ps-field-title"><ImagePlus size={16}/><span>Generate reference image</span></div><div className="ps-form-grid"><label><span>Reference name</span><input value={referenceName} onChange={event => setReferenceName(event.target.value)} placeholder="Main character · night wardrobe"/></label><label><span>Image provider</span><select value={referenceProvider} onChange={event => setReferenceProvider(event.target.value as 'auto'|'codex'|'agy')}><option value="auto">Auto · Codex then AGY fallback</option><option value="codex">Codex ImageGen</option><option value="agy">AGY ImageGen</option></select></label></div><label><span>Complete image brief</span><textarea value={referencePrompt} onChange={event => setReferencePrompt(event.target.value)} placeholder="Describe identity, wardrobe, location, lighting, camera and composition…"/></label><button className="ps-primary" onClick={() => void generateReference()} disabled={referenceGenerating || !!active || !referenceName.trim() || !referencePrompt.trim()}>{referenceGenerating ? <LoaderCircle className="spin" size={16}/> : <ImagePlus size={16}/>} {referenceGenerating ? 'Generating and reviewing…' : 'Generate reference image'}</button>{active && <small>Pause or stop this production to generate a manual reference.</small>}</div><label className="ps-reference-upload"><Upload size={16} /> Add image, video, or audio<input type="file" accept="image/*,video/*,audio/*" onChange={event => { void uploadReference(event.target.files?.[0] || null); event.currentTarget.value='' }} /></label><div className="ps-reference-list">{production.references?.map(reference => <article key={reference.id}>{reference.kind === 'image' && <img className="ps-reference-thumb" src={reference.url} alt={reference.name} loading="lazy" />}<a href={reference.url} target="_blank" rel="noreferrer"><b>{reference.kind}</b><span>{reference.name}</span></a><button onClick={() => void removeReference(reference)}><Trash2 size={13} /></button></article>)}{!production.references?.length && <p>No reference media uploaded yet.</p>}</div><div className="ps-import-jobs"><span>Import completed generations</span>{jobsLoading ? <small className="ps-inline-loading"><LoaderCircle className="spin" size={13} /> Loading completed generations…</small> : <>{regularJobs.slice(0, 20).map(job => <label key={job.id}><input type="checkbox" checked={importIds.split(',').filter(Boolean).includes(job.id)} onChange={() => { const current=importIds.split(',').filter(Boolean); setImportIds(current.includes(job.id)?current.filter(id=>id!==job.id).join(','):[...current,job.id].join(',')) }}/><b>{job.duration}s · {job.mode}</b><small>{job.prompt}</small></label>)}{!regularJobs.length && <small>No completed regular jobs are available.</small>}</>}<button onClick={() => void importJobs()} disabled={!importIds}>Import selected results</button></div></details>

      <SectionError message={sectionErrors.library} className="ps-section-error" onDismiss={() => clearSectionError('library')} />
      <div className="ps-workspace">
        <div className="ps-left-rail">
        <SectionError message={sectionErrors.shots} className="ps-section-error" onDismiss={() => clearSectionError('shots')} />
        <aside className="ps-panel ps-timeline"><div className="ps-panel-title"><Clapperboard size={17} /><div><h3>Storyboard</h3><p>Shot plan · persistent checkpoint</p></div></div>{!!production.shots?.length && <div className="ps-shot-plan-toolbar"><button type="button" className="ps-shot-plan-button" onClick={() => setShowShotPlan(true)}><Clapperboard size={14} /> View shots ({production.shots.length})</button></div>}{['intake','song_analysis','treatment','references','prompts','generation','review','assembly','final'].map((stage, index) => <div key={stage} className={production.stage.includes(stage) ? 'current' : index / 9 < production.progress ? 'done' : ''}><i>{index / 9 < production.progress ? <Check size={12} /> : index + 1}</i><span>{stage}</span></div>)}
        </aside>
        <aside className="ps-panel ps-decisions"><div className="ps-panel-title"><ShieldCheck size={18} /><div><h3>Shot review</h3><p>{pendingDecisions.length} pending decisions</p></div></div>{!pendingDecisions.length && <div className="ps-empty"><ShieldCheck size={24} /><p>No pending decisions.</p></div>}{pendingDecisions.map(decision => <article className="ps-decision" key={decision.id}><span>{decision.stage.replaceAll('_', ' ')}</span><h4>{decision.title}</h4><p>{decision.summary}</p><div><button className="approve" onClick={() => void decide(decision, 'approve')}><Check size={15} /> Approve</button><button className="reject" onClick={() => void decide(decision, 'reject')}><X size={15} /> Reject / edit</button></div></article>)}</aside>
        </div>
          <main className="ps-panel ps-conversation">
            <div className="ps-panel-title">
              <MessageSquare size={18} />
              <div><h3>Production council</h3><p>User, Codex and AGY · live CLI activity is available here</p></div>
              <button type="button" className="ps-trace-toggle" aria-pressed={showLivePrints} onClick={toggleLivePrints}>{showLivePrints ? 'Hide live prints' : 'Show live prints'}</button>
            </div>
            {active && !controllerMissing && <div className={`ps-agent-activity ${generationIsActive ? 'generation' : production.status}`} role="status" aria-live="polite"><LoaderCircle className="spin" size={17} /><div><b>{generationIsActive ? 'GENERATION IN PROGRESS' : production.status === 'queued' ? 'PRODUCTION QUEUED' : agentActivity?.process_alive ? `${(agentActivity.participant || 'agent').toUpperCase()} WORKING IN BACKGROUND` : 'PRODUCTION CONTROLLER WORKING'}</b><span>{generationIsActive ? generationProgressText : production.status === 'queued' ? 'Waiting for the scheduler to resume from the saved checkpoint.' : agentActivity?.process_alive ? agentActivityText : `Controller is processing ${production.stage.replaceAll('_', ' ')}; no agent CLI process is currently running.`}</span></div><small>{generationIsActive && generationProgress?.shot_index ? `SHOT ${generationProgress.shot_index}` : production.stage.replaceAll('_', ' ')}</small></div>}
            {controllerMissing && <div className="ps-agent-activity paused" role="status" aria-live="polite"><LoaderCircle className="spin" size={17} /><div><b>CONTROLLER RECOVERY</b><span>No agent process is active for this production. The checkpoint is being preserved and the controller is recovering it; no new generation is running.</span></div><small>{production.stage.replaceAll('_', ' ')}</small></div>}
            <SectionError message={sectionErrors.chat} className="ps-section-error" onDismiss={() => clearSectionError('chat')} />
            <div className="ps-messages" ref={messagesRef}>{production.messages_has_older && <button type="button" className="ps-load-older" onClick={() => void loadOlderMessages()} disabled={olderMessagesLoading}>{olderMessagesLoading ? <><LoaderCircle className="spin" size={13} /> Loading older council messages…</> : `Load older council messages · ${Math.max(0, (production.message_total || 0) - (production.messages?.length || 0))} remaining`}</button>}{conversationMessages.map(message => {
              const trace = message.kind === 'agent_trace'
              const responseTrace = trace && message.metadata?.stream === 'response'
              const result = message.kind === 'agent' && (message.participant === 'agy' || message.participant === 'codex')
              const decision = typeof message.metadata?.decision === 'string' ? message.metadata.decision : ''
              const nextAction = typeof message.metadata?.next_action === 'string' ? message.metadata.next_action : ''
              const structuredContent = result ? extractStructuredAgentContent(message.content) : null
              const schemaEcho = result && isAgentSchemaEcho(message)
              const details = schemaEcho ? null : (message.metadata?.content ?? structuredContent)
              const issues = result ? concreteAgentIssues(message.metadata?.issues) : []
              const interventionState = message.kind === 'intervention' && typeof message.metadata?.execution_status === 'string' ? String(message.metadata.execution_status) : ''
              return <article key={message.id} className={`ps-message ${message.participant}${trace ? ' trace' : ''}${responseTrace ? ' response' : ''}${result ? ' result' : ''}`}><div className="ps-avatar"><ParticipantIcon participant={message.participant} /></div><div className="ps-message-card"><header><b>{message.participant === 'user' ? 'YOU' : message.participant.toUpperCase()}{trace && <em>{responseTrace ? 'REPLY' : 'LIVE'}</em>}</b><span>{new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span></header>{structuredContent ? <p>{agentVisibleSummary(message, structuredContent)}</p> : <p>{message.content}</p>}{interventionState && <small className="ps-trace-meta">Request {interventionState.replaceAll('_', ' ')}</small>}{message.metadata && typeof message.metadata.model === 'string' && <small>{message.metadata.model} · {String(message.metadata.effort || '')}</small>}{trace && message.metadata?.stream === 'response' && <small className="ps-trace-meta">Agent response</small>}{trace && message.metadata?.stream !== 'response' && message.metadata?.heartbeat !== true && <small className="ps-trace-meta">Live activity</small>}{schemaEcho && <p className="ps-agent-callout negative"><b>Provider response issue:</b> AGY echoed its output schema instead of returning the requested task result.</p>}{result && decision && !schemaEcho && <p className={'ps-agent-callout ' + agentDecisionTone(decision)}><b>Decision:</b> {decision}</p>}{result && nextAction && !schemaEcho && <p className={'ps-agent-callout ' + agentStatusTone('next_action', nextAction)}><b>Intent / next action:</b> {nextAction}</p>}{result && details !== undefined && details !== null && <details className="ps-agent-details"><summary>{message.participant === 'agy' ? 'Detailed analysis' : 'Structured plan details'}</summary><AgentReadableDetail value={details} /></details>}{result && issues.length > 0 && <details className="ps-agent-issues"><summary>{issues.length} issue{issues.length === 1 ? '' : 's'}</summary><AgentReadableDetail value={issues} /></details>}</div></article>
            })}</div>
          {finalVideo && <section className="ps-final-video"><div><Clapperboard size={18} /><b>Final music video</b></div><video controls playsInline preload="none" src={finalVideo.url} /><a href={finalVideo.url} download>Download final video</a></section>}
          <div className="ps-composer"><select value={recipient} onChange={event => setRecipient(event.target.value)}><option value="both">Both agents</option><option value="codex">Codex only</option><option value="agy">AGY only</option></select><textarea value={intervention} onChange={event => setIntervention(event.target.value)} placeholder="Guide Codex and AGY, correct a decision, or intervene…" /><button onClick={() => void sendIntervention()} disabled={busy || !intervention.trim()}><Send size={17} /></button></div>
         </main>
         <aside className="ps-panel ps-reference-panel"><div className="ps-panel-title"><ImagePlus size={18} /><div><h3>Session references</h3><p>{production.references?.length || 0} reference{production.references?.length === 1 ? '' : 's'} · generated and supplied for this production</p></div></div><div className="ps-session-reference-list">{production.references?.length ? production.references.map(reference => <SessionReferenceCard key={reference.id} reference={reference} onOpen={setPreviewReference} />) : <div className="ps-empty"><ImagePlus size={24} /><p>No references in this production yet.</p></div>}</div></aside>
      </div>
      {production.error && <SectionError message={production.error} className="ps-section-error" onDismiss={() => {}} />}
      {editingShot && <div className="ps-modal-backdrop"><section className="ps-panel ps-shot-editor"><SectionError message={sectionErrors.shotModal} className="ps-modal-error" onDismiss={() => clearSectionError('shotModal')} /><div className="ps-panel-title"><Pencil size={18}/><div><h3>Edit shot {editingShot.shot_index}</h3><p>Set the essentials below. Prompt and references are under Advanced.</p></div><button onClick={closeShotEditor}><X size={16}/></button></div><div className="ps-form-grid"><label><span>Title</span><input value={editingShot.title} onChange={event => setEditingShot(current => current && ({...current,title:event.target.value}))}/></label><label><span>Mode</span><select value={editingShot.mode} onChange={event => { const mode=event.target.value as Shot['mode']; setEditingShot(current => current && ({...current,mode,audio_mode:mode==='reference'?'silent':current.audio_mode})) }}><option value="text">T2V</option><option value="opening">I2V</option><option value="reference" disabled>R2V · future production support</option></select></label></div><details className="ps-advanced-settings"><summary>Prompt (optional)</summary><label><span>Complete prompt</span><textarea value={editingShot.prompt} onChange={event => setEditingShot(current => current && ({...current,prompt:event.target.value}))}/></label></details><div className="ps-form-grid"><label><span>Continuity</span><select value={editingShot.continuity} onChange={event => setEditingShot(current => current && ({...current,continuity:event.target.value as Shot['continuity']}))}><option value="hard_cut">Hard cut / independent</option><option value="sequential">Previous last frame</option></select></label><label><span>Aspect ratio</span><select value={editingShot.aspect_ratio} onChange={event => setEditingShot(current => current && ({...current,aspect_ratio:event.target.value}))}><option>16:9</option><option>9:16</option><option>1:1</option><option>4:3</option><option>3:4</option></select></label><label><span>Turbo LoRA / profile</span><select value={editingShot.turbo_profile || 'v1'} disabled={editingShot.engine !== 'turbo'} onChange={event => setEditingTurboProfile(event.target.value as 'v1' | 'v4')}><option value="v1">Turbo v1</option><option value="v4">Turbo v4</option></select></label><label><span>Steps · whole number</span><input type="number" min="4" max={(editingShot.turbo_profile || 'v1') === 'v4' ? 8 : 12} step="1" value={editingShot.steps || 4} onChange={event => setEditingSteps(event.target.value)}/></label><label><span>Duration seconds</span><input type="number" min="0.5" max="15" step="0.5" value={editingShot.duration} onChange={event => setEditingShot(current => current && ({...current,duration:Number(event.target.value),audio_duration:current.audio_duration || Number(event.target.value)}))}/></label><label><span>Megapixels</span><input type="number" min="0.1" max="2" step="0.05" value={editingShot.megapixels} onChange={event => setEditingShot(current => current && ({...current,megapixels:Number(event.target.value)}))}/></label></div><div className="ps-form-grid ps-shot-audio-controls"><label><span>Audio</span><select value={editingShot.audio_mode || 'silent'} onChange={event => setEditingShot(current => current && ({...current,audio_mode:event.target.value as Shot['audio_mode'],audio_source:event.target.value==='silent'?'song':current.audio_source}))}><option value="silent">Silent generation</option><option value="lip_sync" disabled={editingShot.mode === 'reference'}>Lip-sync · song or reference audio</option></select></label>{editingShot.audio_mode === 'lip_sync' && <label><span>Audio source</span><select value={editingShot.audio_source || 'song'} onChange={event => setEditingShot(current => current && ({...current,audio_source:event.target.value as Shot['audio_source']}))}><option value="song">Production song segment</option><option value="reference" disabled={!production.references?.some(reference => reference.kind === 'audio')}>Assigned audio reference</option></select></label>}</div>{editingShot.audio_mode === 'lip_sync' && <div className="ps-form-grid ps-shot-audio-timing"><label><span>Audio start (seconds)</span><input type="number" min="0" max="3600" step="0.1" value={editingShot.audio_start || 0} onChange={event => setEditingShot(current => current && ({...current,audio_start:Number(event.target.value)}))}/></label><label><span>Audio duration</span><input type="number" min="0.5" max="60" step="0.1" value={editingShot.audio_duration || editingShot.duration} onChange={event => setEditingShot(current => current && ({...current,audio_duration:Number(event.target.value)}))}/></label>{editingShot.audio_source === 'reference' && <label><span>Audio reference</span><select value={editingShot.audio_reference_id || ''} onChange={event => setEditingShot(current => current && ({...current,audio_reference_id:event.target.value || null}))}><option value="">Choose audio reference</option>{production.references?.filter(reference => reference.kind === 'audio').map(reference => <option key={reference.id} value={reference.id}>{reference.name}</option>)}</select></label>}</div>}<details className="ps-advanced-settings"><summary>Assigned references (optional)</summary><div className="ps-reference-checks"><span>Use assigned images as creative anchors for Codex and AGY to build this shot&apos;s opening scene. The generated scene frame is sent to I2V; original references are not sent directly. R2V is not used in production yet.</span><ShotReferenceAssignments shot={editingShot} references={production.references || []} onOpen={setPreviewReference}/>{production.references?.map(reference => <label key={reference.id}><input type="checkbox" checked={editingShot.reference_ids.includes(reference.id)} onChange={() => setEditingShot(current => current && ({...current,reference_ids:current.reference_ids.includes(reference.id)?current.reference_ids.filter(id=>id!==reference.id):[...current.reference_ids,reference.id]}))}/>{reference.kind}: {reference.name}</label>)}</div></details><div className="ps-create-actions"><button className="ps-secondary" onClick={closeShotEditor}>Cancel</button><button className="ps-primary" onClick={() => void saveShot()} disabled={busy}>Save shot</button></div></section></div>}
      {showShotPlan && production.shots?.length ? <ShotPlanModal shots={production.shots} references={production.references || []} active={!!active} autonomous={production.participation_mode === 'autonomous'} onClose={() => setShowShotPlan(false)} onEdit={openShotEditor} onRetry={shot => void retryShot(shot)} onOpenReference={setPreviewReference} /> : null}
      {previewReference && <div className="ps-modal-backdrop ps-reference-preview-backdrop" role="presentation" onClick={() => setPreviewReference(null)}><section className="ps-panel ps-reference-preview" role="dialog" aria-modal="true" aria-labelledby="reference-preview-title" onClick={event => event.stopPropagation()}><div className="ps-panel-title"><ImagePlus size={18}/><div><h3 id="reference-preview-title">{previewReference.name}</h3><p>{previewReference.kind.toUpperCase()} reference from this production</p></div><button type="button" aria-label="Close reference preview" onClick={() => setPreviewReference(null)}><X size={16}/></button></div><div className="ps-reference-preview-media">{previewReference.kind === 'image' && <img src={previewReference.url} alt={previewReference.name}/>} {previewReference.kind === 'video' && <video controls playsInline preload="metadata" src={previewReference.url}/>} {previewReference.kind === 'audio' && <audio controls src={previewReference.url}/>}</div><a className="ps-reference-preview-open" href={previewReference.url} target="_blank" rel="noreferrer">Open original file</a></section></div>}
    </>}
    <FeedbackToast feedback={feedback.feedback} onDismiss={feedback.dismiss} />
    <AppModal modal={appModal.modal} value={appModal.value} onValueChange={appModal.setValue} onResolve={appModal.resolveModal} />
  </section>
}
