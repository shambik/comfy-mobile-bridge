import React, { useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'

export type FeedbackKind = 'success' | 'error' | 'info'
export type Feedback = { id: number; kind: FeedbackKind; message: string }

export function useFeedback() {
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const timerRef = useRef<number | null>(null)

  const dismiss = () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    timerRef.current = null
    setFeedback(null)
  }

  const notify = (kind: FeedbackKind, message: string, duration = 4200) => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    const id = Date.now() + Math.random()
    setFeedback({ id, kind, message })
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null
      setFeedback(current => current?.id === id ? null : current)
    }, duration)
  }

  useEffect(() => () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
  }, [])

  return { feedback, notify, dismiss }
}

export function FeedbackToast({ feedback, onDismiss }: { feedback: Feedback | null; onDismiss: () => void }) {
  if (!feedback) return null
  const Icon = feedback.kind === 'success' ? CheckCircle2 : feedback.kind === 'error' ? AlertCircle : Info
  return <div className={`feedback-toast ${feedback.kind}`} role={feedback.kind === 'error' ? 'alert' : 'status'} aria-live="polite">
    <Icon size={18} aria-hidden="true" />
    <span>{feedback.message}</span>
    <button type="button" onClick={onDismiss} aria-label="Dismiss notification"><X size={15} /></button>
  </div>
}
