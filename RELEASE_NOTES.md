# NovaStream v2.7.0

Bu sürüm arayüzü baştan düzenler, açık/koyu temayı ekler ve video indirmelerini hız sınırı uygulayan sunuculara karşı daha dayanıklı hale getirir.

## Neler Değişti?

- **Yeni Arayüz:**
  - Uygulama Windows/Linux'un açık-koyu tema ayarını izler ve ayar değişince anında güncellenir; Ayarlar → Görünüm'den "Koyu" veya "Açık" olarak sabitlenebilir.
  - İndirme tablosunda ince ilerleme çubuğu ve durum noktası durumu renkle gösterir (inen, duraklatılan, hatalı, tamamlanan).
  - Hız ve kalan süre yalnızca inen indirmede görünür; videolarda aşama bilgisi Durum sütununda yer alır (ör. `Ses 1/2 · TR`).
  - İnen dosyada boyut `indirilen / toplam` olarak, eklenme zamanı `Bugün 18:38` biçiminde gösterilir; kategori adları Türkçedir.
  - İlerleme penceresi sadeleştirildi; bağlantı haritası yalnızca parçalı indirmelerde görünür.
  - Ayarlar bölümlere ayrıldı; kurulum sihirbazı uygulamayla aynı tasarıma geçti.
- **Video İndirmeleri:**
  - Hız sınırı uygulayan HLS sunucularında (ör. Close) eşzamanlı parça isteği 10'dan 4'e düşürüldü ve parça başına deneme hakkı 20'ye çıkarıldı; uzun indirmelerin HTTP 429 yüzünden yarıda kalma riski azaldı.
  - Her video indirmesinde video ve ses kanalları için süre, boyut, parça ve 429 sayısı log dosyasına yazılır.

> Not: Sütun düzeni değiştiği için tablo sütun genişlikleri bu sürüme geçişte bir kez varsayılana döner.

## Release Dosyaları

| Dosya | Açıklama |
| --- | --- |
| `NovaStream-Kurulum-v2.7.0.exe` | Windows kurulum sihirbazı (gömülü Python + FFmpeg içerir) |
| `NovaStream-Linux-v2.7.0.tar.gz` | Linux kaynak & kurulum paketi |
| `NovaStream-Chrome-Edge-Brave-v2.7.0.zip` | Chrome / Edge / Brave / Opera / Vivaldi eklenti arşivi (Paketlenmemiş öğe yükle için) |
| `NovaStream-Firefox-v2.7.0.xpi` | Firefox / LibreWolf / Waterfox eklenti paketi |
| `SHA256SUMS.txt` | Dosya doğrulama özetleri |
