const pptxgen = require('pptxgenjs');
const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE'; // 13.333 x 7.5
pres.title = 'Jumbo AI';
const RED = 'C00000', BAND = 'D9D9D9', LEFT = 'F2F2F2', TXT = '262626', LINE = 'BFBFBF', GREY = '7F7F7F';
const F = 'Calibri';
const s = pres.addSlide();
s.background = { color: 'FFFFFF' };

// Left panel background
s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 6.55, h: 7.5, fill: { color: LEFT }, line: { color: LEFT } });

// Titles
s.addText('Jumbo AI', { x: 0.2, y: 0.28, w: 3, h: 0.45, fontFace: F, fontSize: 24, bold: true, color: RED, margin: 0, isTextBox: true });
s.addShape(pres.shapes.RECTANGLE, { x: 7.74, y: 0.42, w: 5.6, h: 0.52, fill: { color: RED }, line: { color: RED } });
s.addText('Jumbo AI', { x: 7.74, y: 0.42, w: 5.5, h: 0.52, fontFace: F, fontSize: 20, bold: true, color: 'FFFFFF', align: 'right', valign: 'middle', margin: [0, 8, 0, 0], isTextBox: true });

function band(text, x, y, w) {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 0.3, fill: { color: BAND }, line: { color: BAND } });
  s.addText(text, { x: x + 0.08, y, w: w - 0.1, h: 0.3, fontFace: F, fontSize: 13, bold: true, color: RED, valign: 'middle', margin: 0, isTextBox: true });
}
function header(text, x, y, w) {
  s.addText(text, { x, y, w, h: 0.3, fontFace: F, fontSize: 13, bold: true, color: RED, valign: 'bottom', margin: [0, 0, 2, 4], isTextBox: true });
  s.addShape(pres.shapes.LINE, { x, y: y + 0.33, w, h: 0, line: { color: LINE, width: 0.75 } });
}
function bullets(items, opt) {
  const runs = items.map((t, i) => {
    const o = { bullet: { indent: 10 }, breakLine: i < items.length - 1, paraSpaceAfter: 2 };
    if (Array.isArray(t)) return [{ text: t[0], options: { ...o, bold: true, breakLine: false } }, { text: t[1], options: { breakLine: i < items.length - 1 } }];
    return [{ text: t, options: o }];
  }).flat();
  s.addText(runs, { fontFace: F, fontSize: opt.fs || 10, color: TXT, valign: 'top', margin: [2, 4, 2, 4], isTextBox: true, ...opt, fs: undefined });
}

// ---------- LEFT ----------
band('Kapsam', 0.28, 0.95, 6.1);
s.addText('Jumbo Sertifika Takip uygulamasına eklenen, kurum içi AI servisini kullanan soru-cevap asistanı. Kullanıcı sertifika, domain, ekip ve uyum durumunu doğal dille sorar; cevap ilgili kayıtlara bağlantılarla gelir. Kullanım kılavuzu sorularını kurumsal TFS wiki\'den yanıtlar. Asistan yalnızca okur, hiçbir kaydı değiştirmez.',
  { x: 0.28, y: 1.3, w: 6.1, h: 0.85, fontFace: F, fontSize: 10.5, color: TXT, valign: 'top', margin: [2, 6, 2, 6], isTextBox: true });

band('Değer Önerisi / Kazanımlar', 0.28, 2.22, 3.75);
band('Yönetişim', 4.2, 2.22, 2.18);
bullets([
  'Sertifika ve domain bilgisine menü aramadan, tek soruyla erişim',
  'Süresi dolacak sertifikalar, uyum ihlalleri ve ekip özetleri anında',
  'Cevapta kayda giden bağlantı: tek tıkla detay ekranı',
  'Gözden kaçan süre sonu riskleri azalır, kesinti riski düşer',
  'Kılavuz soruları wiki\'den cevaplanır, destek talebi azalır',
  'Yeni kullanıcılar uygulamayı daha hızlı öğrenir',
], { x: 0.28, y: 2.58, w: 3.75, h: 1.75, fs: 10 });
bullets([
  'Kurum içi AI servisi; veri kurum dışına çıkmaz',
  'Salt okur; kayıt eklemez, değiştirmez',
  'E-posta, parola, IP gibi kişisel veriler AI\'a verilmez',
  'Her soru denetim kaydına yazılır',
  'Günlük soru limiti; ayarlar yalnız yöneticide',
  'API anahtarı ve wiki token şifreli saklanır',
], { x: 4.2, y: 2.58, w: 2.18, h: 1.75, fs: 9 });

band('Detay İçerik / Temel Parçaları', 0.28, 4.42, 6.1);
bullets([
  ['Sohbet paneli: ', 'sağ kenardan açılır, sayfayı kapatmaz; Genişlet/Büyüt, açık-koyu tema'],
  ['Hazır sorular: ', 'yöneticinin Ayarlar\'dan düzenlediği en fazla 20 soru'],
  ['Kaynak gösterimi: ', 'her cevabın altında "Baktığı yerler" ve Kopyala'],
  ['Veri araçları: ', 'sertifika/domain sorgusu, izinli tablolarda sorgu (serbest SQL yok), uyum ihlalleri, kayıt geçmişi (yalnız yönetici)'],
  ['Yetki: ', 'tüm veri modu (Genel İzleyici gibi okur) ya da kullanıcının kendi ekip yetkisi; Ayarlar\'dan seçilir'],
  ['Kılavuz: ', 'TFS / Azure DevOps wiki otomatik okunur, 15 dk\'da bir yenilenir'],
  ['Yönetim: ', 'Ayarlar > AI Asistanı (adres, model, anahtar, limit, ek talimat, bağlantı testi)'],
], { x: 0.28, y: 4.78, w: 6.1, h: 2.35, fs: 10 });

s.addText('1', { x: 0.2, y: 7.05, w: 0.3, h: 0.25, fontFace: F, fontSize: 10, bold: true, color: RED, margin: 0, isTextBox: true });

// ---------- RIGHT ----------
header('Teknoloji Çözüm Önerisi', 6.65, 1.1, 6.45);
// Flow diagram
const boxes = [
  ['Kullanıcı', 'Jumbo ekranı\n(AI paneli)'],
  ['Jumbo Backend', 'Python API\nyetki + salt okur araçlar'],
  ['Kurum İçi AI', 'OpenAI uyumlu API\n(Bearer / API-Key)'],
];
const bw = 1.85, bh = 0.7, by = 1.55, gap = 0.45;
boxes.forEach(([t, d], i) => {
  const x = 6.75 + i * (bw + gap);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: by, w: bw, h: bh, rectRadius: 0.06, fill: { color: i === 2 ? RED : 'FFFFFF' }, line: { color: RED, width: 1 } });
  s.addText([{ text: t, options: { bold: true, fontSize: 11, breakLine: true } }, { text: d, options: { fontSize: 9 } }],
    { x, y: by, w: bw, h: bh, fontFace: F, color: i === 2 ? 'FFFFFF' : TXT, align: 'center', valign: 'middle', margin: 2, isTextBox: true });
  if (i < 2) s.addShape(pres.shapes.LINE, { x: x + bw + 0.05, y: by + bh / 2, w: gap - 0.1, h: 0, line: { color: GREY, width: 1.25, beginArrowType: 'triangle', endArrowType: 'triangle' } });
});
// Data sources under backend
const sx = 6.75 + (bw + gap);
s.addShape(pres.shapes.LINE, { x: sx + bw / 2, y: by + bh, w: 0, h: 0.2, line: { color: GREY, width: 1.25, endArrowType: 'triangle' } });
[['Jumbo MSSQL', 'mevcut tablolar'], ['TFS Wiki', 'kullanım kılavuzu']].forEach(([t, d], i) => {
  const x = sx - 0.55 + i * 1.55;
  s.addShape(pres.shapes.RECTANGLE, { x, y: by + bh + 0.22, w: 1.45, h: 0.45, fill: { color: BAND }, line: { color: BAND } });
  s.addText([{ text: t, options: { bold: true, fontSize: 10, breakLine: true } }, { text: d, options: { fontSize: 8.5 } }],
    { x, y: by + bh + 0.22, w: 1.45, h: 0.45, fontFace: F, color: TXT, align: 'center', valign: 'middle', margin: 1, isTextBox: true });
});
bullets([
  ['Arayüz: ', 'React / Vite; Jumbo içinde yan panel, ayrı uygulama yok'],
  ['Backend: ', 'Python servisi; model, araç çağırma (tool calling) ile veriyi kullanıcı adına okur'],
  ['Model: ', 'kurum içi AI servisi; adres, model ve anahtar Ayarlar\'dan değişir'],
  ['Veri ve ortam: ', 'mevcut MSSQL ve OpenShift; yeni tablo, sunucu ya da imaj gerekmez'],
], { x: 6.65, y: 3.0, w: 6.45, h: 1.08, fs: 10 });

header('Entegrasyon Konuları', 6.62, 4.12, 3.5);
bullets([
  'Kurum içi AI servisi: adres, model, API anahtarı; canlı ortam testi',
  'TFS wiki: PAT ile okuma (REST 6.0 / 5.0 / 4.1)',
  'Gerekirse kurum proxy ayarı',
  'Mevcut AD girişi ve Jumbo ekip yetkileri',
], { x: 6.62, y: 4.51, w: 3.5, h: 1.3, fs: 9.5 });

header('Riskler', 6.62, 5.82, 3.5);
bullets([
  'Model hatalı/eksik cevap verebilir; kayıt bağlantısıyla doğrulanır',
  'AI servisi kapalıysa asistan çalışmaz, uygulama etkilenmez',
  'Wiki güncel tutulmazsa kılavuz cevapları eskir',
  'Tüm veri modunda diğer ekiplerin verisi görülebilir',
], { x: 6.62, y: 6.2, w: 3.5, h: 1.15, fs: 9.5 });

// Maliyetler
header('Maliyetler ve Yatırım', 10.36, 4.12, 2.75);
const rows = [['Proje Büyüklüğü', 'Küçük'], ['Yatırım Maliyeti (TL)', '……'], ['İşletim Maliyeti (TL)', '……']];
rows.forEach(([l, v], i) => {
  const y = 4.5 + i * 0.36;
  s.addText(l, { x: 10.36, y, w: 1.75, h: 0.33, fontFace: F, fontSize: 10.5, color: TXT, valign: 'middle', margin: [0, 0, 0, 4], isTextBox: true });
  s.addText(v, { x: 12.1, y, w: 1.0, h: 0.33, fontFace: F, fontSize: 10.5, bold: true, color: TXT, align: 'right', valign: 'middle', margin: [0, 4, 0, 0], isTextBox: true });
  s.addShape(pres.shapes.LINE, { x: 10.36, y: y + 0.34, w: 2.75, h: 0, line: { color: LINE, width: 0.75 } });
});

// Veri kaynağı
header('Veri Kaynağı', 10.6, 5.82, 2.0);
[['Yapılandırılmış', 'X'], ['Yapılandırılmamış', 'X']].forEach(([l, v], i) => {
  const y = 6.2 + i * 0.36;
  s.addText(l, { x: 10.6, y, w: 1.6, h: 0.33, fontFace: F, fontSize: 10.5, color: TXT, valign: 'middle', margin: [0, 0, 0, 4], isTextBox: true });
  s.addText(v, { x: 12.2, y, w: 0.4, h: 0.33, fontFace: F, fontSize: 11, bold: true, color: TXT, align: 'center', valign: 'middle', margin: 0, isTextBox: true });
  s.addShape(pres.shapes.LINE, { x: 10.6, y: y + 0.34, w: 2.0, h: 0, line: { color: LINE, width: 0.75 } });
});
s.addText('MSSQL kayıtları / TFS wiki sayfaları', { x: 10.6, y: 6.94, w: 2.6, h: 0.25, fontFace: F, fontSize: 8.5, italic: true, color: GREY, margin: [0, 0, 0, 4], isTextBox: true });

s.addNotes('Yatırım ve işletim maliyeti (TL) alanları boş bırakıldı; kurum içi AI servisinin kullanım bedeli ve efor bilgisine göre doldurulmalı.');

pres.writeFile({ fileName: 'jumbo-ai-sunum.pptx' }).then(() => console.log('written'));
