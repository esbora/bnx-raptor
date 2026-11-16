# BnX-Raptor

Avukatlık bürosu için modüler Windows masaüstü programı. Programın arayüzü Almancadır.

## Özellikler (v0.2.0)

- **Sigorta yazısı:** Word mektubunu okur, alıcı e-posta adresini ve sigorta numarasını bulur, kontrol penceresi açar, PDF/A oluşturur ve Outlook taslağını açar. **E-posta asla otomatik gönderilmez.**
- **Müvekkile kopya:** İsteğe bağlı olarak aynı PDF ile müvekkile ikinci bir taslak açılır.
- **Büro bilgileri (Kanzleidaten):** Ad, adres, vergi numarası, USt-IdNr., banka bilgileri ve logo bir kez girilir; bunlardan e-posta imzası oluşturulur.
- **Dosyalar (Akten):** Her sigorta numarası bir dosyadır. Giden yazılar, müvekkile giden e-postalar ve gelen cevaplar tek bir zaman çizelgesinde görünür. Seçilen belgelerle müvekkile ya da sigortaya taslak açılabilir.
- **Gelen cevaplar:** Program Outlook'ta bilinen sigorta numaralarını içeren e-postaları arar. Ayrıca `.eml` / `.msg` dosyaları programa sürüklenebilir. E-posta ve ekleri dava klasörüne kaydedilir; aynı e-posta iki kez kaydedilmez.
- **İşlem geçmişi (Verlauf):** Tüm işlemler tarih, tür, kullanıcı ve durum bilgisiyle listelenir.
- **Güncelleme uyarısı:** Program açılışta GitHub'da yeni sürüm olup olmadığına bakar. Güncellemeyi kullanıcı kendisi kurar (bkz. RELEASE.md).

## Klasör yapısı

```
main.py, version.py         başlangıç, sürüm
config.example.json         örnek ayarlar (config.json ilk açılışta oluşturulur)
core/                       ortak servisler (her iş akışı kullanır)
  extractor.py              e-posta ve numara bulma
  eingang.py                gelen e-postayı dosyayla eşleştirme, .eml okuma
  eingang_service.py        gelen e-postayı klasöre kaydetme + günlük
  outlook_eingang.py        Outlook gelen kutusu (COM)
  entwurf.py                taslak oluşturma (Outlook/.eml, imza, logo)
  mail_service.py           Outlook ve .eml taslak sınıfları
  word_service.py           Word: okuma, PDF/A
  kanzlei.py                büro bilgileri, IBAN/USt-IdNr. kontrolü, imza
  journal.py                veritabanı: işlemler + dosyalar
  update.py                 GitHub sürüm kontrolü
  config.py                 ayarlar
workflows/                  HER YENİ İŞ = BURADA YENİ BİR DOSYA
ui/                         arayüz (PySide6): ana pencere, Akten, Kanzleidaten
tests/                      otomatik testler
.github/workflows/          GitHub: testler + otomatik release
```

## Geliştirme (Windows)

1. Python 3.12'yi python.org'dan kurun ("Add to PATH" işaretli olsun).
2. Programı derlemek için `build.bat` dosyasına çift tıklayın. Sonuç `dist\BnX-Raptor\BnX-Raptor.exe` olur.
3. Doğrudan çalıştırmak için:
   ```
   .venv\Scripts\activate
   python main.py
   ```

Yeni sürüm yayınlamak için: **RELEASE.md**

## Büro bilgisayarında

- Release ZIP dosyasını açın ve klasörü örneğin `C:\Programme\BnX-Raptor` altına koyun.
- İlk açılışta "Kanzleidaten" penceresi çıkar; büro bilgilerini girin.
- Sağ tık menüsüne eklemek için: `Win+R` → `shell:sendto` → `BnX-Raptor.exe` için bir kısayol oluşturun.
- **Outlook:** Varsayılan ayar `"mail_modus": "auto"`. Klasik Outlook varsa taslak orada açılır, yoksa `.eml` taslağı kullanılır. Yeni Outlook'ta gelen cevaplar sürükle-bırak ile alınır.
- **Word şablonu:** İçerik denetimlerinin etiketleri (Tag) `Empfaenger_Email`, `Versicherungsnummer` ve isteğe bağlı `Mandant_Email` olmalı.
