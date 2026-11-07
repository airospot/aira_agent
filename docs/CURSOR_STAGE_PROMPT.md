# Cursor için aşama uygulama talimatı

Aşağıdaki prompt başlangıçta yalnız A00 için kullanılır. Sonraki aşamalarda aşama kodu ve kabul edilmiş başlangıç SHA’sı açıkça değiştirilir. Planın tamamı tek seferde çalıştırılmaz.

```text
Bu depoda docs/AGENT_EVOLUTION_PLAN.md ve docs/UAT_CHECKPOINTS.md dosyalarını oku.

Yalnız A00 aşamasını uygula. Mevcut başlangıç commit’i
99de9f400c48f422348aae4af2d9025b68a7ff27.
HEAD farklıysa önce farkı ve ilgili çalışma ağacını incele; kabul edilmemiş başka
bir aşamayı varsayma, hiçbir kullanıcı değişikliğini silme.

Plan dosyaları bu çalışma için hazırlanmış yeni depo dokümanlarıdır; başlangıçta
untracked olmaları normaldir. Bu üç dokümanı A00 teslimine dahil et. Bunun dışındaki
ilgisiz dosyaları stage etme. Varsa AGENTS.md talimatlarını uygula.

Amaç mevcut hardening commit’ini yeniden yazmak değil; davranışını anlamlı
regresyon testleriyle doğrulamak, kanıtlanan kusurları kapsam içinde düzeltmek
ve kurulum/UAT adımlarını çalışır hale getirmektir. Testleri geçsin diye çalışan
güvenlik kontrollerini kaldırma. Gerçek LLM çağrısı unit testlerde yapılmasın.
Gerçek PostgreSQL yarış/migration testlerini ayrı test DB’sinde çalıştır; erişim
yoksa eksik doğrulamayı açık bildir, mock sonucunu gerçek DB testi diye yazma.

Mevcut kabul edilmiş tabandan codex/agent-a00-baseline-checks dalını aç.
Gerekli testleri çalıştır, yalnız ilgili değişiklikleri commit et, dalı GitHub’a
push et ve draft PR aç. main’e doğrudan push etme, merge etme, force push yapma.
Push/PR yetkisi eksikse bunu bildir; gerçekleşmiş gibi raporlama.

Teslimde şunları ver:
1. Başlangıç SHA, son SHA, GitHub dalı ve draft PR URL’si.
2. Somut değişiklikler ve kapsam içindeki düzeltilmiş kusurlar.
3. Çalıştırılan test komutları/sonuçları; yapılamayan testler ve nedenleri.
4. Benim tarayıcıda uygulayacağım A00 UAT adımları ve beklenen sonuçlar.
5. Migration/başlatma komutları; gerçek secret içermeyen örnekler.
6. Bilinen sınırlar ve veri kaybetmeyen geri dönüş açıklaması.

docs/UAT_CHECKPOINTS.md içinde A00 teknik kaydını doldur; manuel UAT ve dış
inceleme durumlarını BEKLEMEDE bırak. Başkasının yerine PASS yazma.
Uygulama commit SHA’sını PR/teslimde ver; commit içine kendi SHA’sını yazmak
için sonsuz amend döngüsü oluşturma.

A00 tesliminden sonra DUR. A01’i başlatma. Bu sohbetten yapılacak kod incelemesi
ve benim kesin SHA için manuel UAT kabulüm gelmeden sonraki aşamaya geçme.
```

## Sonraki aşama için devam şablonu

```text
Önceki aşama <Axx>, <SHA> için kod incelemesi ve manuel UAT kabul edildi;
PR birleştirildi. Yeni kabul edilmiş başlangıç commit’i: <MERGED_SHA>.
docs/AGENT_EVOLUTION_PLAN.md içinden yalnız <Ayy> aşamasını uygula.
Yeni codex/agent-<ayy>-<konu> dalında çalış; önceki teslim/test/commit/push/draft-PR
ve DUR kurallarını aynen uygula. Manuel UAT ve dış incelemeyi beklemede bırak.
```
