# Değişiklik Günlüğü (Changelog)

Bu projedeki tüm önemli değişiklikler bu dosyada belgelenir.

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
