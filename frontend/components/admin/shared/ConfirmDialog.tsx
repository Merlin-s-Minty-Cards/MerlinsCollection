'use client'

import { useEffect, useRef, type ReactNode } from 'react'
import { AlertTriangle, X } from 'lucide-react'

interface ConfirmDialogProps {
  open: boolean
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'default'
  loading?: boolean
  /**
   * Extra content between the description and the buttons — a required reason
   * field, a warning, a preview. Added for RFC 0010 T11's void, where the
   * reason is the whole point of choosing void over delete, and where a second
   * bespoke dialog would have been the third confirm pattern in the admin.
   */
  children?: ReactNode
  /** Gate the confirm on something the child collects (e.g. a non-empty reason). */
  confirmDisabled?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'default',
  loading = false,
  children,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const handleCancel = (e: Event) => {
      e.preventDefault()
      onCancel()
    }
    dialog.addEventListener('cancel', handleCancel)
    return () => dialog.removeEventListener('cancel', handleCancel)
  }, [onCancel])

  return (
    <dialog
      ref={dialogRef}
      className="backdrop:bg-black/60 bg-transparent p-0 m-auto max-w-md w-[calc(100%-2rem)] open:flex"
      aria-labelledby="confirm-title"
    >
      <div className="vault-panel rounded-xl p-5 w-full shadow-2xl">
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            {variant === 'danger' && (
              <AlertTriangle size={18} className="text-red-400" />
            )}
            <h2 id="confirm-title" className="text-sm font-semibold text-pine-100">
              {title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="p-1 rounded text-pine-400 hover:text-pine-200 transition-colors"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        {description && (
          <p className="text-xs text-pine-300 mb-4 leading-relaxed">
            {description}
          </p>
        )}

        {children && <div className="mb-4">{children}</div>}

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="px-3.5 py-1.5 rounded-lg text-xs font-medium text-pine-300 hover:bg-pine-700/50 transition-colors disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading || confirmDisabled}
            className={`
              px-3.5 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50
              ${variant === 'danger'
                ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30'
                : 'bg-mint/15 text-mint hover:bg-mint/25 border border-mint/30'
              }
            `}
          >
            {loading ? 'Processing…' : confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  )
}
