# NovaStream İndirme Yöneticisi

[![CI](https://github.com/burakkutlu27/NovaStream/actions/workflows/ci.yml/badge.svg)](https://github.com/burakkutlu27/NovaStream/actions/workflows/ci.yml)
![Sürüm](https://img.shields.io/badge/sürüm-v2.6.0-2563eb)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-0f172a)
![Lisans](https://img.shields.io/badge/lisans-MIT-10b981)

**NovaStream**, Windows ve Linux için geliştirilmiş; çok kanallı parçalı HTTP indirme motorunu, YouTube / HLS / DASH ve gömülü iframe oynatıcı video akışı desteğini, altyazı (.srt) indirmeyi ve Chrome / Edge / Brave / Opera / Vivaldi / Firefox tarayıcı eklentilerini tek çatı altında birleştiren açık kaynaklı bir indirme yöneticisidir.

---

## Özellikler (v2.6.0)

- **Çok Kanallı Parçalı İndirme Motoru (`1–32` Bağlantı) & HTTP 429 Koruması:** HTTP `Range` istekleriyle dosyaları paralel parçalara böler, boşta kalan bağlantılara kalan işten parça aktarır; HTTP `429`/`503` hız sınırlarında `Retry-After` başlığına uyup bağlantı sayısını otomatik azaltarak kesintisiz devam eder.
- **Gömülü Iframe Oynatıcı Uyumluluğu:** `webRequest.onBeforeSendHeaders` ile gerçek iframe `Referer`/`Origin` başlıklarını yakalar ve DNR üzerinden uygular. Master playlist içindeki ayrı ses ve altyazı alt listelerini sahte `[HD]` video olarak göstermeyi engeller; her akış için oynatıcı kaynak etiketini, çözünürlüğü, süreyi ve bit hızını net sunar.
- **Altyazı Yakalama ve İndirme (`.srt`):** Web sayfasındaki `<track>` öğelerini, ağdaki `.vtt`/`.srt`/`.ass` dosyalarını ve HLS altyazı listelerini algılar; WebVTT akışlarını otomatik `.srt` biçimine dönüştürüp indirir. Masaüstü uygulamasında da `yt-dlp` ile video + altyazı indirme desteği sunar.
- **Masaüstü Listesinde Çoklu Seçim ve Tümünü Seçme:** Tablo içi onay kutuları (`☐`/`☑`), araç çubuğu **Tümünü Seç** düğmesi, `Ctrl+A`, `Ctrl+Tık`, `Shift+Tık`, `Delete` ve `Escape` kısayollarıyla toplu duraklatma, devam ettirme, URL kopyalama ve silme işlemleri.
- **Paketli Eklenti Dağıtımı & Tarayıcı Algılama:** `.zip` ve `.xpi` eklenti paketleri üretilir (imzalı `.crx` yalnızca yerelde, özel anahtarla). Kurulum sihirbazı ve Ayarlar penceresi kurulu tarayıcıları (Chrome, Edge, Brave, Opera, Vivaldi, Chromium, Firefox, Firefox Dev, LibreWolf, Waterfox) algılayıp köprü kaydını yapar ve adım adım tek tıkla klasör/dosya rehberliği sunar.
- **İndirme Süresi & Kişiselleştirilebilir Tablo:** Her indirmenin aktif süresi (duraklatmalar hariç) **Süre** sütununda ve ilerleme penceresinde gösterilir; tablo sütunları sürüklenerek genişletilebilir ve genişlikler hatırlanır. Uygulama sürümü pencere başlığında ve durum çubuğunda görünür.
- **Güvenli Dosya Yönetimi & Yerel Köprü (`127.0.0.1:9191`):** İndirilen veri `.nspart` dosyasına yazılır, bitince asıl ada taşınır; mevcut dosyaların üzerine yazılmaz. Köprü sunucusu yalnızca tarayıcı eklenti kökenlerinden istek kabul eder.

---

## Proje Yapısı

| Dizin / Dosya | Açıklama |
| --- | --- |
| `NovaStream-App/` | **Masaüstü uygulaması (Windows + Linux ortak).** PyQt6 arayüz (`ui/`), indirme motorları (`core/`), kurulum sihirbazı (`installer.py`), testler (`tests/`). Windows'a özel: `run_windows.bat`, `Kurulum-Windows.bat`, `NovaStream_Setup.iss` (Inno Setup). Linux'a özel: `run_linux.sh`, `run_installer.sh`, `Kurulum-Linux.desktop` |
| `extension/chrome/` | **Chrome / Edge / Brave / Opera / Vivaldi eklentisi** (Manifest V3). Eklentinin **kaynağı** burasıdır; değişiklikler burada yapılır |
| `extension/firefox/` | **Firefox / LibreWolf / Waterfox eklentisi.** `python tools/sync_extensions.py` ile `extension/chrome/`'dan **otomatik üretilir**, elle düzenlenmez |
| `extension/native_host.*` | Tarayıcı ↔ masaüstü uygulaması köprüsü (Native Messaging). İki tarayıcı ailesi için ortak, tek kopya (`.bat` Windows, `.sh` Linux) |
| `Kurulum-Windows.bat` / `Kurulum-Linux.desktop` | Kökten çift tıklayarak kurulumu başlatan kısayollar (`NovaStream-App/` içindekileri çağırır) |
| `setup_native_host*.sh/.bat` | Geliştirici için: uygulamayı kurmadan, kaynak klasörden tarayıcı köprüsünü kaydeder |
| `tools/` | Gömülü Python/FFmpeg paketleyici (`build_windows_bundle.ps1`), eklenti senkronizasyonu (`sync_extensions.py`), `.zip`/`.crx`/`.xpi` paketleyici (`package_extensions.py`) ve eklenti birim testleri (`test_extension.mjs`) |
| `.github/workflows/` | CI doğrulama hattı (`ci.yml`) ve etiket tabanlı otomatik GitHub Release yayınlama hattı (`release.yml`) |
| `BENI-OKU.txt` & `KULLANIM-KILAVUZU.txt` | Detaylı tarayıcı kurulumu (hangi klasör/dosya seçilmeli) ve kullanım kılavuzu |

---

## Kurulum

### 1. Windows

1. [GitHub Releases](https://github.com/burakkutlu27/NovaStream/releases) sayfasından **`NovaStream-Kurulum-v2.6.0.exe`** dosyasını indirip çalıştırın.
   - Windows *"Bilinmeyen yayımcı"* uyarısı gösterirse **Ek bilgi → Yine de çalıştır** seçeneğini kullanın.
   - Gömülü Python ve FFmpeg paketlendiği için bilgisayarınızda ek kurulum gerektirmez.
2. Kaynak koddan kurmak isterseniz:
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\build_windows_bundle.ps1 -IncludeFFmpeg
   .\Kurulum-Windows.bat
   ```

### 2. Linux

`Kurulum-Linux.desktop` dosyasına çift tıklayın veya terminal üzerinden kurulum sihirbazını başlatın:

```bash
chmod +x NovaStream-App/run_installer.sh
./NovaStream-App/run_installer.sh
```

### 3. Tarayıcı Eklentisini Yükleme (Detaylı Rehber: `BENI-OKU.txt`)

Kurulum sihirbazı Native Messaging köprülerini ve Gecko `.xpi` profillerini otomatik hazırlar. Tarayıcı güvenlik politikası nedeniyle manuel yükleme gerekirse:

#### Chrome / Microsoft Edge / Brave / Opera / Vivaldi
1. `chrome://extensions` (veya `edge://extensions`, `brave://extensions`, `opera://extensions`, `vivaldi://extensions`) adresini açın.
2. Sağ üstten **Geliştirici modu (Developer mode)** anahtarını açın.
3. **Paketlenmemiş öğe yükle (Load unpacked)** düğmesine tıklayın ve **`manifest.json` dosyasını değil**, doğrudan şu **KLASÖRÜ** seçin:
   - **Windows:** `%LOCALAPPDATA%\NovaStream\browser\chrome`
   - **Linux:** `~/.local/share/NovaStream/browser/chrome`
   - *(Kaynak klasörden test için: `extension/chrome`)*
4. Sabit eklenti kimliği: `phbdcgdmpmgacehbfkkjbmjofdhhhohg`

> **Not (`.crx` ve `.zip` paketleri):** Tarayıcı politikaları gereği Windows'ta Chrome/Edge, mağaza dışı yerel `.crx` dosyalarının sessiz kurulumuna izin vermez. Bu yüzden GitHub Releases ve `<kurulum>\browser\packages\` altında taşınabilir `.zip` paketi sunulur; manifest'teki sabit anahtar sayesinde "Paketlenmemiş öğe yükle" ile kurulan eklenti her zaman yukarıdaki kimliği alır. İmzalı `.crx`, yalnızca özel anahtara sahip geliştirici tarafından yerelde `python tools/package_extensions.py` ile üretilir.

#### Firefox (Standart) & LibreWolf / Waterfox / Firefox Dev
- **Standart Firefox:** `about:debugging#/runtime/this-firefox` adresini açın → **Geçici Eklenti Yükle...** → **klasörü değil şu DOSYAYI seçin:**
  - **Windows:** `%LOCALAPPDATA%\NovaStream\browser\firefox\manifest.json`
  - **Linux:** `~/.local/share/NovaStream/browser/firefox/manifest.json`
- **Firefox Developer Edition / LibreWolf / Waterfox:** Kurulum sihirbazı `novastream@downloader.local.xpi` paketini profilinizin `extensions` klasörüne otomatik yerleştirir.

---

## Kullanım ve Sorun Giderme

- **Yüzen İndirme Butonu ve Popup:** Oynatıcı üzerindeki **İndir** düğmesi her iframe kaynağını ayrı algılar; menüde çözünürlük, kaynak adı, süre ve algılanan `.srt` altyazıları listelenir.
- **Çoklu Seçim Kısayolları:** `Ctrl+A` (Tümünü seç / kaldır), `Delete` (Seçilileri sil), `Esc` (Seçimi temizle), `Ctrl+Tık` / `Shift+Tık` veya tablo onay kutuları.
- **Log Dosyaları:**
  - Masaüstü uygulaması: Windows'ta `%APPDATA%\NovaStream\logs`, Linux'ta `~/.config/novastream/logs`
  - Native Messaging: Windows'ta `%TEMP%\novastream_native.log`, Linux'ta `/tmp/novastream_native.log`

---

## Gelecek Planı (Roadmap)

- [ ] Harici FFmpeg ve yt-dlp bağımlılıklarından tamamen bağımsız, yerleşik medya ayrıştırıcı ve muxer motoru araştırma ve geliştirme.
- [ ] Chrome Web Store ve Mozilla Add-ons (AMO) üzerinden resmi mağaza imzalı eklenti dağıtımı.

---

## Geliştirici Komutları

- **Eklentileri senkronize etme ve paketleme (`.zip`, `.crx`, `.xpi`):**
  ```bash
  python tools/sync_extensions.py
  python tools/package_extensions.py --out dist/extensions --with-id-name
  ```
- **Windows gömülü Python + FFmpeg paketi hazırlama:**
  ```powershell
  powershell -ExecutionPolicy Bypass -File tools\build_windows_bundle.ps1 -IncludeFFmpeg
  ```
- **Testleri çalıştırma:**
  ```bash
  python -m pytest -v NovaStream-App/tests
  node tools/test_extension.mjs
  ```

---

## Lisans

Bu proje [MIT Lisansı](LICENSE) altında lisanslanmıştır.
