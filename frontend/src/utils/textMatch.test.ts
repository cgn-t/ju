import { describe, expect, it } from 'vitest'
import { foldText, includesFolded } from './textMatch'
import { includesTr } from './peopleLabels'

describe('foldText', () => {
  it('Türkçe I/İ/ı ve aksanları yok sayar', () => {
    expect(foldText('ILETISIM')).toBe('iletisim')
    expect(foldText('İLETİŞİM')).toBe('iletisim')
    expect(foldText('ışık')).toBe('isik')
  })
  it('sütun filtresi: "internet" → "İnternet Şubesi", "API" → "api.firma"', () => {
    expect(includesFolded('İnternet Şubesi', 'internet')).toBe(true)
    expect(includesFolded('api.firma.com.tr', 'API')).toBe(true)
    expect(includesFolded('Ödeme', 'kart')).toBe(false)
  })
  it('kişi araması ASCII yazımla da bulur', () => {
    expect(includesTr(['İsmail Çelik'], 'ISMAIL')).toBe(true)
    expect(includesTr(['İsmail Çelik'], 'celik')).toBe(true)
  })
})
