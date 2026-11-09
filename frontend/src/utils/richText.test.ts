import { describe, expect, it } from 'vitest'
import { colorKey, domToRich, parseRich, richToEditorHtml, richToPlain } from './richText'

const dom = (html: string) => { const d = document.createElement('div'); d.innerHTML = html; return d }

describe('richText', () => {
  it('etiketleri ayrıştırır, bozuk etiketleri metin bırakır', () => {
    expect(parseRich('a [b]k[/b]')).toEqual([{ kind: 'text', text: 'a ' }, { kind: 'mark', mark: 'b', children: [{ kind: 'text', text: 'k' }] }])
    expect(richToPlain('[renk=zehir]x[/renk] [/i] [b]açık')).toBe('[renk=zehir]x[/renk] [/i] açık')
    expect(richToPlain('[i]a[/i]\n[renk=mavi]b[/renk]')).toBe('a\nb')
  })
  it('düzenleyici HTML kaçışlıdır', () => {
    expect(richToEditorHtml('<img src=x onerror=1> [b]k[/b]\n2')).toBe('&lt;img src=x onerror=1&gt; <b>k</b><br>2')
    expect(richToEditorHtml('[renk=kirmizi]r[/renk]')).toBe('<font color="#c62828">r</font>')
  })
  it('düzenleyici DOM\'u geri etiketli metne çevrilir (gidiş-dönüş)', () => {
    const src = 'Satır 1 [b]kalın[/b]\n[renk=kirmizi][i]kırmızı italik[/i][/renk]\n\nson [u]alt[/u]'
    expect(domToRich(dom(richToEditorHtml(src)))).toBe(src)
  })
  it('tarayıcının Enter ile eklediği div\'ler satır olur; yabancı etiketler atılır', () => {
    expect(domToRich(dom('ilk<div>ikinci</div><div><br></div><div>dördüncü</div>'))).toBe('ilk\nikinci\n\ndördüncü')
    expect(domToRich(dom('<span style="color: rgb(198, 40, 40); font-weight: bold">x</span><script>y</script><a href="z">w</a>')))
      .toBe('[b][renk=kirmizi]x[/renk][/b]w')
    expect(colorKey('rgb(144, 202, 249)')).toBe('mavi')
    expect(colorKey('#123456')).toBeNull()
  })
})
