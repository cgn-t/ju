/**
 * Arama/filtre için metin katlama: büyük/küçük harf ve Türkçe karakter farkını yok sayar.
 * "ILETISIM", "iletişim", "İLETİŞİM" → "iletisim". Düz toLowerCase() 'İ'yi 'i̇' yapar,
 * tr-TR ise 'I'yı 'ı' yapar; ikisi de ASCII yazılmış domain/ad aramalarını kaçırır.
 * Sunucu tarafındaki arama (MSSQL Latin1_General_CI_AI) ile aynı davranır.
 */
export function foldText(text: string | null | undefined): string {
  return (text ?? '')
    .replace(/[İIı]/g, 'i')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
}

/** `haystack` içinde `needle` geçiyor mu (harf ve Türkçe karakter duyarsız). */
export function includesFolded(haystack: string | null | undefined, needle: string): boolean {
  return foldText(haystack).includes(foldText(needle))
}
