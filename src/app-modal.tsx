import React, { FormEvent, useCallback, useEffect, useState } from 'react'
import { AlertTriangle, HelpCircle, X } from 'lucide-react'

export type AppModalRequest = {
  type: 'confirm' | 'prompt'
  title: string
  message: string
  eyebrow?: string
  defaultValue?: string
  placeholder?: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
  required?: boolean
}

type AppModalState = AppModalRequest & {
  resolve: (result: AppModalResult) => void
}

export type AppModalResult = { confirmed: boolean; value?: string }

export function useAppModal() {
  const [modal, setModal] = useState<AppModalState | null>(null)
  const [value, setValue] = useState('')

  const ask = useCallback((request: AppModalRequest) => new Promise<AppModalResult>(resolve => {
    setValue(request.defaultValue || '')
    setModal({ ...request, resolve })
  }), [])

  const askConfirm = useCallback((request: Omit<AppModalRequest, 'type'>) =>
    ask({ ...request, type: 'confirm' }).then(result => result.confirmed), [ask])

  const askPrompt = useCallback((request: Omit<AppModalRequest, 'type'>) =>
    ask({ ...request, type: 'prompt' }).then(result => result.confirmed ? result.value || '' : null), [ask])

  const resolveModal = useCallback((result: AppModalResult) => {
    setModal(current => {
      current?.resolve(result)
      return null
    })
  }, [])

  return { modal, value, setValue, askConfirm, askPrompt, resolveModal }
}

export function AppModal({ modal, value, onValueChange, onResolve }: {
  modal: AppModalState | null
  value: string
  onValueChange: (value: string) => void
  onResolve: (result: AppModalResult) => void
}) {
  useEffect(() => {
    if (!modal) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onResolve({ confirmed: false })
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [modal, onResolve])

  if (!modal) return null

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (modal.type === 'prompt' && modal.required && !value.trim()) return
    onResolve({ confirmed: true, value: modal.type === 'prompt' ? value : undefined })
  }

  return <div className="dialog-backdrop app-modal-backdrop" onMouseDown={() => onResolve({ confirmed: false })}>
    <form className={`app-modal ${modal.danger ? 'danger' : ''}`} role="dialog" aria-modal="true" onSubmit={submit} onMouseDown={event => event.stopPropagation()}>
      <div className="app-modal-head"><div className="app-modal-icon">{modal.danger ? <AlertTriangle size={21} /> : <HelpCircle size={21} />} </div><button type="button" className="app-modal-close" onClick={() => onResolve({ confirmed: false })} aria-label="סגירה"><X size={17} /></button></div>
      <div><span className="app-modal-eyebrow">{modal.eyebrow || (modal.type === 'prompt' ? 'פרטים נוספים' : 'אישור פעולה')}</span><h2>{modal.title}</h2></div>
      <p>{modal.message}</p>
      {modal.type === 'prompt' && <input autoFocus value={value} onChange={event => onValueChange(event.target.value)} placeholder={modal.placeholder} aria-label={modal.title} />}
      <div className="app-modal-actions"><button type="button" onClick={() => onResolve({ confirmed: false })}>{modal.cancelLabel || 'ביטול'}</button><button type="submit" className="confirm">{modal.confirmLabel || (modal.type === 'prompt' ? 'שמירה' : 'אישור')}</button></div>
    </form>
  </div>
}
