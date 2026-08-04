import { describe, it, expect } from 'vitest'
import {
  CONDITION_OPTIONS,
  LOCATION_OPTIONS,
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
