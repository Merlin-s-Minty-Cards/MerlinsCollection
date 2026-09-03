/**
 * Pure logic — no DOM. Runs in `node` rather than the default jsdom:
 * constructing a jsdom per file was the single largest cost in this
 * suite (215s cumulative `environment` time against 55s of actual tests).
 * If this file ever renders a component or touches window/document,
 * delete this docblock rather than stubbing the DOM by hand.
 *
 * @vitest-environment node
 */
import { describe, it, expect } from 'vitest'
import {
  CONDITION_OPTIONS,
  LOCATION_OPTIONS,
  PRICED_FINISHES,
  FINISH_ATTRIBUTE_SUGGESTIONS,
  LANGUAGE_OPTIONS,
  parseCondition,
  formatCondition,
} from '../constants'

describe('parseCondition', () => {
  it('parses plain condition without modifier', () => {
    expect(parseCondition('NM')).toEqual({ condition: 'NM', condition_modifier: null })
    expect(parseCondition('LP')).toEqual({ condition: 'LP', condition_modifier: null })
    expect(parseCondition('MP')).toEqual({ condition: 'MP', condition_modifier: null })
    expect(parseCondition('HP')).toEqual({ condition: 'HP', condition_modifier: null })
    expect(parseCondition('DMG')).toEqual({ condition: 'DMG', condition_modifier: null })
  })

  it('parses condition with plus modifier', () => {
    expect(parseCondition('LP+')).toEqual({ condition: 'LP', condition_modifier: '+' })
    expect(parseCondition('NM+')).toEqual({ condition: 'NM', condition_modifier: '+' })
  })

  it('parses condition with minus modifier', () => {
    expect(parseCondition('LP-')).toEqual({ condition: 'LP', condition_modifier: '-' })
    expect(parseCondition('NM-')).toEqual({ condition: 'NM', condition_modifier: '-' })
  })
})

describe('formatCondition', () => {
  it('formats condition with no modifier', () => {
    expect(formatCondition('LP', null)).toBe('LP')
    expect(formatCondition('NM', undefined)).toBe('NM')
  })

  it('formats condition with modifier', () => {
    expect(formatCondition('LP', '+')).toBe('LP+')
    expect(formatCondition('LP', '-')).toBe('LP-')
  })
})

describe('CONDITION_OPTIONS', () => {
  it('includes LP+ and LP-', () => {
    expect(CONDITION_OPTIONS).toContain('LP+')
    expect(CONDITION_OPTIONS).toContain('LP-')
  })

  it('includes all base conditions', () => {
    expect(CONDITION_OPTIONS).toContain('NM')
    expect(CONDITION_OPTIONS).toContain('LP')
    expect(CONDITION_OPTIONS).toContain('MP')
    expect(CONDITION_OPTIONS).toContain('HP')
    expect(CONDITION_OPTIONS).toContain('DMG')
  })

  it('has LP+ before LP and LP- after LP', () => {
    const lpPlusIdx = CONDITION_OPTIONS.indexOf('LP+')
    const lpIdx = CONDITION_OPTIONS.indexOf('LP')
    const lpMinusIdx = CONDITION_OPTIONS.indexOf('LP-')
    expect(lpPlusIdx).toBeLessThan(lpIdx)
    expect(lpIdx).toBeLessThan(lpMinusIdx)
  })
})

describe('PRICED_FINISHES', () => {
  // RFC 0023 T4/T5 — measured from the live catalog 2026-09-02, not typed.
  // Mirrors the backend's `PRICED_FINISHES` tuple in models/inventory.py
  // character for character; a drift here is exactly the class of bug that
  // motivated this measurement (the frontend used to offer
  // `firstEditionHolofoil`, which is in neither list).
  it('matches the measured backend union exactly', () => {
    expect(new Set(PRICED_FINISHES)).toEqual(new Set([
      'normal', 'holofoil', 'reverseHolofoil',
      '1stEdition', 'unlimited', 'unlimitedHolofoil',
      '1stEditionHolofoil', '1stEditionNormal',
    ]))
  })

  it('has no duplicates', () => {
    expect(PRICED_FINISHES.length).toBe(new Set(PRICED_FINISHES).size)
  })

  it('does not contain the old, never-priced firstEditionHolofoil spelling', () => {
    // The live bug this whole task exists to fix: `IncomingCardForm.tsx`
    // offered `firstEditionHolofoil`, camelCase but capitalized differently
    // from the real `1stEditionHolofoil` key, so it silently mispriced.
    expect(PRICED_FINISHES).not.toContain('firstEditionHolofoil')
  })
})

describe('FINISH_ATTRIBUTE_SUGGESTIONS', () => {
  it('is a non-empty list of suggested, not enforced, tags', () => {
    expect(FINISH_ATTRIBUTE_SUGGESTIONS.length).toBeGreaterThan(0)
  })

  it('includes the tags RFC 0023 §2.2 names by example', () => {
    for (const tag of ['1st Edition', 'Shadowless', 'Full Art', 'Signed']) {
      expect(FINISH_ATTRIBUTE_SUGGESTIONS).toContain(tag)
    }
  })

  it('has no duplicates', () => {
    expect(FINISH_ATTRIBUTE_SUGGESTIONS.length).toBe(new Set(FINISH_ATTRIBUTE_SUGGESTIONS).size)
  })

  it('every suggestion fits the backend 40-character bound', () => {
    for (const tag of FINISH_ATTRIBUTE_SUGGESTIONS) {
      expect(tag.length).toBeLessThanOrEqual(40)
    }
  })
})

describe('LANGUAGE_OPTIONS', () => {
  // RFC 0023 T1/T3 — mirrors backend `LANGUAGE_LABELS` (models/inventory.py)
  // exactly: 18 real TCGdex codes + OTHER, 19 total.
  it('has all 19 members, EN and JP included', () => {
    const values = LANGUAGE_OPTIONS.map((o) => o.value)
    expect(values.length).toBe(19)
    expect(values).toContain('EN')
    expect(values).toContain('JP')
    expect(values).toContain('OTHER')
  })

  it('has no duplicates', () => {
    const values = LANGUAGE_OPTIONS.map((o) => o.value)
    expect(values.length).toBe(new Set(values).size)
  })

  it('each entry has a value and a real label, not the bare code repeated', () => {
    for (const opt of LANGUAGE_OPTIONS) {
      expect(opt.value).toBeTruthy()
      expect(opt.label).toBeTruthy()
    }
    const jp = LANGUAGE_OPTIONS.find((o) => o.value === 'JP')
    expect(jp?.label).toBe('Japanese')
    const other = LANGUAGE_OPTIONS.find((o) => o.value === 'OTHER')
    expect(other?.label).toBe('Other / unsupported')
  })

  it('includes the hyphenated codes verbatim (zh-tw, es-mx, pt-br, pt-pt)', () => {
    const values = LANGUAGE_OPTIONS.map((o) => o.value)
    expect(values).toContain('ZH-TW')
    expect(values).toContain('ES-MX')
    expect(values).toContain('PT-BR')
    expect(values).toContain('PT-PT')
  })
})

describe('LOCATION_OPTIONS', () => {
  it('has required base locations', () => {
    const values = LOCATION_OPTIONS.map((o) => o.value)
    expect(values).toContain('glass')
    expect(values).toContain('toploader')
    expect(values).toContain('binder')
    expect(values).toContain('storage')
  })

  it('has new show-related locations', () => {
    const values = LOCATION_OPTIONS.map((o) => o.value)
    expect(values).toContain('show_box_a')
    expect(values).toContain('show_box_b')
  })

  it('each entry has value and label', () => {
    for (const opt of LOCATION_OPTIONS) {
      expect(opt.value).toBeTruthy()
      expect(opt.label).toBeTruthy()
    }
  })
})
