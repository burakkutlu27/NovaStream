# NovaStream İndirme Yöneticisi

[![CI](https://github.com/burakkutlu27/NovaStream/actions/workflows/ci.yml/badge.svg)](https://github.com/burakkutlu27/NovaStream/actions/workflows/ci.yml)
![Sürüm](https://img.shields.io/badge/sürüm-v2.4.3-2563eb)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-0f172a)
![Lisans](https://img.shields.io/badge/lisans-MIT-10b981)

**NovaStream**, Windows ve Linux için geliştirilmiş; çok kanallı parçalı HTTP indirme motorunu, YouTube / HLS / DASH video akışı desteğini ve Chrome / Edge / Brave / Firefox tarayıcı eklentilerini tek çatı altında birleştiren açık kaynaklı bir indirme yöneticisidir.

---

## Özellikler (v2.4.3)

- **Çok Kanallı Parçalı İndirme Motoru (`1–32` Bağlantı):** HTTP `Range` istekleriyle dosyaları paralel parçalara böler, boşta kalan bağlantılara kalan işten parça aktarır ve `.nspart` / `.nspart.meta` dosyalarıyla duraklatma veya uygulama kapanışı sonrası kaldığı yerden devam eder.
- **Güvenli Dosya Yönetimi:** İndirilen veri önce `.nspart` geçici dosyasına yazılır, tamamlanınca hedef ada taşınır; mevcut dosyaların üzerine yazılmaz (`dosya (1).ext`). Listeden kaldırma işlemi diskteki dosyaya dokunmaz.
- **Video ve Akış İndirme (yt-dlp + FFmpeg + Deno):** YouTube (4K/1080p/720p/480p/yalnızca MP3 ses), HLS (`.m3u8`), şifreli HLS, ayrı ses kanallı akışlar ve DASH (`.mpd`) videolarını indirip birleştirir. Haftalık otomatik yt-dlp/Deno güncellemesi destekler.
- **Tarayıcı Eklentileri (Manifest V3):**
  - Chrome, Microsoft Edge, Brave ve Firefox ile uyumludur.
  - Sayfadaki medya akışlarını ve HLS master playlist çözünürlüklerini otomatik yakalar.
  - Video oynatıcı üzerinde yüzen indirme düğmesi, açılır pencere (popup) ve sağ tık *"NovaStream ile indir"* menüsü sunar.
  - Giriş gerektiren (ör. kanal üyeliği) videolarda oturum çerezlerini yalnızca yerel makinedeki NovaStream'e geçici olarak iletir.
- **Güvenli Yerel Köprü (`127.0.0.1:9191`) & Native Messaging:** Köprü sunucusu yalnızca tarayıcı eklenti kökenlerinden (`chrome-extension://`, `moz-extension://`, `extension://`, `safari-web-extension://`) gelen istekleri kabul eder; web sayfalarının doğrudan erişimini `403` ile engeller.
- **Modern Koyu Masaüstü Arayüzü (PyQt6):** Kategori filtreleme, canlı hız ve bağlantı kanalı görselleştirici (`ChunkVisualizer`), sistem tepsisi küçültme/bildirim, pano izleme ve tek örnek (single-instance) kilidi.

---

## Proje Yapısı

| Dizin / Dosya | Açıklama |
| --- | --- |
| `NovaStream-App/` | PyQt6 masaüstü uygulaması, indirme motorları (`core/`), arayüz (`ui/`), kurulum sihirbazı (`installer.py`), Inno Setup betiği (`NovaStream_Setup.iss`) ve testler (`tests/`) |
| `NovaStream-v2/` | Chrome / Edge / Brave Manifest V3 eklenti kaynağı ve Native Messaging host (`native_host.py`, `native_host.bat`, `native_host.sh`) |
| `NovaStream-Firefox/` | `tools/sync_extensions.py` ile `NovaStream-v2` kaynağından otomatik senkronize edilen Firefox eklenti paketi |
| `tools/` | Windows gömülü Python paketi oluşturucu (`build_windows_bundle.ps1`) ve eklenti senkronizasyon aracı (`sync_extensions.py`) |
| `.github/workflows/` | Windows ve Ubuntu üzerinde çalışan CI doğrulama hattı (`ci.yml`) |
| `KULLANIM-KILAVUZU.txt` | Son kullanıcı kurulum ve kullanım kılavuzu |

---

## Kurulum

### 1. Windows

1. [GitHub Releases](https://github.com/burakkutlu27/NovaStream/releases) sayfasından **`NovaStream-Kurulum-2.4.3.exe`** dosyasını indirip çalıştırın.
   - Windows *"Bilinmeyen yayımcı"* uyarısı gösterirse **Ek bilgi → Yine de çalıştır** seçeneğini kullanın.
   - Paket içinde gömülü Python yer aldığı için sistemde Python kurulu olması gerekmez ve yönetici izni istemez.
   - Kurulum varsayılan olarak `%LOCALAPPDATA%\NovaStream` klasörüne yapılır, kısayolları ve tarayıcı köprülerini kaydeder, FFmpeg yoksa `winget` ile kurmayı dener.
2. Kaynak koddan kurmak isterseniz önce gömülü Python çalışma ortamını hazırlayıp ardından `Kurulum-Windows.bat` dosyasını çalıştırın:
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\build_windows_bundle.ps1
   .\Kurulum-Windows.bat
   ```

### 2. Linux

`Kurulum-Linux.desktop` dosyasına çift tıklayın veya terminal üzerinden kurulum sihirbazını başlatın:

```bash
chmod +x NovaStream-App/run_installer.sh
./NovaStream-App/run_installer.sh
```

Uygulama `~/.local/share/NovaStream` dizinine kurulur, Python sanal ortamı (`venv`) oluşturulur ve sistemde yoksa paket yöneticisi aracılığıyla FFmpeg kurulumu başlatılır.

### 3. Tarayıcı Eklentisini Yükleme (Bir Kez)

#### Chrome / Microsoft Edge / Brave
1. Tarayıcıda **`chrome://extensions`** (Edge için `edge://extensions`, Brave için `brave://extensions`) adresini açın.
2. Sağ üstten **Geliştirici modu (Developer mode)** anahtarını açın.
3. **Paketlenmemiş öğe yükle (Load unpacked)** düğmesine tıklayın ve kurulum sonrası oluşan şu klasörü seçin:
   - **Windows:** `%LOCALAPPDATA%\NovaStream\browser\chrome`
   - **Linux:** `~/.local/share/NovaStream/browser/chrome`
   - *(Kaynak klasörden doğrudan test için: `NovaStream-v2/OpenVideoDownloader-Extension`)*
4. Sabit eklenti kimliği: `phbdcgdmpmgacehbfkkjbmjofdhhhohg`

#### Firefox
1. Adres çubuğuna **`about:debugging#/runtime/this-firefox`** yazıp açın.
2. **Geçici Eklenti Yükle (Load Temporary Add-on...)** düğmesine tıklayın ve şu dosyayı seçin:
   - **Windows:** `%LOCALAPPDATA%\NovaStream\browser\firefox\manifest.json`
   - **Linux:** `~/.local/share/NovaStream/browser/firefox/manifest.json`
   - *(Kaynak klasörden doğrudan test için: `NovaStream-Firefox/OpenVideoDownloader-Extension/manifest.json`)*

---

## Kullanım ve Sorun Giderme

- **Otomatik Video Yakalama:** Video sayfasında oynatıcının sağ üst köşesinde beliren **İndir** düğmesine tıklayın veya tarayıcı araç çubuğundaki NovaStream simgesini açın. Masaüstü uygulaması açıksa indirme otomatik olarak uygulamaya aktarılır.
- **Sağ Tık Menüsü:** Herhangi bir video, ses veya dosya bağlantısına sağ tıklayıp **NovaStream ile indir** seçeneğini kullanabilirsiniz.
- **Log Dosyaları:**
  - Masaüstü uygulaması logları (Ayarlar → *Log klasörünü aç*): Windows'ta `%APPDATA%\NovaStream\logs`, Linux'ta `~/.config/novastream/logs`
  - Native Messaging köprü logu: Windows'ta `%TEMP%\novastream_native.log`, Linux'ta `/tmp/novastream_native.log`
- **Yarım İndirmeler:** Duraklatılan veya kesilen indirmeler `.nspart` uzantısıyla saklanır ve **Devam Et** ile kaldığı bayttan sürer.

---

## Gelecek Planı (Roadmap)

Sonraki sürümlerde üzerinde çalışılacak planlanan geliştirmeler:

- [ ] **Rapidrame / Close Oynatıcı Uyumluluğu:** Gömülü iframe oynatıcılarında doğru `Referer`/`Origin` aktarımı, HTTP `429` hız uyarlaması ve medya listesinde gereksiz/tekrarlı seçeneklerin temizlenmesi.
- [ ] **Çoklu Seçim ve Tümünü Seçme:** Masaüstü indirme tablosunda çoklu satır seçimi, `Ctrl+A` / tümünü seçme ve toplu işlem (duraklat/devam/sil) desteği.
- [ ] **Altyazı Yakalama ve İndirme:** Web sayfası ve akışlardaki `.vtt`, `.srt`, `.ass` ve HLS altyazı kanallarını algılayıp indirme desteği.
- [ ] **Paketli Eklenti Dağıtımı ve Otomatik Tarayıcı Tespiti:** `.xpi`, `.crx` ve `.zip` paketleme, kurulum sihirbazında yüklü tarayıcı profillerini otomatik algılama ve adım adım rehberli kurulum.
- [ ] **Harici Bağımlılıkları Azaltma:** FFmpeg ve yt-dlp bağımlılığını en aza indiren yerleşik alternatif akış/birleştirme motoru üzerine araştırma ve geliştirme.
- [ ] **Otomatik GitHub Releases Hattı:** Etiket (`tag`) bazlı otomatik Windows kurulum paketi ve eklenti arşivi yayınlama iş akışı.

---

## Geliştirici Komutları

- **Eklentileri senkronize etme (`NovaStream-v2` → `NovaStream-Firefox`):**
  ```bash
  python tools/sync_extensions.py
  ```
- **Windows gömülü Python çalışma ortamını hazırlama:**
  ```powershell
  powershell -ExecutionPolicy Bypass -File tools\build_windows_bundle.ps1
  ```
- **Testleri çalıştırma (ağ erişimi gerekmez; yerel test HTTP sunucusu kullanır):**
  ```bash
  python -m pytest -v NovaStream-App/tests
  ```
- **Kurulum yapmadan yerel Native Host kaydı:**
  - Windows: `setup_native_host_windows.bat`
  - Linux: `./setup_native_host.sh`

---

## Lisans

Bu proje [MIT Lisansı](LICENSE) altında lisanslanmıştır.
