TEX Engine'de çalışmaya devam ediyorsun (repo: travellerbuddha/texengine, temel dal: `claude/inspiring-ptolemy-i6wdu2`). Bu projenin sahibiyim; seninle Türkçe yazışırım.

## Önce durumu kendin kur
Gereksinimleri bana yeniden sorma. Durumu şu sırayla oku:
1. `CLAUDE.md`
2. `docs/tex-engine/HANDOFF.md` (hepsini; özellikle §1, §2, §3, §9 ve §10)
3. `docs/tex-engine/IMPLEMENTATION_STATUS.md` (en son §6 bölümleri: §6O, §6P)
4. `TARGET_ARCHITECTURE.md`
5. `ARCHITECTURE_DECISIONS.md` (ADR-079, ADR-080)
6. `PRODUCT_SPEC.md`
7. `git log` ve PR #33–#36 açıklamaları

Son durum:
- Denetim Part 2 bitti; üye fiyatları (C-04) tamamlandı (2N-1 PR #33, 2N-2 PR #34; ikisi de birleşti).
- 2O partisi (PR #35) birleşti: LOW kalanlar, C-04h ve CLP/ISK.
- 2P partisi, PR #36 (sahip birleştirecek): misafir kimliği ve LOW kalanlar:
  - aynı e-posta adresi aynı misafirdir (büyük/küçük harf fark etmez); aksanlı benzeri başka misafirdir;
  - e-posta tek ve düz bir adres olmalı; değilse rezervasyon kodla reddedilir, kanal rezervasyonu adressiz girer;
  - sepet sorun kodları, "zaten rezerve edildi" uyarısı ve diğer LOW maddeler (§6P).
- Sonraya bırakılan karar: başkası adına rezervasyon (puanı kim kazanır, üye fiyatı kimin, onay e-postası kime gider). Bu parti başlarken bana sorulacak (HANDOFF §2 madde 11).

## İlk adımlar
1. GitHub'da PR #36'nın birleşip birleşmediğine bak. Birleşmediyse önce bana sor. Birleşmemiş bir tabanın üzerinde yeni partiye başlama, PR'ı kendin de birleştirme.
2. Yerel bench'i `docs/tex-engine/DEV_ENVIRONMENT.md`'ye göre kur. Konteyner yeniden başladıysa servisleri o dosyadaki "Cloud containers can restart" bölümüne göre yeniden başlat. Saf birim testlerini ve bir entegrasyon modülünü çalıştırıp ortamın sağlam olduğunu göster.
3. Sonraki partiyi benimle birlikte seç. Seçenekleri HANDOFF §2'den çıkar; her birinin sonucunu sade bir dille yazıp bana sor:
   - D-15: her otelde hangi PMS? (PMS adaptörleri, SMS/WhatsApp, PMS'ten gelen olaylar)
   - Dış taraf bekleyen C maddeleri: C-10, C-14, C-15 (belge veya hesap geldiyse)
   - Başkası adına rezervasyon (HANDOFF §2 madde 11; önce soruları bana sor)
   - Karar gerektirmeyen düşük öncelikli işler (yeni bir LOW partisi: §6* ve §6P "Not done" satırları)

   Cevabımı almadan, karar bekleyen bir işe başlama.

## Çalışma yöntemi (HANDOFF §3)
- Bir parti = bir PR. PR'ı taslak olarak aç, şablonu (`.github/PULL_REQUEST_TEMPLATE.md`) doldur.
- Her maddede:
  - önce kartı bugünkü koda göre yeniden doğrula;
  - başarısız olan testi önce yaz ve kırmızı çıktısını sakla;
  - sonra düzelt;
  - her madde için bir commit at (Conventional Commits).
- Ön yüz değişikliklerinde derlenmiş paketleri de commit et: `cd frontend && npm ci && npm run build`, ardından `git add -A kamra/public`.
- Belgeleri aynı partide güncelle:
  - ilgili ADR'ye ek yaz ya da yeni ADR aç (sıradaki ADR-081);
  - `IMPLEMENTATION_STATUS.md` sonuna yeni bir §6 bölümü ekle (sıradaki §6Q veya partinin adı);
  - HANDOFF, gerekiyorsa SECURITY_MODEL ve MIGRATION_PLAN'ı güncelle;
  - yeni yama gerekiyorsa p79'dan devam et.
- Bağımsız, salt okunur bir inceleyiciyle en çok 2 tur inceleme yap. Bulguları düzelt.
- "Hazır" demeden önce temel dalı fetch et. İlerlemişse MERGE et; asla rebase yapma.
- Son head tamamen yeşil olmalı: CI + Linters + Supply chain. Çalıştırma numaralarını PR'a yaz.
- PR açıklamasında şunlar olsun:
  - madde başına commit, sorun, düzeltme, test ve kırmızı çıktı;
  - inceleme turları;
  - kırıcı değişiklikler / notlar;
  - "Kalanlar";
  - CI ve yerel sayılar.
- Bana kısa bir Türkçe rapor ver ve şu satırla bitir: "PR #N → Ready for review → Merge pull request → Confirm merge".

## Asla yapma
- PR birleştirme, base'e push, rebase veya force-push; test atlama ya da kapatma; boş commit.
- Sır ya da kişisel veri commit etme (repo herkese açık).
- Mevcut bir test assertion'ını değiştirme. Bir kararım bunu gerektiriyorsa PR'da açıkça belirt.
- Playwright çalışırken veritabanı testi (`bench run-tests`) çalıştırma.
- Playwright çalışırken uygulamanın Python dosyalarını düzenleme: `bench serve` yeniden başlar, testler boşuna kırılır.

## Yetkiler ve kararlar
- PR birleştirme yetkisi bende kalır. Birleştirdiğimi söylemeden sonraki partiye geçme.
- D-15 ve diğer açık sorular: ilgili parti gelince bana sor. Cevap gelmeden o işe başlama.
- Bir güvenlik ya da tasarım bulgusu verdiğim bir kararı etkiliyorsa önce bana sor. Seçenekleri ve sonuçlarını sade bir dille yaz.
