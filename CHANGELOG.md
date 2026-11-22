# Değişiklik Günlüğü (Changelog)

Bu projedeki tüm önemli değişiklikler bu dosyada belgelenir.

## [v2.7.0] - 2026-11-22

### Arayüz (`NovaStream-App/ui`)
- **Tema sistemi (`ui/theme.py`):** Tüm renkler tek bir token tablosundan gelir (açık ve koyu); dağınık satır içi stiller ve eski `ui/styles.py` kaldırıldı. Uygulama sistemin açık/koyu ayarını izler (`QStyleHints.colorSchemeChanged`), Ayarlar → Görünüm'den sabitlenebilir (`theme` ayarı). İkon SVG'leri temaya göre yeniden renklendirilir.
- **Ana pencere (`ui/main_window.py`, `ui/display.py`):** Duruma göre renklenen ince ilerleme çubuğu, durum noktası, aşama bilgisinin Durum sütununa taşınması, yalnızca inen satırda hız/kalan süre, `indirilen / toplam` boyut, Türkçe kategori adları, kısa eklenme zamanı; seçim yokken eylem butonları pasif. Sütun genişlikleri yeni `table_columns` ayarında saklanır.
- **Pencereler:** İlerleme penceresi (`ui/progress_dialog.py`) yeniden düzenlendi, bağlantı haritası yalnızca parçalı indirmelerde gösterilir ve tema renklerini kullanır (`ui/chunk_visualizer.py`); ayarlar bölümlere ayrıldı (`ui/settings_dialog.py`); yeni indirme penceresi ve kurulum sihirbazı (`installer.py`) aynı tasarıma geçti.
- **Erişilebilirlik:** Metin ve kontrol kontrastları WCAG eşiklerine göre seçildi (metin ≥ 4.5:1, kutucuk çerçevesi ≥ 3:1).

### Video İndirme (`core/stream_handler.py`)
- **Akış ölçümü:** Her akış (video, ses kanalları) için süre, boyut, parça, yeniden deneme ve HTTP 429 sayısı loga yazılır (`StreamStats`).
- **Hız sınırlı sunucular:** Ölçümle görülen ~5 istek/sn sınırı nedeniyle HLS eşzamanlı parça sayısı 10 → 4, parça deneme hakkı 10 → 20.

### Araçlar & CI
- Windows konsolunda Türkçe karakter çıktısı çökmesi giderildi (`tools/sync_extensions.py`, `tools/package_extensions.py`); Linux CI'ya Qt sistem kütüphaneleri eklendi; zamanlamaya bağlı kuyruk testi kararlı hale getirildi.

---

## [v2.6.0] - 2026-11-22

### Masaüstü Uygulaması (`NovaStream-App`)
- **İndirme süresi (`core/queue_manager.py`, `core/engine.py`, `ui/main_window.py`, `ui/progress_dialog.py`):** Her görev için yalnızca aktif indirme süresi (`elapsed_seconds`) tutulur ve geçmişe kaydedilir; tabloya **Süre** sütunu (10 sütun) ve ilerleme penceresine süre etiketi eklendi.
- **Ayarlanabilir sütunlar (`ui/main_window.py`):** Sütunlar `Interactive` moda alındı; genişlikler `column_widths` ayarında saklanıp açılışta geri yüklenir.
- **Sürüm görünürlüğü (`ui/main_window.py`, `ui/tray_icon.py`):** `APP_VERSION` pencere başlığında, durum çubuğunda ve tepsi ipucunda gösterilir.
- **Statik kontrol (`installer.py`):** pyflakes'in yakaladığı gereksiz f-string önekleri kaldırıldı.

### Paketleme & Otomatik Release
- **Release iş akışı (`.github/workflows/release.yml`):** Etiket/sürüm tutarlılık kontrolü, `workflow_dispatch` etiket girdisinin kullanımı, Linux arşivinin çalışma ağacı dışında oluşturulması, sürümden bağımsız `ISCC.exe` arama ve eksik dosyada hata verme eklendi.
- **`.crx` release dışı (`tools/package_extensions.py`):** `--no-crx` seçeneği eklendi; CI özel anahtar olmadan yalnızca `.zip` ve `.xpi` üretir.

### Klasör Düzeni
- **Eklentiler tek yerde (`extension/`):** `NovaStream-v2/OpenVideoDownloader-Extension` → `extension/chrome/`, `NovaStream-Firefox/OpenVideoDownloader-Extension` → `extension/firefox/` (otomatik üretilir). İki kopya hâlindeki native host tek kopyaya indirildi: `extension/native_host.*`. Düzen, kurulumdaki `browser/` klasörüyle birebir aynıdır.

---

## [v2.5.0] - 2026-11-20

### Eklenti & Video Yakalama İyileştirmeleri (`NovaStream-v2` & `NovaStream-Firefox`)
- **Rapidrame / Close iframe uyumluluğu:** `webRequest.onBeforeSendHeaders` (Chrome `extraHeaders` + Firefox uyumlu geri dönüş) ile gerçek iframe `Referer`/`Origin` bilgisi yakalanıp `withScopedHeaders` ile uygulanır.
- **HTTP 429 hız sınırı koruması:** Aynı sunucuya yapılan playlist incelemeleri host başına sıraya alındı (200 ms aralık + `120 sn` önbellek + `Retry-After` soğuma süresi). Segment indirmede eşzamanlılık `4 -> 2 -> 1` adaptif düşüş ve üstel bekleme eklendi.
- **Temiz ve anlaşılır medya listesi:** `#EXT-X-MEDIA` ses/altyazı alt listeleri `tabKnownSubstreams` ve yarış-durumu temizliğiyle sahte `[HD]` kaydı olarak çıkmaz. Aynı iframe'de master playlist varsa belirsiz yalın HLS kayıtları bastırılır; kaynak etiketi (`Rapidrame`, `Close`, vb.), bit hızı ve süre açıkça gösterilir.
- **Altyazı yakalama ve `.srt` dönüştürme:** `.vtt`/`.srt`/`.ass`/`.ttml` dosyaları, `<video><track>` öğeleri ve HLS WebVTT altyazı listeleri yakalanır; WebVTT akışları otomatik `.srt` biçimine dönüştürülüp masaüstü köprüsü (`/api/save_subtitle`) veya tarayıcı üzerinden indirilir.

### Masaüstü Uygulaması (`NovaStream-App`)
- **HTTP 429 direnci (`core/engine.py`, `core/stream_handler.py`):** `SegmentedDownloader` HTTP `429`/`503` yanıtlarında `Retry-After` destekli bekleme uygular ve bağlantı sayısını dinamik azaltır; `yt-dlp` tarafında HLS için `-N 4` ve `--retry-sleep` etkinleştirildi.
- **Çoklu seçim ve Tümünü Seç (`ui/main_window.py`, `core/queue_manager.py`):** 9 sütunlu tabloda onay kutuları (`☐`/`☑`), `ExtendedSelection`, **Tümünü Seç** düğmesi, `Ctrl+A` / `Delete` / `Escape` kısayolları ve toplu duraklat/devam/URL kopyala/sil işlemleri eklendi.
- **Altyazı ayarları (`ui/download_dialog.py`, `ui/settings_dialog.py`, `core/bridge_server.py`):** Video ile birlikte otomatik altyazı indirme (`.srt`), dil tercihi (`tr,en`) ve `/api/save_subtitle` uç noktası eklendi.

### Paketleme, Tarayıcı Algılama & Otomatik Release
- **Tarayıcı algılama ve eklenti paketleme (`core/browser_setup.py`, `core/native_messaging.py`, `tools/package_extensions.py`):** `.zip`, CRX3 (`.crx`) ve `.xpi` paketleme; Chrome, Edge, Brave, Opera, Vivaldi, Chromium, Firefox, Firefox Dev, LibreWolf ve Waterfox için algılama, profil yerleştirme ve tek tıkla klasör/dosya rehberliği eklendi.
- **Belgeler ve Release hattı:** Detaylı [BENI-OKU.txt](BENI-OKU.txt), [KULLANIM-KILAVUZU.txt](KULLANIM-KILAVUZU.txt), [RELEASE_NOTES.md](RELEASE_NOTES.md) ve otomatik GitHub Releases iş akışı (`.github/workflows/release.yml`) eklendi.

---

## [v2.4.3] - 2026-11-20

İlk GitHub sürümü ve kararlı temel paket.

### Masaüstü Uygulaması (`NovaStream-App`)
- **Çok kanallı parçalı indirme motoru (`core/engine.py`):** HTTP `Range` desteğiyle 1–32 arası dinamik paralel bağlantı, boşta kalan bağlantılara kalan işleri bölme, `.nspart` / `.nspart.meta` ile duraklatma ve yeniden başlatma sonrası kaldığı yerden devam etme, aynı adlı dosyaların üzerine yazmama (`ad (1).ext`).
- **Akış ve video desteği (`core/stream_handler.py`, `core/updater.py`):** yt-dlp ve FFmpeg üzerinden YouTube, HLS (`.m3u8`) ve DASH (`.mpd`) indirme; kalite seçimi (`best`, `2160`, `1080`, `720`, `480`, `audio`), haftalık otomatik ve manuel yt-dlp / Deno güncellemesi.
- **Yerel köprü ve Native Messaging (`core/bridge_server.py`, `core/native_messaging.py`):** `127.0.0.1:9191` üzerinde yalnızca `chrome-extension://`, `moz-extension://`, `extension://` ve `safari-web-extension://` kaynaklarından istek kabul eden yerel HTTP köprüsü; Windows kayıt defteri ve Linux manifest kaydı.
- **PyQt6 koyu masaüstü arayüzü (`ui/`):** Kategori kenar çubuğu, gerçek zamanlı ilerleme ve parça görselleştirici (`ChunkVisualizer`), sistem tepsisi (`NovaTrayIcon`), pano izleme, ayarlar ve indirme onay pencereleri.
- **Kurulum ve dağıtım (`installer.py`, `NovaStream_Setup.iss`, `tools/build_windows_bundle.ps1`):** Windows için gömülü Python (`runtime`) hazırlama, Inno Setup yükleyici betiği, Windows ve Linux grafiksel/sessiz kurulum sihirbazı.

### Tarayıcı Eklentileri (`NovaStream-v2` & `NovaStream-Firefox`)
- Chrome / Edge / Brave ve Firefox uyumlu Manifest V3 eklentileri (`tools/sync_extensions.py` ile tek kaynaktan senkronize).
- Ağ isteklerinden `.m3u8`, `.mpd`, `.mp4`, `.webm`, `.mkv`, `.mov` akışlarını yakalama, master playlist çözünürlük ayrıştırma, video üzerinde yüzen indirme HUD düğmesi, sağ tık *"NovaStream ile indir"* menüsü ve oturum çerezi aktarımı.

### Otomasyon ve Testler
- `pytest` tabanlı birim/entegrasyon test paketi (`NovaStream-App/tests/`) ve yerel test HTTP sunucusu.
- GitHub Actions CI iş akışı (`.github/workflows/ci.yml`): Windows ve Ubuntu üzerinde `pyflakes`, `pytest`, eklenti senkronizasyon doğrulaması ve `node --check` sözdizimi denetimi.
