<p align="center">
  <img src="frontend/public/tex-mark.svg" width="96" alt="TEX Engine" />
</p>

<h1 align="center">TEX Engine</h1>

<p align="center">
  <b>Oteller ve otel grupları için ticari yönetim ve merkezi rezervasyon platformu.</b><br />
  Sözleşmeler, fiyatlandırma, envanter, rezervasyon, çağrı merkezi, CRM ve ödemeler.
</p>

<p align="center">
  <a href="#yerelde-çalıştırma">Yerel kurulum</a> ·
  <a href="docs/tex-engine/IMPLEMENTATION_STATUS.md">Geliştirme durumu</a> ·
  <a href="docs/tex-engine/PRODUCT_SPEC.md">Ürün kapsamı</a> ·
  <a href="https://github.com/travellerbuddha/TexEngine/issues">Hata ve öneriler</a> ·
  <a href="license.txt">AGPL-3.0</a>
</p>

**TEX Engine**, otelin sözleşmeden satışa uzanan ticari akışını tek platformda yönetmek için geliştiriliyor. Otel ve otel grubu bazında fiyat kurallarını tanımlar; misafir rezervasyon motoru, merkezi rezervasyon sistemi (CRS) ve çağrı merkezi aynı fiyatlandırma ve rezervasyon servislerini kullanır.

Projenin kaynak deposu: **[travellerbuddha/TexEngine](https://github.com/travellerbuddha/TexEngine)**.

## Neler yapar?

| Alan | İşlevler |
| --- | --- |
| **Sözleşmeler** | Otel ve pazar bazında sözleşmeler, fiyat dönemleri, taslak düzenleme, doğrulama, yayınlama ve sürüm geçmişi. |
| **Fiyatlandırma** | Oda ve kişi bazlı fiyatlar, yetişkin/çocuk kuralları, yaş bantları, döviz politikaları, satış marjları, promosyonlar ve ek hizmetler. |
| **Envanter ve kısıtlamalar** | Kontenjanlar, müsaitlik, satışa kapatma, konaklama kısıtlamaları ve toplu fiyat/envanter düzenleme. |
| **CRS ve çağrı merkezi** | Tek veya çok odalı teklif ve rezervasyon, klavye odaklı satış akışı, ödeme bağlantıları ve rezervasyon değişiklikleri. |
| **Misafir rezervasyon motoru** | Tarih ve kişi seçimi, oda/fiyat sonuçları, ek hizmetler, misafir bilgileri, ödeme ve onay akışı. |
| **Misafir işlemleri** | Rezervasyonu görüntüleme, değişiklik ve iptal talepleri, ödeme ve rezervasyon sonrası ek hizmetler. |
| **CRM ve sadakat** | Misafir profilleri, iletişim izinleri, segmentler, terk edilen rezervasyonlar ve sadakat puanları. |
| **Ödemeler** | Test ödeme akışları, sağlayıcı entegrasyonları, ödeme bağlantıları, iade ve ödeme mutabakatı. |
| **Raporlama** | Rezervasyon üretimi, sözleşme maliyeti/satış fiyatı, marj, ödeme, iptal, promosyon ve dönüşüm raporları. |
| **TEX Connect** | PMS ve kanal bağlantıları için adaptörler, gönderim kuyrukları, tekrar deneme ve sistem durumu takibi. |

Bu tablo ürün alanlarını özetler. Her alt özelliğin tamamlanma durumu [geliştirme durum belgesinde](docs/tex-engine/IMPLEMENTATION_STATUS.md) takip edilir.

## Temel yaklaşım

- **Tek fiyatlandırma kaynağı:** Web rezervasyon motoru, CRS ve çağrı merkezi aynı ticari kuralları kullanır.
- **Deterministik hesaplama:** Para ve fiyat kuralları `Decimal` ile hesaplanır; fiyat kararlarını bir yapay zekâ modeli vermez.
- **Yayınlanmış sözleşme sürümleri:** Satışın dayandığı kurallar ve sürüm bilgisi kaydedilir.
- **Rezervasyon fiyat kilidi:** Sonradan yapılan sözleşme düzenlemeleri satılmış rezervasyonun fiyatını değiştirmez. Değişiklikler ayrı fiyatlama ve revizyon akışından geçer.
- **Otel bazında yetki:** Kullanıcıların erişimi işletme, otel grubu ve otel kapsamındaki yetkilerle sınırlandırılır.
- **İşlem geçmişi:** Ticari değişiklikler, ödeme sonuçları ve yetkili işlemler denetim kaydına yazılır.

## Geliştirme durumu

TEX Engine **aktif geliştirme aşamasındadır**. Yerel demo ortamında sözleşme, fiyatlandırma, rezervasyon, test ödemesi ve rezervasyon değişikliği akışları kullanılabilir.

Gerçek ödeme ve kanal sağlayıcılarının doğrulanması ile canlı ortam hazırlıkları ayrıca takip edilir. Güncel kapsam ve açık işler için:

- [Uygulama durumu](docs/tex-engine/IMPLEMENTATION_STATUS.md)
- [Ürün gereksinimleri](docs/tex-engine/PRODUCT_SPEC.md)
- [Canlıya geçiş hazırlıkları](docs/tex-engine/GO_LIVE_READINESS.md)

## Yerelde çalıştırma

En kolay başlangıç, depo içindeki **Docker demo kurulumudur**. Windows ve macOS'ta Docker Desktop; Linux'ta Docker Engine ve Compose eklentisi gerekir.

```bash
git clone https://github.com/travellerbuddha/TexEngine.git
cd TexEngine/deploy/tex-local
docker compose up -d --build
```

İlk çalıştırmada uygulama imajı derlenir, veritabanı oluşturulur ve demo verileri yüklenir. İlerlemeyi ve servis durumunu görmek için:

```bash
docker compose logs -f tex
docker compose ps
```

`tex` servisi **healthy** olduğunda tarayıcıda açılabilecek adresler:

| Ekran | Yerel adres |
| --- | --- |
| TEX personel uygulaması | `http://localhost:8000/kamra/tex` |
| Misafir rezervasyon motoru | `http://localhost:8000/book/aurora` |
| Yönetim ekranı | `http://localhost:8000/desk` |

### Demo kullanıcıları

Demo personel hesaplarının ortak şifresi: **`TexDemo#2026`**.

| Kullanıcı | Rol |
| --- | --- |
| `revenue@demo.tex` | Otel grubu gelir yönetimi |
| `agent@demo.tex` | Çağrı merkezi ve rezervasyon |
| `finance@demo.tex` | Finans |
| `beach.gm@demo.tex` | Aurora Beach Resort otel yöneticisi |

Yönetici hesabı: `Administrator` / `admin`.

Bu kurulum demo verileri ve test ödeme sayfası kullanır; gerçek kart veya misafir verisi gerektirmez. Varsayılan şifreler herkese açık olduğu için ortamı kendi bilgisayarında test amacıyla kullan.

Durdurmak ve tekrar açmak için, aynı klasörde:

```bash
docker compose stop
docker compose up -d
```

Ayarlar, sorun giderme ve güncelleme adımları: [Docker kurulum rehberi](deploy/tex-local/README.md). Docker kullanmadan kurulum: [native kurulum rehberi](deploy/tex-local/NATIVE.md).

### Güncel arayüzle geliştirme

Frappe sunucusu `8000` portunda çalışırken, **Node.js 24** ile ikinci bir terminalde:

```bash
cd TexEngine/frontend
npm ci
```

macOS / Linux:

```bash
KAMRA_API_HOST=tex.localhost KAMRA_API_TARGET=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --strictPort
```

Windows PowerShell:

```powershell
$env:KAMRA_API_HOST = 'tex.localhost'
$env:KAMRA_API_TARGET = 'http://127.0.0.1:8000'
npm run dev -- --host 127.0.0.1 --strictPort
```

Vite üzerinden personel ekranı `http://localhost:5173/tex`, misafir ekranı `http://localhost:5173/book/aurora` adresindedir. Bu akış arayüz kaynak kodundaki değişiklikleri doğrudan gösterir; `8000` portundaki sunucu depoya kaydedilmiş hazır arayüz paketlerini kullanır.

## Geliştiriciler için

| Katman | Teknoloji |
| --- | --- |
| Backend | Python 3.14, Frappe v16.25.0 |
| Arayüz | React 19, TypeScript, Vite, Tailwind CSS |
| JavaScript çalışma ortamı | Node.js 24, Yarn 1 |
| Veritabanı | MariaDB; yerel Docker kurulumu 11.8 kullanır |
| Önbellek ve iş kuyruğu | Redis, Frappe arka plan işleri |
| Testler | Python birim/entegrasyon testleri, Node.js birim testleri, Playwright |

### Testler

Frontend klasöründe:

```bash
cd frontend
npm run test:unit
npm run i18n:tex
```

Arayüzün tip kontrolü ve derlemesi; çıktılar depo dışına yazılır:

```bash
npx tsc -b
npx vite build --outDir ../../tex-build/frontend
npx vite build -c vite.widget.config.ts --outDir ../../tex-build/widget
```

Ön yüz kaynağını değiştiren bir PR, `frontend/` içinde `npm ci && npm run build` çalıştırıp `kamra/public/frontend` ve `kamra/public/tex` altındaki derlenmiş dosyaları da commit eder: CI, commit edilen dosyaların kaynağın taze bir derlemesiyle aynı olduğunu denetler (ADR-073).

Backend testleri kurulu bir Frappe bench'in Python ortamında çalıştırılır. Bench klasöründen:

```bash
./env/bin/python -m pytest apps/kamra/kamra/tex/tests/unit -q
bench --site tex.localhost run-tests --module kamra.tex.tests.integration.test_critical_journey
```

Test sitesinde `allow_tests` açık olmalıdır. Tarayıcı testleri, demo verisi ve diğer entegrasyon testleri için [geliştirme ortamı rehberine](docs/tex-engine/DEV_ENVIRONMENT.md) bak.

## Proje dokümantasyonu

| Belge | İçerik |
| --- | --- |
| [Ürün kapsamı](docs/tex-engine/PRODUCT_SPEC.md) | İşlevler ve kabul kriterleri |
| [Geliştirme durumu](docs/tex-engine/IMPLEMENTATION_STATUS.md) | Tamamlanan, kısmi ve açık maddeler |
| [Hedef mimari](docs/tex-engine/TARGET_ARCHITECTURE.md) | Servisler ve sistem sınırları |
| [Mimari kararlar](docs/tex-engine/ARCHITECTURE_DECISIONS.md) | Tasarım kararları ve gerekçeleri |
| [Fiyatlandırma çalışma alanı](docs/tex-engine/PRICING_WORKSPACE_UX.md) | Sözleşme ve fiyat yönetimi arayüzü |
| [Geliştirme ortamı](docs/tex-engine/DEV_ENVIRONMENT.md) | Araçlar, testler ve demo verisi |
| [Migration planı](docs/tex-engine/MIGRATION_PLAN.md) | Şema ve veri geçişleri |
| [Güvenlik](SECURITY.md) | Güvenlik politikası |

Hata ve önerileri [bu deponun Issues bölümünde](https://github.com/travellerbuddha/TexEngine/issues) takip edebilirsin.

## Lisans ve kaynak atfı

TEX Engine, **[GNU Affero General Public License v3.0](license.txt)** kapsamında dağıtılır.

Projenin başlangıç kodu [Kamra PMS](https://github.com/Kamra-PMS/kamra-pms) kaynaklarına dayanır. Orijinal telif hakları ve kaynak atıfları korunur; ayrıntılar [NOTICE.md](NOTICE.md) ve [upstream başlangıç kaydında](docs/tex-engine/UPSTREAM_BASELINE.md) yer alır. Değiştirilmiş yazılımı ağ üzerinden sunarken kullanıcılarına ilgili kaynak kodu da sunman gerekir.

Frappe uygulama/paket adı ve bazı teknik yollar uyumluluk için `kamra` olarak korunmuştur; ürünün adı **TEX Engine**'dir.
