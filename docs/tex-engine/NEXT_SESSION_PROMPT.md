TEX Engine'de çalışmaya devam ediyorsun (repo: travellerbuddha/texengine, temel dal: `claude/inspiring-ptolemy-i6wdu2`). Bu projenin sahibiyim; seninle Türkçe yazışırım.

## Önce durumu kendin kur
Gereksinimleri bana yeniden sorma. Durumu şu sırayla oku:
1. `CLAUDE.md`
2. `docs/tex-engine/HANDOFF.md` (hepsini; özellikle §1, §2, §3, §9 ve §10)
3. `docs/tex-engine/IMPLEMENTATION_STATUS.md` (en son §6 bölümleri: §6P, §6Q)
4. `TARGET_ARCHITECTURE.md`
5. `ARCHITECTURE_DECISIONS.md` (ADR-080, ADR-081)
6. `PRODUCT_SPEC.md`
7. `git log` ve PR #34–#37 açıklamaları

Son durum:
- Denetim Part 2 bitti; üye fiyatları (C-04) tamamlandı (2N-1 PR #33, 2N-2 PR #34; ikisi de birleşti).
- 2O (PR #35) ve 2P (PR #36) birleşti: LOW kalanlar, C-04h, CLP/ISK ve misafir kimliği (aynı e-posta adresi aynı misafirdir).
- 2Q partisi, PR #37 (sahip birleştirecek): karar gerektirmeyen tüm LOW kalanlar (§6Q, ADR-081):
  - misafir e-postası her kayıt yolunda tek düz adres (Desk, REST, eski PMS yolları, ön check-in);
  - başkası adına rezervasyon: girilen e-posta adresi her şeyi belirler (onay e-postası, profil, puan, üye fiyatı); bugünkü davranış, kayda geçti;
  - depozito payı, fiyat uyarısı, ekstra ret kodları, üyelik engeli, bağlantı yarışları ve diğer maddeler.
- Bekleyen sahip soruları (o iş başlarken bana sor, HANDOFF §2):
  - madde 12: "geçersiz sepet" uyarısındaki "Tekrar dene" (LO-14 e2e testi değişir);
  - madde 14–21: Türkçe-F kısayolları, etiketsiz kanal adı, çağrı merkezinde promosyon kodundaki boşluk, grup programı ile otel programı çakışması, geleceğe taşınan konaklamanın puanları, eski MCP kaydında hız sınırı, kontrast ölçümü, silme sonrası hata kaydının kalıcı olması (her biri mevcut bir testi ya da bir kuralı değiştirir).
- Para partisi (madde 13): mükerrer tahsilat, inceleme sürerken yeni ödeme, LO-09 profil yarışı.

## İlk adımlar
1. GitHub'da PR #37'nin birleşip birleşmediğine bak. Birleşmediyse önce bana sor. Birleşmemiş bir tabanın üzerinde yeni partiye başlama, PR'ı kendin de birleştirme.
2. Yerel bench'i `docs/tex-engine/DEV_ENVIRONMENT.md`'ye göre kur. Konteyner yeniden başladıysa servisleri o dosyadaki "Cloud containers can restart" bölümüne göre yeniden başlat. Saf birim testlerini ve bir entegrasyon modülünü çalıştırıp ortamın sağlam olduğunu göster.
3. Sonraki partiyi benimle birlikte seç. Seçenekleri HANDOFF §2'den çıkar; her birinin sonucunu sade bir dille yazıp bana sor:
   - D-15: her otelde hangi PMS? (PMS adaptörleri, SMS/WhatsApp, PMS'ten gelen olaylar)
   - Dış taraf bekleyen C maddeleri: C-10, C-14, C-15 (belge veya hesap geldiyse)
   - Para partisi (HANDOFF §2 madde 13)
   - Sahip soruları (HANDOFF §2 madde 12 ve 14–21; önce soruları bana sor)

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
  - ilgili ADR'ye ek yaz ya da yeni ADR aç (sıradaki ADR-082);
  - `IMPLEMENTATION_STATUS.md` sonuna yeni bir §6 bölümü ekle (sıradaki §6R veya partinin adı);
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
