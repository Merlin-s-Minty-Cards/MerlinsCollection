'use client'

import { useState } from 'react'
import { Banknote, Calendar, CreditCard, DollarSign, Plus, Smartphone, X } from 'lucide-react'
import MoneyInput from '@/components/admin/shared/MoneyInput'
import { formatMoney, formatMoneyInput } from '@/lib/money'
import { availableModes, canConfirmBasis, type BasisMode } from '@/lib/trade-basis'
import type { CashComponent, DealMode } from '@/lib/deal-session'

/**
 * The summary rail — cash, balance, profit, basis mode, date and Confirm
 * (RFC 0011 T15). "The balance is the hero" per the RFC's design section: it
 * is the one figure every path through this page ends in, so it is the
 * largest thing on screen and never conditional on mode.
 *
 * Customer view removes cost basis and profit from the DOM entirely, not
 * `display:none` — a hidden node still copies and still reads aloud.
 */

const PAYMENT_METHOD_OPTIONS = [
  { value: 'cash', icon: Banknote, label: 'Cash' },
  { value: 'venmo', icon: Smartphone, label: 'Venmo' },
  { value: 'zelle', icon: DollarSign, label: 'Zelle' },
  { value: 'card', icon: CreditCard, label: 'Card' },
] as const

export interface DealSummaryProps {
  mode: DealMode
  supportsCostBasisMode: boolean
  showProfit: boolean
  customerView: boolean
  cashComponents: CashComponent[]
  onCashComponentsChange: (components: CashComponent[]) => void
  balance: number
  profit: number | null
  basisMode: BasisMode
  onBasisModeChange: (mode: BasisMode) => void
  manualBasis: string
  onManualBasisChange: (raw: string) => void
  date: string
  onDateChange: (date: string) => void
  counterparty: string
  onCounterpartyChange: (name: string) => void
  onConfirm: () => void
  confirmDisabled: boolean
  /**
   * Buy/Sell only (`!supportsCostBasisMode`) — the payment method the whole
   * deal books under, distinct from the cash-component list above (trade's
   * cash-difference tracking, not a single payment method). Without this the
   * old `/admin/sell` page's method selector had no replacement, so every
   * non-cash sale silently booked as `cash` (final-review Critical 2) — the
   * server defaults `payment_method` to `"cash"` when nothing overrides it.
   */
  paymentMethod?: string
  onPaymentMethodChange?: (method: string) => void
}

export default function DealSummary({
  mode,
  supportsCostBasisMode,
  showProfit,
  customerView,
  cashComponents,
  onCashComponentsChange,
  balance,
  profit,
  basisMode,
  onBasisModeChange,
  manualBasis,
  onManualBasisChange,
  date,
  onDateChange,
  counterparty,
  onCounterpartyChange,
  onConfirm,
  confirmDisabled,
  paymentMethod = 'cash',
  onPaymentMethodChange,
}: DealSummaryProps) {
  const hasCash = cashComponents.length > 0

  // Same reasoning as `DealStagedColumn`'s `drafts` map: a controlled input
  // whose `value` re-derives from the already-parsed number every render
  // loses whatever the parser can't yet make sense of — typing "1.50" or
  // "1,300" had the decimal point or comma vanish mid-keystroke, because the
  // parent immediately reflowed the field back to the last successfully
  // parsed integer (final-review Important 4). The raw typed string lives
  // here until it parses; the parsed number is what actually reaches
  // `onCashComponentsChange`.
  const [amountDrafts, setAmountDrafts] = useState<Record<number, string>>({})

  const addCashComponent = () => {
    onCashComponentsChange([...cashComponents, { direction: 'they_pay', amount: 0, payment_method: 'cash' }])
  }
  const updateCashComponent = (idx: number, updates: Partial<CashComponent>) => {
    onCashComponentsChange(cashComponents.map((c, i) => (i === idx ? { ...c, ...updates } : c)))
  }
  const removeCashComponent = (idx: number) => {
    onCashComponentsChange(cashComponents.filter((_, i) => i !== idx))
  }

  return (
    <div className="space-y-3" data-testid="deal-summary">
      <div className="vault-panel rounded-xl p-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-pine-400 uppercase tracking-wider">Cash</span>
          <button
            type="button"
            onClick={addCashComponent}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-pine-800/60 text-pine-300 border border-pine-700/40 hover:border-pine-600 transition-colors"
          >
            <Plus size={10} /> Add
          </button>
        </div>
        {cashComponents.length === 0 ? (
          <p className="text-[10px] text-pine-500">No cash in this deal</p>
        ) : (
          <div className="space-y-1.5">
            {cashComponents.map((comp, idx) => (
              <div key={idx} className="flex items-center gap-1.5">
                <select
                  aria-label={`Cash direction ${idx + 1}`}
                  value={comp.direction}
                  onChange={(e) => updateCashComponent(idx, { direction: e.target.value as CashComponent['direction'] })}
                  className="vault-field px-1.5 py-1 rounded text-[10px] w-[76px]"
                >
                  <option value="they_pay">They pay</option>
                  <option value="we_pay">We pay</option>
                </select>
                <select
                  aria-label={`Payment method ${idx + 1}`}
                  value={comp.payment_method}
                  onChange={(e) => updateCashComponent(idx, { payment_method: e.target.value as CashComponent['payment_method'] })}
                  className="vault-field px-1.5 py-1 rounded text-[10px] w-[68px]"
                >
                  {PAYMENT_METHOD_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
                <div className="relative flex-1">
                  <DollarSign size={10} className="absolute left-1.5 top-1/2 -translate-y-1/2 text-pine-500" />
                  <MoneyInput
                    label={`Cash amount ${idx + 1}`}
                    value={amountDrafts[idx] ?? formatMoneyInput(comp.amount)}
                    onChange={(raw, parsed) => {
                      setAmountDrafts((d) => ({ ...d, [idx]: raw }))
                      if (parsed !== null) updateCashComponent(idx, { amount: parsed })
                    }}
                    onBlur={() => {
                      setAmountDrafts((d) => {
                        const next = { ...d }
                        delete next[idx]
                        return next
                      })
                    }}
                    className="vault-field w-full pl-5 pr-1.5 py-1 rounded text-[10px] font-mono"
                    placeholder="0.00"
                  />
                </div>
                <button type="button" onClick={() => removeCashComponent(idx)} className="p-0.5 text-pine-500 hover:text-red-400">
                  <X size={10} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {supportsCostBasisMode && !customerView && (
        <div className="vault-panel rounded-xl p-3 space-y-2">
          <span className="text-[11px] text-pine-400 uppercase tracking-wider font-medium block">Cost Basis Mode</span>
          <div className="flex items-center gap-1 flex-wrap">
            {availableModes(hasCash).map(({ mode: m, disabled, reason }) => (
              <button
                key={m}
                type="button"
                disabled={disabled}
                title={reason ?? undefined}
                onClick={() => onBasisModeChange(m)}
                className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${
                  basisMode === m
                    ? 'bg-spriggatito-300/15 text-spriggatito-300 border-spriggatito-300/30'
                    : 'text-pine-400 border-pine-700/40 hover:border-pine-600'
                } disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                {m.charAt(0).toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
          {basisMode === 'manual' && (
            <div className="flex items-center gap-2">
              <label className="text-[10px] text-pine-400 uppercase tracking-wider">Total cost basis</label>
              <MoneyInput
                label="Total cost basis"
                value={manualBasis}
                onChange={(raw) => onManualBasisChange(raw)}
                className="vault-field w-28 px-2 py-1 rounded-lg text-xs font-mono"
                placeholder="0.00"
              />
            </div>
          )}
        </div>
      )}

      <div className="vault-panel rounded-xl p-4 text-center">
        <span className="text-[11px] text-pine-400 uppercase tracking-wider block mb-1">Balance</span>
        <div
          data-testid="deal-balance"
          className={`text-3xl font-mono font-semibold ${balance >= 0 ? 'text-mint' : 'text-red-400'}`}
        >
          {balance >= 0 ? '+' : '-'}{formatMoney(Math.abs(balance))}
        </div>
      </div>

      {showProfit && !customerView && (
        <div className="vault-panel rounded-xl p-3 text-center">
          <span className="text-[11px] text-pine-400 uppercase tracking-wider block mb-1">Profit</span>
          <div className={`text-lg font-mono ${(profit ?? 0) >= 0 ? 'text-mint' : 'text-red-400'}`}>
            {profit === null ? '—' : `${profit >= 0 ? '+' : '-'}${formatMoney(Math.abs(profit))}`}
          </div>
        </div>
      )}

      {!supportsCostBasisMode && onPaymentMethodChange && (
        <div className="vault-panel rounded-xl p-3 space-y-2">
          <label className="block">
            <span className="text-[11px] text-pine-400 uppercase tracking-wider">Payment method</span>
            <select
              aria-label="Payment method"
              value={paymentMethod}
              onChange={(e) => onPaymentMethodChange(e.target.value)}
              className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs"
            >
              {PAYMENT_METHOD_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
        </div>
      )}

      <div className="vault-panel rounded-xl p-3 space-y-2">
        <label className="block">
          <span className="text-[11px] text-pine-400 uppercase tracking-wider flex items-center gap-1">
            <Calendar size={11} /> Date
          </span>
          <input
            type="date"
            value={date}
            onChange={(e) => onDateChange(e.target.value)}
            className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs"
          />
        </label>
        <label className="block">
          <span className="text-[11px] text-pine-400 uppercase tracking-wider">
            {mode === 'trade' ? 'Trading with' : mode === 'buy' ? 'Seller' : 'Customer'}
          </span>
          <input
            value={counterparty}
            onChange={(e) => onCounterpartyChange(e.target.value)}
            placeholder="Name (optional)"
            className="vault-field w-full mt-1 px-2.5 py-1.5 rounded-lg text-xs"
          />
        </label>
        <button
          type="button"
          onClick={onConfirm}
          disabled={
            confirmDisabled ||
            (supportsCostBasisMode && !canConfirmBasis(basisMode, hasCash, manualBasis))
          }
          className="w-full px-4 py-2 rounded-lg text-sm font-medium bg-spriggatito-300/15 text-spriggatito-300 border border-spriggatito-300/30 hover:bg-spriggatito-300/25 disabled:opacity-40 transition-colors"
        >
          Confirm {mode === 'buy' ? 'Purchase' : mode === 'sell' ? 'Sale' : 'Trade'}
        </button>
      </div>
    </div>
  )
}
