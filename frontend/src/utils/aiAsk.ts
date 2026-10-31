// Sayfalardan Jumbo AI panelini bir soruyla açmak için (ör. Regresyon Testi'ndeki "AI'a sor").
// AiAssistant bu olayı dinler: paneli açar, yeni bir sohbet başlatıp soruyu gönderir.
export const AI_ASK_EVENT = 'jumbo-ai-ask'

export function askAi(question: string) {
  window.dispatchEvent(new CustomEvent<string>(AI_ASK_EVENT, { detail: question }))
}
