# NovaStream v2.5.0

Bu sürüm; gömülü oynatıcı sorunlarını gideren, HTTP 429 hız sınırlarına uyum sağlayan, altyazı indirme ve çoklu seçim özelliklerini ekleyen kapsamlı bir güncellemedir.

## Neler Değişti?

- **Rapidrame / Close Oynatıcı ve HTTP 429 Düzeltmeleri:**
  - Iframe içi video isteklerinin gerçek `Referer` / `Origin` başlıkları korunur.
  - Aynı sunucuya ardışık playlist taramaları host bazında sıraya alınır ve `429` durumunda `Retry-After` süresi kadar beklenir.
  - HLS segment ve HTTP parçalı indirmelerde HTTP `429` hatası alındığında eşzamanlı bağlantı sayısı otomatik düşürülerek indirme sürdürülür.
  - Master playlist içindeki ayrı ses ve altyazı alt listeleri sahte `[HD]` kaydı olarak görünmez; açılır menüde kaynak adı (`Rapidrame`, `Close` vb.), çözünürlük, süre ve bit hızı net gösterilir.
- **Altyazı Yakalama ve İndirme (`.srt`):**
  - Sayfadaki `<track>`, `.vtt`/`.srt`/`.ass` dosyaları ve HLS WebVTT altyazı kanalları yakalanır, WebVTT içerikleri otomatik `.srt` formatına çevrilip indirilir.
  - Masaüstü uygulamasında video ile birlikte altyazı indirme seçeneği ve dil ayarı (`tr,en`) eklendi.
- **Listede Çoklu Seçim & Tümünü Seçme:**
  - İndirme tablosuna onay kutuları (`☐`/`☑`), **Tümünü Seç** düğmesi ve `Ctrl+A`, `Delete`, `Escape` klavye kısayolları ile toplu işlem menüleri eklendi.
- **Paketli Eklentiler, Tarayıcı Algılama ve Detaylı Kurulum Rehberi:**
  - Kurulu tarayıcılar (Chrome, Edge, Brave, Opera, Vivaldi, Chromium, Firefox, Firefox Dev, LibreWolf, Waterfox) otomatik algılanır.
  - `.zip`, `.crx` (CRX3) ve `.xpi` paketleri otomatik üretilir; desteklenen Gecko profillerine `.xpi` yerleştirilir, diğer tarayıcılarda tek tıkla klasör/dosya gösterimi ve uzantı sayfası açılır.
  - Hangi klasör veya dosyanın seçileceğini ayrıntılı anlatan `BENI-OKU.txt` eklendi.

## Release Dosyaları

| Dosya | Açıklama |
| --- | --- |
| `NovaStream-Kurulum-v2.5.0.exe` | Windows kurulum sihirbazı (gömülü Python + FFmpeg içerir) |
| `NovaStream-Linux-v2.5.0.tar.gz` | Linux kaynak & kurulum paketi |
| `NovaStream-Chrome-Edge-Brave-v2.5.0.zip` | Chrome / Edge / Brave / Opera / Vivaldi eklenti arşivi (Paketlenmemiş öğe yükle için) |
| `NovaStream-Chrome-Edge-Brave-v2.5.0.crx` | İmzalı CRX3 eklenti paketi |
| `NovaStream-Firefox-v2.5.0.xpi` | Firefox / LibreWolf / Waterfox eklenti paketi |
| `SHA256SUMS.txt` | Dosya doğrulama özetleri |
