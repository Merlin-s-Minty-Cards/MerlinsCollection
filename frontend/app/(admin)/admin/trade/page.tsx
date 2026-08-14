'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter, usePathname, useSearchParams } from 'next/navigation'
import { Check, Eye, EyeOff } from 'lucide-react'
import { useAdminApi, AdminApiError } from '@/lib/admin-api'
import { todayLocal } from '@/lib/dates'
import { useCardImages } from '@/lib/use-card-images'
import { adminItemName } from '@/lib/admin-item-name'
import { parseMoney } from '@/lib/money'
import type { BasisMode } from '@/lib/trade-basis'
import ConfirmDialog from '@/components/admin/shared/ConfirmDialog'
import type { PickerCard } from '@/components/admin/shared/CardPickerRow'
import DealSearchPanel, {
  sourceForMode,
  type DealMode,
  type SearchSource,
  type DealInventoryItem,
} from '@/components/admin/deal/DealSearchPanel'
import IncomingCardForm from '@/components/admin/deal/IncomingCardForm'
import DealStagedColumn from '@/components/admin/deal/DealStagedColumn'
import DealSummary from '@/components/admin/deal/DealSummary'
import type { DealRowCard } from '@/components/admin/deal/DealCardRow'
import { sessionApiFor, type CashComponent } from '@/lib/deal-session'
import type { IncomingLeg } from '@/lib/trade-incoming-form'

/**
 * One page, three modes — buy, sell, trade (RFC 0011 T15, §I).
 *
 * Replaces the old two-column trade-only page. Buy and Sell (their own routes,
 * `/admin/buy` and `/admin/sell`) are untouched by this task — T16 retires
 * them once this page has been reviewed and proven out.
 *
 * `lib/deal-session.ts` is the ONLY place that knows which of the three
 * session APIs (`/purchases`, `/sales`, `/trades`) a mode talks to. This file
 * never branches on `mode` to build a URL — it asks the adapter's `supports`
 * flags to decide what to render, and hands the adapter's methods the data
 * they need.
 */

const MODES: DealMode[] = ['buy', 'sell', 'trade']

interface StagedIncoming extends DealRowCard {
  agreedValue: number
}

interface StagedOutgoing extends DealRowCard {
  itemId: string
  agreedValue: number
  /** From the picked inventory item, when it carried one. Server-sent, so a
   *  straight parse is safe — see lib/money.ts. */
  costBasis: number | null
}

function modeLabel(mode: DealMode): string {
  return mode.charAt(0).toUpperCase() + mode.slice(1)
}

export default function DealPage() {
  const api = useAdminApi()
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const modeParam = searchParams.get('mode')
  const mode: DealMode = (MODES as string[]).includes(modeParam ?? '') ? (modeParam as DealMode) : 'trade'

  const session = useMemo(() => sessionApiFor(mode, api), [mode, api])

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [source, setSource] = useState<SearchSource>(() => {
    const s = sourceForMode(mode)
    return s === 'inventory' ? 'inventory' : 'catalog'
  })
  const [incoming, setIncoming] = useState<StagedIncoming[]>([])
  const [outgoing, setOutgoing] = useState<StagedOutgoing[]>([])
  const [cashComponents, setCashComponents] = useState<CashComponent[]>([])
  const [customerView, setCustomerView] = useState(false)
  const [date, setDate] = useState(todayLocal())
  const [counterparty, setCounterparty] = useState('')
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [basisMode, setBasisMode] = useState<BasisMode>('transfer')
  const [manualBasis, setManualBasis] = useState('')

  // `undefined` = closed. `null` = manual entry. A `PickerCard` = a catalog pick.
  const [formCard, setFormCard] = useState<PickerCard | null | undefined>(undefined)

  const [pendingMode, setPendingMode] = useState<DealMode | null>(null)
  const [showConfirm, setShowConfirm] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [confirmed, setConfirmed] = useState(false)

  // Create the session for the current mode. Re-runs whenever `session`
  // changes identity, which happens exactly when `mode` changes.
  useEffect(() => {
    if (!api.isAuthenticated || sessionId) return
    let cancelled = false
    session.create().then((id) => {
      if (!cancelled) setSessionId(id)
    }).catch(() => { /* surfaced when the operator tries to add a card */ })
    return () => { cancelled = true }
  }, [api.isAuthenticated, session]) // eslint-disable-line react-hooks/exhaustive-deps

  // A mode that locks the search source (buy = catalog, sell = inventory)
  // overrides whatever was picked in trade's toggle.
  useEffect(() => {
    const s = sourceForMode(mode)
    if (s !== 'both') setSource(s)
  }, [mode])

  const { getImageUrl } = useCardImages([
    ...incoming.map((i) => i.card_id),
    ...outgoing.map((o) => o.card_id),
  ])

  const isEmpty = incoming.length === 0 && outgoing.length === 0

  const resetSessionState = () => {
    setSessionId(null)
    setIncoming([])
    setOutgoing([])
    setCashComponents([])
    setBasisMode('transfer')
    setManualBasis('')
    setCounterparty('')
    setPaymentMethod('cash')
    setFormCard(undefined)
    setDate(todayLocal())
  }

  const applyModeSwitch = (next: DealMode) => {
    resetSessionState()
    router.replace(`${pathname}?mode=${next}`)
  }

  const handleModeChange = (next: DealMode) => {
    if (next === mode) return
    if (!isEmpty) {
      setPendingMode(next)
      return
    }
    applyModeSwitch(next)
  }

  const confirmModeSwitch = () => {
    if (pendingMode) applyModeSwitch(pendingMode)
    setPendingMode(null)
  }

  const handleAddIncoming = async (leg: IncomingLeg) => {
    if (!sessionId) return
    try {
      await session.addIncoming(sessionId, leg)
      setIncoming((prev) => [...prev, {
        name: leg.name,
        card_id: leg.card_id,
        meta: [leg.set_name, leg.card_number && `#${leg.card_number}`].filter(Boolean).join(' · ') || undefined,
        price: leg.agreed_value,
        priceLabel: 'value',
        agreedValue: leg.agreed_value,
      }])
      setFormCard(undefined)
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to add card')
    }
  }

  const handlePickInventory = async (item: DealInventoryItem) => {
    if (!sessionId) return
    const raw = item.sticker_price ?? item.current_market_value ?? 0
    const value = parseMoney(String(raw)) ?? 0
    const costBasisRaw = (item as unknown as { cost_basis?: string | number | null }).cost_basis
    const costBasis = costBasisRaw === undefined || costBasisRaw === null ? null : parseMoney(String(costBasisRaw))
    try {
      await session.addOutgoing(sessionId, item, value)
      setOutgoing((prev) => [...prev, {
        itemId: item.item_id,
        name: adminItemName(item, ''),
        card_id: item.card_id ?? null,
        meta: [item.set_name, item.card_number && `#${item.card_number}`].filter(Boolean).join(' · ') || undefined,
        price: value,
        priceLabel: 'value',
        agreedValue: value,
        costBasis,
      }])
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to add card')
    }
  }

  const removeIncoming = async (idx: number) => {
    if (!sessionId) return
    try {
      await session.removeIncoming(sessionId, idx)
      setIncoming((prev) => prev.filter((_, i) => i !== idx))
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to remove card')
    }
  }

  /**
   * Editing a staged outgoing value updates local state immediately for a
   * responsive UI — `MoneyInput` owns its text so a half-typed "1," is not
   * thrown away on the next render — AND patches the session, so Confirm
   * sends the negotiated price rather than the picked item's original one
   * (RFC 0011 T15 fix round 1: this used to be local-only, so a price
   * negotiated down at the table was silently re-sent at the original
   * figure on confirm). `=== null`, never falsiness, so a re-typed `0` (a
   * throw-in) is accepted.
   */
  const editOutgoingValue = (idx: number, _raw: string, parsed: number | null) => {
    if (parsed === null) return
    const itemId = outgoing[idx]?.itemId
    setOutgoing((prev) => prev.map((row, i) => (i === idx ? { ...row, price: parsed, agreedValue: parsed } : row)))
    if (!sessionId || !itemId) return
    session.updateOutgoing(sessionId, itemId, parsed).catch((err) => {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to update price')
    })
  }

  const removeOutgoing = async (idx: number) => {
    if (!sessionId) return
    const itemId = outgoing[idx]?.itemId
    if (!itemId) return
    try {
      await session.removeOutgoing(sessionId, itemId)
      setOutgoing((prev) => prev.filter((_, i) => i !== idx))
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to remove card')
    }
  }

  const handleCashComponentsChange = (components: CashComponent[]) => {
    setCashComponents(components)
    if (!sessionId) return
    session.setCash(sessionId, components).catch(() => { /* balance simply stays stale */ })
  }

  const incomingTotal = incoming.reduce((s, i) => s + i.agreedValue, 0)
  const outgoingTotal = outgoing.reduce((s, o) => s + o.agreedValue, 0)
  const outgoingCostBasisTotal = outgoing.reduce((s, o) => s + (o.costBasis ?? o.agreedValue), 0)
  const cashNet = cashComponents.reduce((s, c) => s + (c.direction === 'they_pay' ? c.amount : -c.amount), 0)

  // The balance is what changes hands: positive means the counterparty owes
  // us (a sale, or a trade weighted toward us), negative means we owe them (a
  // buy). Net, never summed magnitudes — a $50-for-$30 trade is +$20, not $80.
  const balance = outgoingTotal - incomingTotal + cashNet

  let profit: number | null = null
  if (mode === 'sell') profit = outgoingTotal - outgoingCostBasisTotal
  if (mode === 'trade') {
    const costBasis = basisMode === 'manual' ? (parseMoney(manualBasis) ?? 0) : outgoingCostBasisTotal
    profit = incomingTotal + cashNet - costBasis
  }

  const handleConfirm = async () => {
    if (!sessionId) return
    setConfirming(true)
    try {
      await session.confirm(sessionId, {
        counterparty: counterparty || null,
        date,
        // Trade has no single payment method (its cash legs each carry their
        // own); Buy/Sell book under exactly one, chosen in `DealSummary`'s
        // payment-method select — never derived from the cash-component list,
        // which is a different concept (final-review Critical 2).
        payment_method: session.supports.costBasisMode ? undefined : paymentMethod,
        basis_mode: session.supports.costBasisMode ? basisMode : undefined,
        manual_basis:
          session.supports.costBasisMode && basisMode === 'manual'
            ? String(parseMoney(manualBasis) ?? 0)
            : undefined,
      })
      setConfirmed(true)
      setShowConfirm(false)
    } catch (err) {
      alert(err instanceof AdminApiError ? err.detail : 'Failed to confirm')
    } finally {
      setConfirming(false)
    }
  }

  const startNew = () => {
    setConfirmed(false)
    resetSessionState()
  }

  if (confirmed) {
    return (
      <div className="p-6 lg:p-8">
        <div className="vault-panel rounded-xl p-8 text-center">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-spriggatito-300/15 text-spriggatito-300 mb-4">
            <Check size={28} />
          </div>
          <h2 className="text-lg font-semibold text-pine-100 mb-1">
            {modeLabel(mode)} Confirmed
          </h2>
          <p className="text-sm text-pine-300 mb-4">
            {mode === 'buy' ? 'Purchase' : mode === 'sell' ? 'Sale' : 'Trade'} executed successfully.
          </p>
          <button
            type="button"
            onClick={startNew}
            className="px-4 py-2 rounded-lg text-xs font-medium bg-mint/15 text-mint border border-mint/30 hover:bg-mint/25 transition-colors"
          >
            Start New {modeLabel(mode)}
          </button>
        </div>
      </div>
    )
  }

  const withImages = (rows: (StagedIncoming | StagedOutgoing)[]): DealRowCard[] =>
    rows.map((r) => ({ ...r, imageUrl: r.card_id ? getImageUrl(r.card_id) : null }))

  return (
    <div className="p-6 lg:p-8">
      <header className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div className="flex items-center gap-4">
          <div>
            <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-spriggatito-300/70">
              Deal
            </span>
            <h1 className="text-xl font-semibold text-pine-100">{modeLabel(mode)}</h1>
          </div>
          <div role="radiogroup" aria-label="Deal mode" className="flex items-center gap-1">
            {MODES.map((m) => (
              <label
                key={m}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border cursor-pointer transition-colors ${
                  mode === m
                    ? 'bg-spriggatito-300/15 text-spriggatito-300 border-spriggatito-300/30'
                    : 'text-pine-400 border-pine-700/40 hover:border-pine-600'
                }`}
              >
                <input
                  type="radio"
                  name="deal-mode"
                  value={m}
                  checked={mode === m}
                  onChange={() => handleModeChange(m)}
                  className="sr-only"
                />
                {modeLabel(m)}
              </label>
            ))}
          </div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={customerView}
          onClick={() => setCustomerView((v) => !v)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
            customerView ? 'bg-amber-500/15 text-amber-400 border-amber-500/30' : 'text-pine-400 border-pine-700/40 hover:border-pine-600'
          }`}
        >
          {customerView ? <EyeOff size={13} /> : <Eye size={13} />}
          Customer View
        </button>
      </header>

      <div className="mb-6">
        {formCard === undefined ? (
          <DealSearchPanel
            mode={mode}
            source={source}
            onSourceChange={setSource}
            onPickCatalog={(card) => setFormCard(card)}
            onPickInventory={handlePickInventory}
            onManualEntry={() => setFormCard(null)}
            manualEntryAllowed={session.supports.incoming}
          />
        ) : (
          <div data-testid="incoming-form">
            <IncomingCardForm
              card={formCard}
              onAdd={handleAddIncoming}
              onCancel={() => setFormCard(undefined)}
              gradedAllowed={true}
            />
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {session.supports.incoming && (
          <DealStagedColumn
            title="Coming In"
            testId="coming-in"
            accentClassName="text-mint"
            rows={withImages(incoming)}
            onRemove={removeIncoming}
            total={incomingTotal}
            emptyLabel="No items coming in yet"
          />
        )}
        {session.supports.outgoing && (
          <DealStagedColumn
            title="Going Out"
            testId="going-out"
            accentClassName="text-red-400"
            rows={withImages(outgoing)}
            onRemove={removeOutgoing}
            onEditValue={editOutgoingValue}
            total={outgoingTotal}
            emptyLabel="No items going out yet"
          />
        )}
        <DealSummary
          mode={mode}
          supportsCostBasisMode={session.supports.costBasisMode}
          showProfit={mode !== 'buy'}
          customerView={customerView}
          cashComponents={cashComponents}
          onCashComponentsChange={handleCashComponentsChange}
          balance={balance}
          profit={profit}
          basisMode={basisMode}
          onBasisModeChange={setBasisMode}
          manualBasis={manualBasis}
          onManualBasisChange={setManualBasis}
          date={date}
          onDateChange={setDate}
          counterparty={counterparty}
          onCounterpartyChange={setCounterparty}
          paymentMethod={paymentMethod}
          onPaymentMethodChange={setPaymentMethod}
          onConfirm={() => setShowConfirm(true)}
          confirmDisabled={isEmpty}
        />
      </div>

      <ConfirmDialog
        open={showConfirm}
        title={`Confirm ${modeLabel(mode)}`}
        description={`${incoming.length} card${incoming.length !== 1 ? 's' : ''} in, ${outgoing.length} card${outgoing.length !== 1 ? 's' : ''} out${cashComponents.length > 0 ? ` + ${cashComponents.length} cash component${cashComponents.length !== 1 ? 's' : ''}` : ''}?`}
        confirmLabel={`Execute ${modeLabel(mode)}`}
        loading={confirming}
        onConfirm={handleConfirm}
        onCancel={() => setShowConfirm(false)}
      />

      <ConfirmDialog
        open={pendingMode !== null}
        title="Discard this session?"
        description="Switching modes starts a new session on a different API — this one has no migration path, so the in-progress deal will be discarded. Nothing has been saved to inventory yet."
        confirmLabel="Discard and switch"
        variant="danger"
        onConfirm={confirmModeSwitch}
        onCancel={() => setPendingMode(null)}
      />
    </div>
  )
}
