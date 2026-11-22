# NovaStream v2.6.0

Bu sürüm indirme süresini gösterir, indirme tablosunu kişiselleştirilebilir hale getirir ve otomatik release hattındaki hataları giderir.

## Neler Değişti?

- **İndirme Süresi:**
  - İndirme tablosuna **Süre** sütunu eklendi; indirme sürerken canlı artar, bitince toplam süreyi gösterir. Duraklatma ve kuyrukta bekleme süreleri sayılmaz.
  - Süre geçmişe kaydedilir, uygulama yeniden açıldığında kaybolmaz. İlerleme penceresinde de görünür.
- **Ayarlanabilir Sütun Genişlikleri:**
  - Tablo sütunları başlık kenarından sürüklenerek genişletilip daraltılabilir; genişlikler ayarlara kaydedilir.
- **Sürüm Bilgisi:**
  - Uygulama sürümü pencere başlığında, durum çubuğunun sağ köşesinde ve sistem tepsisi ipucunda gösterilir.
- **Release Hattı Düzeltmeleri:**
  - Etiket ile uygulama/eklenti/kurulum sürümleri uyuşmazsa yayın en başta durur.
  - Linux paketi ve Windows kurulum adımları daha sağlam hale getirildi; eksik dosya varsa yayın yapılmaz.
  - Mağaza dışı `.crx` kurulumu tarayıcılarca engellendiği için release'ten çıkarıldı; Chrome tabanlı tarayıcılar için `.zip` paketi aynı sabit eklenti kimliğini verir.

## Release Dosyaları

| Dosya | Açıklama |
| --- | --- |
| `NovaStream-Kurulum-v2.6.0.exe` | Windows kurulum sihirbazı (gömülü Python + FFmpeg içerir) |
| `NovaStream-Linux-v2.6.0.tar.gz` | Linux kaynak & kurulum paketi |
| `NovaStream-Chrome-Edge-Brave-v2.6.0.zip` | Chrome / Edge / Brave / Opera / Vivaldi eklenti arşivi (Paketlenmemiş öğe yükle için) |
| `NovaStream-Firefox-v2.6.0.xpi` | Firefox / LibreWolf / Waterfox eklenti paketi |
| `SHA256SUMS.txt` | Dosya doğrulama özetleri |
