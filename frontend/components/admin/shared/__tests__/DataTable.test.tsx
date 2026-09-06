import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import DataTable, { Column } from '../DataTable'

interface Row {
  id: string
  name: string
  cost_basis: string
  finish_attributes: string[]
}

const ROWS: Row[] = [
  { id: '1', name: 'Charizard', cost_basis: '10.00', finish_attributes: ['holofoil'] },
  { id: '2', name: 'Pikachu', cost_basis: '2.50', finish_attributes: [] },
]

describe('DataTable — columns with no edit spec', () => {
  it('renders read-only exactly as before, with no editor affordance', () => {
    const columns: Column<Row>[] = [
      { key: 'name', label: 'Name', render: (r) => <span>{r.name}</span> },
    ]
    render(<DataTable columns={columns} data={ROWS} keyField="id" />)
    expect(screen.getByText('Charizard')).toBeInTheDocument()
    // No click-to-edit affordance: clicking does not open an input.
    fireEvent.click(screen.getByText('Charizard'))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })
})

describe('DataTable — columns with an edit spec', () => {
  const makeColumns = (save: (item: Row, next: string) => Promise<void>, disabled?: (item: Row) => boolean): Column<Row>[] => [
    {
      key: 'cost_basis',
      label: 'Cost',
      render: (r) => <span>${r.cost_basis}</span>,
      edit: {
        type: 'money',
        value: (r) => r.cost_basis,
        save,
        disabled,
      },
    },
  ]

  it('opens an editor on click, passing the rendered display as displayValue', () => {
    render(<DataTable columns={makeColumns(vi.fn())} data={ROWS} keyField="id" />)
    fireEvent.click(screen.getByText('$10.00'))
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('opens an editor on Enter (keyboard-reachable, not hover-only)', () => {
    render(<DataTable columns={makeColumns(vi.fn())} data={ROWS} keyField="id" />)
    const cell = screen.getByText('$10.00').closest('[role="button"]') as HTMLElement
    fireEvent.keyDown(cell, { key: 'Enter' })
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('calls save(item, next) on commit', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    render(<DataTable columns={makeColumns(save)} data={ROWS} keyField="id" />)
    fireEvent.click(screen.getByText('$10.00'))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '15.00' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(save).toHaveBeenCalledWith(ROWS[0], '15')
  })

  it('disabled(item) suppresses the editor for that row only', () => {
    render(
      <DataTable
        columns={makeColumns(vi.fn(), (r) => r.id === '1')}
        data={ROWS}
        keyField="id"
      />
    )
    fireEvent.click(screen.getByText('$10.00'))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    // Row 2 is not disabled and still opens.
    fireEvent.click(screen.getByText('$2.50'))
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('a rejecting save keeps the editor open and calls onEditError at the table level', async () => {
    const save = vi.fn().mockRejectedValue(new Error('nope'))
    const onEditError = vi.fn()
    render(
      <DataTable columns={makeColumns(save)} data={ROWS} keyField="id" onEditError={onEditError} />
    )
    fireEvent.click(screen.getByText('$10.00'))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '15.00' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onEditError).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('sorting and selection still work with editable cells present', () => {
    const onSort = vi.fn()
    const onSelect = vi.fn()
    const columns: Column<Row>[] = [
      {
        key: 'name',
        label: 'Name',
        sortable: true,
        render: (r) => <span>{r.name}</span>,
      },
      ...makeColumns(vi.fn()),
    ]
    render(
      <DataTable
        columns={columns}
        data={ROWS}
        keyField="id"
        onSort={onSort}
        selectedIds={new Set()}
        onSelect={onSelect}
      />
    )
    fireEvent.click(screen.getByText('Name'))
    expect(onSort).toHaveBeenCalledWith('name')
    fireEvent.click(screen.getAllByRole('checkbox')[1]) // [0] is "select all"
    expect(onSelect).toHaveBeenCalledWith('1', true)
  })
})

describe('DataTable — multiselect edit spec', () => {
  it('wires multiselectValue/saveMultiselect through to InlineEditCell', async () => {
    const saveMultiselect = vi.fn().mockResolvedValue(undefined)
    const columns: Column<Row>[] = [
      {
        key: 'finish_attributes',
        label: 'Finishes',
        render: (r) => <span>{r.finish_attributes.join(', ') || '—'}</span>,
        edit: {
          type: 'multiselect',
          options: [
            { value: 'holofoil', label: 'Holofoil' },
            { value: 'normal', label: 'Normal' },
          ],
          value: () => '',
          save: async () => {},
          multiselectValue: (r) => r.finish_attributes,
          saveMultiselect,
        },
      },
    ]
    render(<DataTable columns={columns} data={ROWS} keyField="id" />)
    fireEvent.click(screen.getByText('holofoil'))
    await act(async () => {
      fireEvent.click(screen.getByRole('checkbox', { name: 'Normal' }))
    })
    expect(saveMultiselect).toHaveBeenCalledWith(ROWS[0], ['holofoil', 'normal'])
  })
})

describe('DataTable — undo toast (RFC 0022 T3)', () => {
  // Scoped to setTimeout/clearTimeout only — full fake timers deadlock
  // React's async rendering/act flush (CLAUDE.md's dates-testing lesson,
  // same underlying trap applied to a plain setTimeout instead of Date).
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  const makeColumns = (save: (item: Row, next: string) => Promise<void>, undoLabel?: string): Column<Row>[] => [
    {
      key: 'cost_basis',
      label: 'Cost',
      render: (r) => <span>${r.cost_basis}</span>,
      edit: { type: 'money', value: (r) => r.cost_basis, save, undoLabel },
    },
  ]

  it('shows a toast after a successful commit on a field with undoLabel', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    render(<DataTable columns={makeColumns(save, 'Cost basis')} data={ROWS} keyField="id" />)
    fireEvent.click(screen.getByText('$10.00'))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '15.00' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(screen.getByText(/Cost basis/)).toBeInTheDocument()
    expect(screen.getByText('Undo')).toBeInTheDocument()
  })

  it('does NOT toast a commit on a field with no undoLabel', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    render(<DataTable columns={makeColumns(save)} data={ROWS} keyField="id" />)
    fireEvent.click(screen.getByText('$10.00'))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '15.00' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(save).toHaveBeenCalled()
    expect(screen.queryByText('Undo')).not.toBeInTheDocument()
  })

  it('Undo re-issues save with the PREVIOUS value', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    render(<DataTable columns={makeColumns(save, 'Cost basis')} data={ROWS} keyField="id" />)
    fireEvent.click(screen.getByText('$10.00'))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '15.00' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(save).toHaveBeenLastCalledWith(ROWS[0], '15')
    await act(async () => {
      fireEvent.click(screen.getByText('Undo'))
    })
    expect(save).toHaveBeenLastCalledWith(ROWS[0], '10.00')
  })

  it('the toast auto-dismisses after 5 seconds', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    render(<DataTable columns={makeColumns(save, 'Cost basis')} data={ROWS} keyField="id" />)
    fireEvent.click(screen.getByText('$10.00'))
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '15.00' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(screen.getByText('Undo')).toBeInTheDocument()
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })
    expect(screen.queryByText('Undo')).not.toBeInTheDocument()
  })

  it('a second edit replaces the toast rather than stacking', async () => {
    const save = vi.fn().mockResolvedValue(undefined)
    const columns: Column<Row>[] = [
      {
        key: 'cost_basis',
        label: 'Cost',
        render: (r) => <span>${r.cost_basis}</span>,
        edit: { type: 'money', value: (r) => r.cost_basis, save, undoLabel: 'Cost basis' },
      },
    ]
    render(<DataTable columns={columns} data={ROWS} keyField="id" />)

    fireEvent.click(screen.getByText('$10.00'))
    let input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '15.00' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    expect(screen.getAllByText('Undo')).toHaveLength(1)

    fireEvent.click(screen.getByText('$2.50'))
    input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '3.00' } })
    await act(async () => {
      fireEvent.keyDown(input, { key: 'Enter' })
    })
    // Still exactly one toast, not two stacked.
    expect(screen.getAllByText('Undo')).toHaveLength(1)
  })
})
