import { useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Check, Download, Expand, Image as ImageIcon, ImagePlus, LoaderCircle, Pencil, RefreshCw, Sparkles, Trash2, X, ZoomIn } from 'lucide-react'

type Field = { node: string; key: string; subkey?: string; value: string | number | boolean; type: 'text' | 'number' | 'boolean'; label: string }
type LoraOption = { filename: string; enabled_by_default: boolean }
type Task = 'create' | 'edit' | 'expand' | 'upscale'
type InputRole = { label: string; help: string }
type Workflow = { name: string; label: string; title: string; description: string; model: string; variant: string; task: Task; engine: 'image' | 'qwen21'; image_count: number; min_images: number; max_images: number; multi_image_picker: boolean; input_roles: InputRole[]; control_kind: string; prompt_supported: boolean; negative_supported: boolean; has_outpaint: boolean; has_controlnet_switch: boolean; has_power_lora: boolean; lora_options: LoraOption[]; node_classes: string[]; fields: Field[] }
type Run = { id: string; workflow: string; status: string; step: number; total_steps: number; seed: number; error?: string; elapsed_seconds: number; generation_seconds?: number; images: string[] }
type Compatibility = { ready: boolean; missing_nodes: string[]; missing_models: string[]; missing_inputs?: string[]; field_choices?: Record<string, (string | number | boolean)[]> }
const historyKey = 'bot-image-experiment-runs-v1'
const qwenRatios = ['1:1', '16:9', '9:16', '4:3', '3:2', '2:3']

function qwenDimensions(aspect: string, megapixels: number): [number, number] {
  const [ratioWidth, ratioHeight] = aspect.split(':').map(Number)
  const ratio = ratioWidth / ratioHeight
  const maxMegapixels = Math.min(4, (2048 * 2048 * Math.min(ratio, 1 / ratio)) / 1_000_000)
  const target = Math.min(Math.max(megapixels || 1, 0.25), maxMegapixels)
  const pixels = target * 1_000_000
  let width = Math.sqrt(pixels * ratio)
  let height = Math.sqrt(pixels / ratio)
  const scale = Math.min(1, 2048 / width, 2048 / height)
  width = Math.max(256, Math.round((width * scale) / 32) * 32)
  height = Math.max(256, Math.round((height * scale) / 32) * 32)
  return [width, height]
}

function fieldId(field: Field): string { return `${field.node}:${field.key}:${field.subkey || ''}` }
function getDetail(value: unknown): string { return typeof value === 'object' && value !== null && 'detail' in value ? String((value as { detail: unknown }).detail) : 'Request failed' }

const tasks: { id: Task; title: string; help: string; icon: typeof ImagePlus }[] = [
  { id: 'create', title: 'Create', help: 'Generate from text.', icon: ImagePlus },
  { id: 'edit', title: 'Edit / references', help: 'Change or guide an image.', icon: Pencil },
  { id: 'expand', title: 'Outpaint', help: 'Add to the canvas.', icon: Expand },
  { id: 'upscale', title: 'Upscale', help: 'Enlarge and refine.', icon: ZoomIn },
]

function ImagePicker({ index, file, role, onChange }: { index: number; file?: File; role?: InputRole; onChange: (file?: File) => void }) {
  const [preview, setPreview] = useState('')
  useEffect(() => {
    if (!file) { setPreview(''); return }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])
  return <div className="bot-images-upload">
    <label htmlFor={`bot-image-source-${index}`}><span>{role?.label || `Input image ${index + 1}`} <small>Required</small></span><input id={`bot-image-source-${index}`} type="file" accept="image/png,image/jpeg,image/webp" onChange={event => { onChange(event.target.files?.[0]); event.target.value = '' }} /></label>
    {file ? <div className="bot-images-picked"><img src={preview} alt={`Selected input ${index + 1}`} /><span>{file.name}</span><button type="button" aria-label={`Remove image ${index + 1}`} onClick={() => onChange()}><X size={16} /></button></div> : <small>{role?.help || 'Choose a JPG, PNG or WebP image (up to 20 MB).'}</small>}
  </div>
}

function MultiImagePreview({ file, index, count, onRemove, onMove }: {
  file: File; index: number; count: number; onRemove: () => void; onMove: (direction: -1 | 1) => void
}) {
  const [preview, setPreview] = useState('')
  useEffect(() => {
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])
  return <div className="bot-images-reference-row">
    {preview && <img src={preview} alt={`Qwen reference ${index + 1}`} />}
    <div><strong>Image {index + 1} · {index === 0 ? 'edit target' : 'supporting reference'}</strong><small>{file.name}</small></div>
    <div className="bot-images-reference-actions">
      <button type="button" aria-label={`Move image ${index + 1} up`} disabled={index === 0} onClick={() => onMove(-1)}><ArrowUp size={15} /></button>
      <button type="button" aria-label={`Move image ${index + 1} down`} disabled={index === count - 1} onClick={() => onMove(1)}><ArrowDown size={15} /></button>
      <button type="button" aria-label={`Remove image ${index + 1}`} onClick={onRemove}><X size={15} /></button>
    </div>
  </div>
}

function QwenReferencePicker({ files, max, onAdd, onRemove, onMove, onError }: {
  files: File[]; max: number; onAdd: (files: File[]) => void; onRemove: (index: number) => void;
  onMove: (index: number, direction: -1 | 1) => void; onError: (message: string) => void
}) {
  return <div className="bot-images-inputs bot-images-qwen-references">
    <strong>Reference images <span>{files.length}/{max} · image 1 is the edit target</span></strong>
    <label className="bot-images-multi-upload"><ImagePlus size={18} /><span>Add 1–10 images<small>Choose images in order. The first is the image to edit; later images guide details or style.</small></span>
      <input type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={event => {
        const selected = Array.from(event.target.files || [])
        if (files.length + selected.length > max) onError(`Qwen Image 2.1 accepts up to ${max} references.`)
        else if (selected.length) { onError(''); onAdd(selected) }
        event.target.value = ''
      }} />
    </label>
    {files.length > 0 && <div className="bot-images-reference-list">{files.map((file, index) => <MultiImagePreview key={`${file.name}-${file.size}-${index}`} file={file} index={index} count={files.length} onRemove={() => onRemove(index)} onMove={direction => onMove(index, direction)} />)}</div>}
    <small className="bot-images-reference-help">For precise control, refer to images in your prompt as &lt;image1&gt;, &lt;image2&gt;, and so on.</small>
  </div>
}

function LoraDropdown({ options, selected, onChange }: {
  options: LoraOption[]; selected: string[]; onChange: (files: string[]) => void
}) {
  const preset = options.filter(option => option.enabled_by_default)
  const optional = options.filter(option => !option.enabled_by_default)
  if (!options.length) return null
  return <div className="bot-images-lora-picker">
    {preset.length > 0 && <p><strong>Included by this recipe:</strong> {preset.map(option => option.filename).join(', ')}</p>}
    {optional.length > 0 && <details className="bot-images-lora-dropdown">
      <summary>Optional LoRAs <small>{selected.length ? `${selected.length} selected` : 'None selected'}</small></summary>
      <div className="bot-images-lora-options">{optional.map(option => <label key={option.filename}>
        <input type="checkbox" checked={selected.includes(option.filename)} onChange={event => onChange(event.target.checked ? [...selected, option.filename] : selected.filter(value => value !== option.filename))} />
        <span>{option.filename}</span>
      </label>)}</div>
    </details>}
    {optional.length === 0 && <small>No optional LoRAs are configured for this recipe.</small>}
  </div>
}

export function BotImagesPage({ csrf }: { csrf: string }) {
  const [engineReady, setEngineReady] = useState({ image: false, qwen21: false })
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [compatibility, setCompatibility] = useState<Record<string, Compatibility>>({})
  const [task, setTask] = useState<Task>('create')
  const [workflowName, setWorkflowName] = useState('')
  const [workflowSearch, setWorkflowSearch] = useState('')
  const [prompt, setPrompt] = useState('')
  const [negative, setNegative] = useState('')
  const [files, setFiles] = useState<(File | undefined)[]>([])
  const [advanced, setAdvanced] = useState<Record<string, string | number | boolean>>({})
  const [seed, setSeed] = useState('')
  const [steps, setSteps] = useState('')
  const [cfg, setCfg] = useState('')
  const [seednoise, setSeednoise] = useState('')
  const [upnoise, setUpnoise] = useState('')
  const [resWidth, setResWidth] = useState('')
  const [resHeight, setResHeight] = useState('')
  const [qwenAspect, setQwenAspect] = useState('1:1')
  const [qwenMegapixels, setQwenMegapixels] = useState('1')
  const [extend, setExtend] = useState({ left: 0, top: 0, right: 0, bottom: 0 })
  const [controlnet, setControlnet] = useState('')
  const [powerlora, setPowerlora] = useState<string[]>([])
  const [changeSampler, setChangeSampler] = useState(false)
  const [runIds, setRunIds] = useState<string[]>(() => { try { return JSON.parse(localStorage.getItem(historyKey) || '[]') as string[] } catch { return [] } })
  const [runs, setRuns] = useState<Record<string, Run>>({})
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const refresh = () => { void fetch('/api/bot-images/status', { cache: 'no-store' }).then(async response => {
      const data = await response.json() as { ready?: boolean; qwen21_ready?: boolean }
      if (active) setEngineReady({ image: response.ok && data.ready === true, qwen21: response.ok && data.qwen21_ready === true })
    }).catch(() => { if (active) setEngineReady({ image: false, qwen21: false }) }) }
    refresh()
    const timer = window.setInterval(refresh, 5000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  const selected = workflows.find(item => item.name === workflowName)
  const comfyReady = selected?.engine === 'qwen21' ? engineReady.qwen21 : engineReady.image
  const hasField = (key: string) => !!selected?.fields.some(field => field.key === key)
  const supportsResolution = !!selected?.node_classes.some(name => ['EmptySD3LatentImage', 'EmptyHunyuanLatentVideo', 'EmptyLatentImage'].includes(name))
  const qwenTextToImage = selected?.name === 'qwen21_t2i_api.json'
  const imageCount = files.filter((file): file is File => !!file).length
  const missingImages = !!selected && (selected.multi_image_picker ? imageCount < selected.min_images : Array.from({ length: selected.image_count }, (_, index) => !files[index]).some(Boolean))
  const canSubmit = comfyReady && selected && compatibility[selected.name]?.ready === true && (!selected.prompt_supported || !!prompt.trim()) && !missingImages && !sending && !Object.values(runs).some(run => ['queued', 'running'].includes(run.status))
  const taskWorkflows = useMemo(() => {
    const term = workflowSearch.trim().toLowerCase()
    const matches = workflows.filter(item => item.task === task && (!term || [item.title, item.description, item.model, item.variant, item.name].join(' ').toLowerCase().includes(term)))
    const current = workflows.find(item => item.name === workflowName && item.task === task)
    return current && !matches.some(item => item.name === current.name) ? [current, ...matches] : matches
  }, [workflows, task, workflowName, workflowSearch])
  const inputRole = (index: number): InputRole | undefined => {
    if (selected?.control_kind !== 'pose_depth' || index !== 1) return selected?.input_roles[index]
    if (controlnet === 'depth') return { label: 'Depth guide photo', help: 'Upload a photo whose spatial layout should guide the result. The workflow estimates its depth automatically.' }
    return { label: 'Pose guide photo', help: 'Upload a photo showing the body pose to follow. The workflow extracts pose landmarks automatically.' }
  }

  useEffect(() => {
    fetch('/api/bot-images/workflows', { cache: 'no-store' }).then(async response => {
      const data = await response.json() as { workflows?: Workflow[]; detail?: string }
      if (!response.ok) throw new Error(getDetail(data))
      setWorkflows(data.workflows || [])
      setWorkflowName(current => current || data.workflows?.find(item => item.task === 'create')?.name || '')
    }).catch(reason => setError(String(reason)))
  }, [])
  useEffect(() => {
    fetch('/api/bot-images/compatibility', { cache: 'no-store' }).then(async response => {
      if (!response.ok) return
      const data = await response.json() as { workflows: Record<string, Compatibility> }
      setCompatibility(data.workflows)
    }).catch(() => {})
  }, [engineReady.image, engineReady.qwen21])
  useEffect(() => { localStorage.setItem(historyKey, JSON.stringify(runIds.slice(0, 30))) }, [runIds])
  useEffect(() => {
    if (!runIds.length) return
    let active = true
    const refresh = async () => {
      const data = await Promise.all(runIds.map(async id => {
        try {
          const response = await fetch(`/api/bot-images/runs/${id}`, { cache: 'no-store' })
          return response.ok ? await response.json() as Run : null
        } catch { return null }
      }))
      if (active) setRuns(Object.fromEntries(data.filter((item): item is Run => !!item).map(item => [item.id, item])))
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 2500)
    return () => { active = false; window.clearInterval(timer) }
  }, [runIds])

  const switchWorkflow = (name: string) => {
    const nextTask = workflows.find(item => item.name === name)?.task
    if (nextTask) setTask(nextTask)
    setWorkflowName(name); setFiles([]); setAdvanced({}); setPrompt(''); setNegative(''); setError('')
    setSeed(''); setSteps(''); setCfg(''); setSeednoise(''); setUpnoise(''); setResWidth(''); setResHeight('')
    setQwenAspect('1:1'); setQwenMegapixels('1')
    setExtend({ left: 0, top: 0, right: 0, bottom: 0 }); setControlnet(''); setPowerlora([]); setChangeSampler(false)
  }

  const switchTask = (nextTask: Task) => {
    if (nextTask === task) return
    setTask(nextTask)
    setWorkflowSearch('')
    const next = workflows.find(item => item.task === nextTask)
    if (next) switchWorkflow(next.name)
    else { setWorkflowName(''); setFiles([]); setPrompt(''); setNegative(''); setError('') }
  }

  const submit = async () => {
    if (!selected || !canSubmit) return
    setSending(true); setError('')
    try {
      const flags: Record<string, unknown> = {}
      if (seed.trim()) flags.seed = Number(seed)
      if (steps.trim()) flags.steps = Number(steps)
      if (cfg.trim()) flags.cfg = Number(cfg)
      if (seednoise.trim()) flags.seednoise = Number(seednoise)
      if (upnoise.trim()) flags.upnoise = Number(upnoise)
      if (qwenTextToImage) flags.res = qwenDimensions(qwenAspect, Number(qwenMegapixels))
      else if (resWidth.trim() || resHeight.trim()) flags.res = [Number(resWidth), Number(resHeight)]
      if (selected.has_outpaint) flags.extend = extend
      if (controlnet) flags.controlnet = controlnet
      if (powerlora.length) flags.powerlora = powerlora
      if (changeSampler) flags.chngsmp = true
      const overrides = selected.fields.filter(field => fieldId(field) in advanced).map(field => ({ node: field.node, key: field.key, subkey: field.subkey, value: advanced[fieldId(field)] }))
      const form = new FormData()
      form.set('payload', JSON.stringify({ workflow: selected.name, prompt, negative, flags, overrides }))
      files.forEach(file => { if (file) form.append('images', file) })
      const response = await fetch('/api/bot-images/runs', { method: 'POST', headers: { 'X-CSRF-Token': csrf }, body: form })
      const data = await response.json() as Run & { detail?: string }
      if (!response.ok) throw new Error(getDetail(data))
      setRuns(current => ({ ...current, [data.id]: data }))
      setRunIds(current => [data.id, ...current.filter(id => id !== data.id)].slice(0, 30))
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setSending(false) }
  }

  const remove = async (id: string) => {
    if (!window.confirm('Delete this generated image from storage?')) return
    const response = await fetch(`/api/bot-images/runs/${id}`, { method: 'DELETE', headers: { 'X-CSRF-Token': csrf } })
    const data = await response.json() as { detail?: string }
    if (!response.ok) { setError(getDetail(data)); return }
    setRunIds(current => current.filter(value => value !== id))
  }

  return <section className="bot-images-page">
    <div className="bot-images-head"><div><span className="eyebrow"><ImageIcon size={15} /> Image workflow lab</span><h2>Image Lab</h2><p>Choose what you want to do, pick a ready-made recipe, add a prompt or image, then generate. H3 video workflows stay untouched.</p></div><span className={`bot-images-count ${comfyReady ? 'is-ready' : 'is-offline'}`}><i />{comfyReady ? selected?.engine === 'qwen21' ? 'Qwen local engine ready' : 'Image engine ready' : selected?.engine === 'qwen21' ? 'Qwen engine offline' : 'Image engine offline'}</span></div>
    <div className="bot-images-panel">
      <div className="bot-images-step"><span className="bot-images-step-number">1</span><div><h3>Choose a task</h3><p>Only workflows for this task are shown below.</p></div></div>
      <div className="bot-images-task-tabs" role="group" aria-label="Image task">{tasks.map(item => { const Icon = item.icon; const count = workflows.filter(workflow => workflow.task === item.id).length; return <button type="button" key={item.id} className={task === item.id ? 'active' : ''} onClick={() => switchTask(item.id)} aria-pressed={task === item.id}><Icon size={17} /><span>{item.title}</span><small>{count}</small></button> })}</div>

      <div className="bot-images-step"><span className="bot-images-step-number">2</span><div><h3>Choose a workflow</h3><p>Search by model, number of images, steps, or guidance type.</p></div></div>
      <label className="bot-images-search"><span>Search workflows</span><input type="search" value={workflowSearch} onChange={event => setWorkflowSearch(event.target.value)} placeholder="For example: Qwen, 3 images, depth, 8 steps" /></label>
      <label className="bot-images-workflow-select"><span>Workflow</span><select value={workflowName} onChange={event => switchWorkflow(event.target.value)} disabled={!taskWorkflows.length}><option value="" disabled>Select a workflow</option>{taskWorkflows.map(item => <option key={item.name} value={item.name}>{item.title}</option>)}</select></label>
      {taskWorkflows.length === 0 && workflows.length > 0 && <p className="bot-images-note">No matching workflows. Try a different search or task.</p>}
      {selected && <div className="bot-images-recipe-detail"><div className="bot-images-recipe-detail-head"><h3>{selected.title}</h3></div><p>{selected.description}</p><span className={`bot-images-compatibility ${compatibility[selected.name]?.ready ? 'is-ready' : compatibility[selected.name] ? 'is-missing' : ''}`}>{compatibility[selected.name] ? compatibility[selected.name].ready ? <><Check size={14} /> Ready on {selected.engine === 'qwen21' ? 'local Qwen engine' : 'image engine'}</> : 'Requires setup' : 'Checking this workflow…'}</span></div>}

      {selected && <>
        <div className="bot-images-step"><span className="bot-images-step-number">3</span><div><h3>Add your prompt and required images</h3><p>Each image slot below says exactly what to upload there.</p></div></div>
        <div className="bot-images-generation-summary"><strong>Before you generate</strong><span>{selected.multi_image_picker ? `${selected.min_images} required · up to ${selected.max_images} ordered references` : selected.image_count ? `${selected.image_count} required input image${selected.image_count === 1 ? '' : 's'}` : 'No input image required'}</span><span>{selected.prompt_supported ? 'Prompt required' : 'No prompt input'}</span></div>
        {compatibility[selected.name] && !compatibility[selected.name].ready && <div className="bot-images-error"><strong>This recipe needs setup before it can run.</strong>{compatibility[selected.name].missing_nodes.length > 0 && <p>Missing nodes: {compatibility[selected.name].missing_nodes.join(', ')}</p>}{(compatibility[selected.name].missing_inputs || []).length > 0 && <p>Missing required inputs: {compatibility[selected.name].missing_inputs?.join(', ')}</p>}{compatibility[selected.name].missing_models.length > 0 && <p>Missing models/options: {compatibility[selected.name].missing_models.join('; ')}</p>}</div>}
        {selected.prompt_supported && <label className="bot-images-prompt"><span>{selected.task === 'edit' ? 'What should change in the image?' : 'What should the image look like?'}</span><textarea value={prompt} onChange={event => setPrompt(event.target.value)} rows={5} maxLength={8000} placeholder={selected.engine === 'qwen21' && selected.task === 'edit' ? 'Example: Keep <image1> as the base. Take the jacket color from <image2> and the lighting mood from <image3>.' : 'Example: A cinematic product photo of a silver perfume bottle on wet black stone, dramatic studio lighting, premium editorial style…'} /><small>{selected.engine === 'qwen21' && selected.task === 'edit' ? 'State what to preserve and what to change. Refer to ordered references as <image1>, <image2>, etc.' : 'Be specific about the subject, setting, style, lighting and any text you want visible.'}</small></label>}
        {selected.has_controlnet_switch && <div className="bot-images-control"><label><span>What should input image 2 guide?</span><select value={controlnet} onChange={event => setControlnet(event.target.value)}><option value="">Pose guidance (workflow default)</option><option value="openpose">Extract body pose from image 2</option><option value="depth">Extract scene depth from image 2</option></select></label><small>Image 2 is processed as a structural guide. It does not act as an identity/reference image.</small></div>}
        {selected.multi_image_picker && <QwenReferencePicker files={files.filter((file): file is File => !!file)} max={selected.max_images} onAdd={added => setFiles(current => [...current.filter((file): file is File => !!file), ...added])} onRemove={index => setFiles(current => current.filter((_, itemIndex) => itemIndex !== index))} onMove={(index, direction) => setFiles(current => { const next = current.filter((file): file is File => !!file); const target = index + direction; if (target < 0 || target >= next.length) return next; [next[index], next[target]] = [next[target], next[index]]; return next })} onError={setError} />}
        {!selected.multi_image_picker && selected.image_count > 0 && <div className="bot-images-inputs"><strong>Input images <span>{files.filter(Boolean).length}/{selected.image_count} added</span></strong><div className="bot-images-input-grid">{Array.from({ length: selected.image_count }, (_, index) => <ImagePicker key={`${selected.name}-${index}`} index={index} role={inputRole(index)} file={files[index]} onChange={file => setFiles(current => { const next = [...current]; next[index] = file; next.length = selected.image_count; return next })} />)}</div></div>}
        <details className="bot-images-settings"><summary>Quality and generation settings <small>Optional · defaults come from the recipe</small></summary><div className="bot-images-grid">
          {selected.node_classes.some(name => ['KSampler', 'RandomNoise'].includes(name)) && <label><span>Seed <small>Leave blank for a random result</small></span><input type="number" min="0" step="1" value={seed} onChange={event => setSeed(event.target.value)} placeholder="Random" /></label>}
          {hasField('steps') && <label><span>Steps <small>More steps may take longer</small></span><input type="number" min="1" step="1" value={steps} onChange={event => setSteps(event.target.value)} placeholder="Recipe default" /></label>}
          {hasField('cfg') && <label><span>Prompt strength</span><input type="number" step="0.1" value={cfg} onChange={event => setCfg(event.target.value)} placeholder="Recipe default" /></label>}
          {hasField('denoise') && <label><span>Edit strength <small>How much the source image can change</small></span><input type="number" min="0" max="1" step="0.01" value={seednoise} onChange={event => setSeednoise(event.target.value)} placeholder="Recipe default" /></label>}
          {selected.node_classes.includes('UltimateSDUpscale') && <label><span>Upscale creativity</span><input type="number" min="0" max="1" step="0.01" value={upnoise} onChange={event => setUpnoise(event.target.value)} placeholder="Recipe default" /></label>}
          {qwenTextToImage && <><label><span>Aspect ratio</span><select value={qwenAspect} onChange={event => setQwenAspect(event.target.value)}>{qwenRatios.map(ratio => <option key={ratio} value={ratio}>{ratio}</option>)}</select></label><label><span>Megapixels <small>Max varies with aspect ratio</small></span><input type="number" min="0.25" max={Math.min(4, (2048 * 2048 * Math.min(Number(qwenAspect.split(':')[0]) / Number(qwenAspect.split(':')[1]), Number(qwenAspect.split(':')[1]) / Number(qwenAspect.split(':')[0]))) / 1_000_000)} step="0.1" value={qwenMegapixels} onChange={event => setQwenMegapixels(event.target.value)} /></label><p className="bot-images-resolution-note">Output uses multiples of 32 and stays at or below 2048 px per side. Larger images take more VRAM/time.</p></>}
          {supportsResolution && !qwenTextToImage && <><label><span>Width <small>Pixels</small></span><input type="number" min="64" max="8192" step="1" value={resWidth} onChange={event => setResWidth(event.target.value)} placeholder="Recipe default" /></label><label><span>Height <small>Pixels</small></span><input type="number" min="64" max="8192" step="1" value={resHeight} onChange={event => setResHeight(event.target.value)} placeholder="Recipe default" /></label></>}
        </div>
          {selected.negative_supported && <label className="bot-images-optional-prompt"><span>Avoid in the result <small>Optional</small></span><textarea value={negative} onChange={event => setNegative(event.target.value)} rows={2} maxLength={8000} placeholder="Things you do not want to see" /></label>}
          {selected.has_outpaint && <div className="bot-images-options"><strong>Canvas expansion</strong><p>Choose how much new canvas to add on each side (pixels).</p><div className="bot-images-grid">{(['left', 'top', 'right', 'bottom'] as const).map(side => <label key={side}><span>{side}</span><input type="number" min="0" max="2048" value={extend[side]} onChange={event => setExtend(current => ({ ...current, [side]: Number(event.target.value) }))} /></label>)}</div></div>}
          {selected.has_power_lora && <LoraDropdown options={selected.lora_options || []} selected={powerlora} onChange={setPowerlora} />}
          {hasField('sampler_name') && <label className="bot-images-check"><input type="checkbox" checked={changeSampler} onChange={event => setChangeSampler(event.target.checked)} /><span>Use DPM++ 2M / Karras sampler</span></label>}
        </details>
        <details className="bot-images-advanced-details"><summary>Expert controls <small>{selected.fields.length} underlying workflow inputs</small></summary><div className="bot-images-advanced"><p>Enumerable choices come from the active ComfyUI server; other values keep the recipe default unless edited.</p>{selected.fields.map(field => {
          const id = fieldId(field)
          const value = advanced[id] ?? field.value
          const choices = compatibility[selected.name]?.field_choices?.[id]
          const hasCurrentChoice = choices?.some(choice => String(choice) === String(value)) ?? false
          return <label key={id}><span>{field.label} <small>#{field.node}</small></span>
            {choices?.length ? <select value={String(value)} onChange={event => setAdvanced(current => ({ ...current, [id]: event.target.value }))}>
              {!hasCurrentChoice && <option value={String(value)}>{String(value)} · recipe value</option>}
              {choices.map(choice => <option key={String(choice)} value={String(choice)}>{String(choice)}</option>)}
            </select> : field.type === 'boolean' ? <select value={String(value)} onChange={event => setAdvanced(current => ({ ...current, [id]: event.target.value === 'true' }))}><option value="true">True</option><option value="false">False</option></select> : <input type={field.type} step={field.type === 'number' ? 'any' : undefined} value={String(value)} onChange={event => setAdvanced(current => ({ ...current, [id]: field.type === 'number' ? (Number.isInteger(field.value) ? Number.parseInt(event.target.value, 10) : Number(event.target.value)) : event.target.value }))} />}
          </label>
        })}</div></details>
        <button type="button" className="bot-images-submit" onClick={() => { void submit() }} disabled={!canSubmit}>{sending ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{sending ? 'Sending to image engine…' : 'Generate image'}</button>
        {comfyReady && selected && compatibility[selected.name]?.ready !== false && !canSubmit && <p className="bot-images-note">{missingImages ? selected.multi_image_picker ? 'Add at least the image to edit; additional references are optional.' : `Add all ${selected.image_count} required image${selected.image_count === 1 ? '' : 's'} to continue.` : !prompt.trim() && selected.prompt_supported ? 'Add a prompt to continue.' : Object.values(runs).some(run => ['queued', 'running'].includes(run.status)) ? 'Wait for the current image generation to finish before starting another.' : 'Preparing this recipe…'}</p>}
        {!comfyReady && <p className="bot-images-note">The image engine is offline. You can browse recipes, but generation will be available when it reconnects.</p>}
      </>}
      {!workflows.length && <p className="bot-images-note">No image workflow graphs were found in the configured bot directory.</p>}
      {error && <div className="bot-images-error" role="alert">{error}</div>}
    </div>
    <div className="bot-images-results"><h3>Recent generations</h3>{runIds.length ? runIds.map(id => { const run = runs[id]; return run ? <article className="bot-images-result" key={id}><div className="bot-images-result-head"><strong>{run.workflow}</strong><span>{run.status}</span></div><p>Seed {run.seed} · {run.total_steps ? `step ${run.step}/${run.total_steps} · ` : ''}{run.generation_seconds ? `generated in ${run.generation_seconds}s` : `elapsed ${run.elapsed_seconds}s`}</p>{run.error && <div className="bot-images-error">{run.error}</div>}{run.images.map((url, index) => <div key={url}><img src={url} alt={`${run.workflow} output ${index + 1}`} /><a href={url} download><Download size={15} /> Download image {index + 1}</a></div>)}{['completed', 'failed'].includes(run.status) && <button type="button" onClick={() => { void remove(id) }}><Trash2 size={14} /> Delete</button>}</article> : <div className="bot-images-result" key={id}><RefreshCw size={15} /> Run {id.slice(0, 8)} is not available in this app process</div> }) : <p>No image runs yet.</p>}</div>
  </section>
}
