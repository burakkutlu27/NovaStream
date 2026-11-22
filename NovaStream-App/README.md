# NovaStream Desktop 2.4

Linux ve Windows için çok bağlantılı indirme yöneticisi; YouTube / HLS / DASH video indirme ve Chrome / Edge / Brave / Firefox eklentisi entegrasyonu.

## Özellikler

- **Parçalı indirme motoru (1–32 bağlantı):** HTTP Range ile paralel indirme, boşta kalan bağlantıya iş devri, duraklat / devam, program kapanıp açılınca kaldığı yerden sürdürme.
- **Güvenli dosya yönetimi:** Veri önce `ad.nspart` dosyasına yazılır, bitince asıl ada taşınır; mevcut hiçbir dosyanın üzerine yazılmaz (`ad (1).ext`); "Listeden kaldır" dosyaya dokunmaz.
- **Video:** yt-dlp + FFmpeg; kalite seçimi (4K/1080p/720p/480p/yalnızca ses), DASH, şifreli HLS ve ayrı ses kanallı HLS; Deno ile YouTube uyumu; haftalık otomatik yt-dlp güncellemesi.
- **Tarayıcı köprüsü (127.0.0.1:9191):** Yalnızca eklentilerden istek kabul eder; web siteleri erişemez. İsteğe bağlı onay penceresi.
- **Sağ tık menüsü:** "NovaStream ile indir".
- **Tek örnek, sistem tepsisi, dosyaya loglama.**

## Kurulum

| Sistem | Komut | Not |
| --- | --- | --- |
| Windows | `Kurulum-Windows.bat` | Gömülü Python ile; sistemde Python gerekmez |
| Linux | `./run_installer.sh` | venv kurar; FFmpeg'i paket yöneticisiyle kurar |
| Sessiz kurulum | `python installer.py --silent [--dir KLASÖR] [--no-shortcuts] [--no-browser]` | |

## Geliştirici notları

- **Gömülü Python paketi (Windows):** `powershell -ExecutionPolicy Bypass -File tools\build_windows_bundle.ps1` → `NovaStream-App\runtime`
- **Inno Setup:** `NovaStream_Setup.iss` (önce gömülü paketi oluşturun)
- **Eklenti tek kaynaktan:** `extension/chrome/` düzenlenir, `python tools/sync_extensions.py` `extension/firefox/` kopyasını üretir.
- **Kurmadan tarayıcı köprüsü:** `setup_native_host.sh` / `setup_native_host_windows.bat`
- **Testler:** `python -m pytest NovaStream-App/tests` (ağ gerekmez; yerel test sunucusu kullanır)
- **CI:** `.github/workflows/ci.yml` — Windows ve Linux'ta pyflakes + testler + eklenti senkron kontrolü
