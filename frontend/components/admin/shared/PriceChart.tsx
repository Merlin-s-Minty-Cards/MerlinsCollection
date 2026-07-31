'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import { useAdminApi } from '@/lib/admin-api'

// Register Chart.js components
ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler)

interface PriceChartProps {
  itemId: string
  costBasis?: string
  acquiredAt?: string
}

interface PricePoint {
  date: string
  market_value: string
}

interface BuyMarker {
  date: string
  price: string
}

interface PriceChartData {
  points: PricePoint[]
  buy_marker: BuyMarker | null
  timeframe: string
  item_id: string
}

const TIMEFRAMES = ['1mo', '3mo', '6mo', '1yr', '2yr'] as const
type Timeframe = (typeof TIMEFRAMES)[number]

const TIMEFRAME_LABELS: Record<Timeframe, string> = {
  '1mo': '1M',
  '3mo': '3M',
  '6mo': '6M',
  '1yr': '1Y',
  '2yr': '2Y',
}

/**
 * Price history chart with toggleable timeframes.
 * Fetches data from the price-chart endpoint and renders a Chart.js line graph.
 */
export default function PriceChart({ itemId, costBasis, acquiredAt }: PriceChartProps) {
  const api = useAdminApi()
  const [timeframe, setTimeframe] = useState<Timeframe>('1yr')
  const [chartData, setChartData] = useState<PriceChartData | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchChart = useCallback(async () => {
    if (!api.isAuthenticated || !itemId) return
    setLoading(true)
    try {
      const data = await api.get<PriceChartData>(
        `/inventory/${itemId}/price-chart`,
        { timeframe }
      )
      setChartData(data)
    } catch {
      setChartData(null)
    } finally {
      setLoading(false)
    }
  }, [api, itemId, timeframe])

  useEffect(() => {
    fetchChart()
  }, [fetchChart])

  const { data, options } = useMemo(() => {
    if (!chartData || chartData.points.length === 0) {
      return { data: null, options: null }
    }

    const labels = chartData.points.map((p) => {
      const d = new Date(p.date)
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    })
    const values = chartData.points.map((p) => parseFloat(p.market_value))

    // Build datasets
    const datasets: Array<{
      label: string
      data: (number | null)[]
      borderColor: string
      backgroundColor: string
      pointRadius: number | number[]
      pointBackgroundColor: string | string[]
      pointBorderColor: string | string[]
      borderWidth: number
      tension: number
      fill: boolean
    }> = [
      {
        label: 'Market Value',
        data: values,
        borderColor: '#a9e0b3',
        backgroundColor: 'rgba(169, 224, 179, 0.08)',
        pointRadius: values.map(() => 2),
        pointBackgroundColor: values.map(() => '#a9e0b3'),
        pointBorderColor: values.map(() => '#a9e0b3'),
        borderWidth: 2,
        tension: 0.3,
        fill: true,
      },
    ]

    // Add buy price marker if within range
    if (chartData.buy_marker) {
      const markerDate = chartData.buy_marker.date
      const markerPrice = parseFloat(chartData.buy_marker.price)
      const markerIndex = chartData.points.findIndex((p) => p.date === markerDate)

      if (markerIndex >= 0) {
        // Highlight the buy point on the main line
        const pointRadii = values.map((_, i) => (i === markerIndex ? 6 : 2))
        const pointBgColors = values.map((_, i) =>
          i === markerIndex ? '#f59e0b' : '#a9e0b3'
        )
        const pointBorderColors = values.map((_, i) =>
          i === markerIndex ? '#f59e0b' : '#a9e0b3'
        )
        datasets[0].pointRadius = pointRadii
        datasets[0].pointBackgroundColor = pointBgColors
        datasets[0].pointBorderColor = pointBorderColors
      } else {
        // Buy marker is not in the data range — show as separate annotation point
        // We'll add it as a separate dataset with a single point
        const buyData: (number | null)[] = values.map(() => null)
        // Find the closest date position to insert
        const allDates = chartData.points.map((p) => p.date)
        let insertIdx = allDates.findIndex((d) => d >= markerDate)
        if (insertIdx === -1) insertIdx = allDates.length - 1
        if (insertIdx >= 0 && insertIdx < buyData.length) {
          buyData[insertIdx] = markerPrice
          datasets.push({
            label: 'Buy Price',
            data: buyData,
            borderColor: 'transparent',
            backgroundColor: 'transparent',
            pointRadius: buyData.map((v) => (v !== null ? 7 : 0)),
            pointBackgroundColor: buyData.map((v) => (v !== null ? '#f59e0b' : 'transparent')),
            pointBorderColor: buyData.map((v) => (v !== null ? '#f59e0b' : 'transparent')),
            borderWidth: 0,
            tension: 0,
            fill: false,
          })
        }
      }
    }

    const opts = {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        intersect: false,
        mode: 'index' as const,
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a2e1f',
          titleColor: '#a9e0b3',
          bodyColor: '#e8e4d9',
          borderColor: '#2d5a3a',
          borderWidth: 1,
          padding: 8,
          callbacks: {
            label: (ctx: { dataset: { label: string }; parsed: { y: number } }) => {
              return `${ctx.dataset.label}: $${ctx.parsed.y.toFixed(2)}`
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(45, 90, 58, 0.2)' },
          ticks: {
            color: '#5a7d65',
            maxTicksLimit: 8,
            font: { size: 10 },
          },
        },
        y: {
          grid: { color: 'rgba(45, 90, 58, 0.2)' },
          ticks: {
            color: '#5a7d65',
            font: { size: 10 },
            callback: (value: number | string) => `$${value}`,
          },
        },
      },
    }

    return { data: { labels, datasets }, options: opts }
  }, [chartData])

  return (
    <div className="space-y-2">
      {/* Timeframe toggles */}
      <div className="flex gap-1">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            type="button"
            onClick={() => setTimeframe(tf)}
            className={`px-2 py-1 rounded text-[10px] font-medium transition-colors ${
              timeframe === tf
                ? 'bg-mint/15 text-mint border border-mint/30'
                : 'text-pine-500 hover:text-pine-300 border border-transparent'
            }`}
          >
            {TIMEFRAME_LABELS[tf]}
          </button>
        ))}
      </div>

      {/* Chart */}
      <div className="h-48 rounded-lg bg-pine-800/20 border border-pine-700/20 p-3">
        {loading ? (
          <div className="h-full flex items-center justify-center text-xs text-pine-500">
            Loading chart…
          </div>
        ) : !data || !options ? (
          <div className="h-full flex items-center justify-center text-xs text-pine-600">
            No price history available
          </div>
        ) : (
          <Line data={data} options={options} />
        )}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 text-[10px] text-pine-500">
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-full bg-[#a9e0b3]" />
          Market Value
        </span>
        {chartData?.buy_marker && (
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded-full bg-[#f59e0b]" />
            Buy Price (${parseFloat(chartData.buy_marker.price).toFixed(2)})
          </span>
        )}
      </div>
    </div>
  )
}
