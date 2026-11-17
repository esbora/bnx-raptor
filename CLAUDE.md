# CLAUDE.md – BnX-Raptor

Bu dosya Claude Code için proje talimatıdır. Her oturumun başında okunur.

## 1. Proje nedir?

**BnX-Raptor**, Almanya'daki bir avukatlık bürosu için yazılmış bir **Windows masaüstü programıdır**.
Amacı avukatın tekrar eden yazışma işlerini tek ekrandan, birkaç tıklamayla yapmaktır.
Program zamanla büyüyecek; her yeni iş ayrı bir **iş akışı (workflow) modülü** olarak eklenecek.

Mevcut sürüm: `version.py` dosyasına bakın (`main`: 0.2.0 yayımlı; `v0.3.0-entwicklung`: 0.3.0; yerel `v0.4.0-pdf`: 0.4.0). Değişiklikler `CHANGELOG.md` dosyasında.

## 2. Dil ve iletişim

- **Proje dili Türkçedir:** kod yorumları, docstring'ler, README, CLAUDE.md, RELEASE.md ve commit mesajları Türkçe yazılır.
- **Programın arayüzü yalnızca Almancadır:** pencereler, düğmeler, hata mesajları, e-posta metinleri ve `CHANGELOG-aktuell.md` (avukat bunu okur). Avukat Türkçe bilmiyor.
- Koddaki tanımlayıcılar (değişken, fonksiyon adları) İngilizce ya da Almanca olabilir, ama bir dosya içinde tutarlı olmalı.
- Proje sahibiyle **Türkçe** konuşulur. Proje sahibi programcı değil: adımları basit anlat, komutları eksiksiz ve kopyalanabilir ver, bir şey kurmak gerekiyorsa neden gerektiğini tek cümleyle söyle.
- Büyük bir değişiklikten önce (mimari, yeni bağımlılık, veri biçimi değişikliği) kısa bir plan sun ve onay al. Küçük düzeltmeleri doğrudan yap.

## 3. Değişmez kurallar

1. **E-posta asla otomatik gönderilmez.** `.Send()` çağrısı yasaktır. Sadece `.Display()` ya da `.eml` taslak kullanılır.
2. **Avukat her zaman son kontrolü yapar.** Otomatik bulunan her değer kontrol penceresinde, kaynağıyla birlikte gösterilir („aus Vorlage“ / „erkannt – bitte prüfen“).
3. **Veriler bürodan çıkmaz (DSGVO, avukatlık sırrı § 203 StGB).** Bulut servisi, harici API, telemetri ya da otomatik hata raporu eklenmez.
   **Tek istisna:** GitHub'daki son sürümün sorgulanması (`core/update.py`). Bu sadece bir GET isteğidir ve hiçbir veri göndermez. `config.json` içinde `"update_pruefen": false` ile kapatılabilir.
4. **Orijinal belgeler değiştirilmez.** Word salt okunur açılır, sonuçlar yeni dosya olarak yazılır.
5. **Var olan bir dosyanın üzerine yazılmaz.** Aynı isimde dosya varsa `_2`, `_3` … eklenir.
6. **Avukatın açık Word penceresine dokunulmaz.** Program ayrı ve görünmez bir Word örneği (`DispatchEx`) kullanır.
7. **Her işlem günlüğe yazılır** (`journal`): başarılı, iptal ve hata durumları dahil.
8. **Aynı gelen e-posta iki kez kaydedilmez.** Bunun için `quelle_id` (Message-ID) kullanılır.
9. **Güncellemeler büro verilerini ezmez.** Release ZIP içinde `config.json` yoktur; veriler `%APPDATA%\BnX-Raptor` klasöründe (ya da `daten_ordner` ayarındaki klasörde) durur.
10. **Veritabanı değişiklikleri sadece ekleme yoluyla yapılır.** Yeni sütun gerekirse `journal.py` içindeki `MIGRATIONEN` listesine eklenir. Mevcut sütunlar silinmez ve adları değiştirilmez.

## 4. Teknoloji

- Python 3.12+, arayüz **PySide6**, Office otomasyonu **pywin32 (COM)**
- Paketleme: **PyInstaller** → `BnX-Raptor.exe` (büroda Python kurulu olması gerekmez)
- Veri: SQLite (`verlauf.sqlite`, tablolar `vorgaenge`, `akten` ve `versicherer`), büro bilgileri `kanzlei.json` ve logo dosyası
- Ayarlar: exe'nin yanındaki `config.json` (ilk açılışta oluşturulur). Örnek: `config.example.json`
- Testler: pytest. GitHub Actions: her push'ta testler, `v*` etiketiyle release
- Hedef sistem: Windows 10/11, Microsoft Word, klasik Outlook.
  "Yeni Outlook" COM desteklemez. Varsayılan `"mail_modus": "auto"` bunu kendisi algılar
  (`core/entwurf.py` → `mail_modus()`): klasik Outlook varsa taslak orada açılır, yoksa `.eml` taslağı kullanılır.
  Gelen cevaplar klasik Outlook'ta otomatik aranır; yeni Outlook'ta sürükle-bırak ile alınır.

## 5. Mimari

```
main.py                 başlangıç; komut satırı argümanları = listeye eklenecek dosyalar
version.py              __version__ (TEK kaynak)
core/                   ortak servisler – iş akışları bunları kullanır, aynı kod tekrar yazılmaz
  config.py             DEFAULTS, load_config(), app_dir(), data_dir(cfg)
  extractor.py          metinden e-posta/numara bulma (tüm numaralar + türü), konu  [saf Python]
  eingang.py            numara eşleştirme, .eml okuma, dosya adı  [saf Python]
  kanzlei.py            Kanzlei verisi, IBAN/USt-IdNr. kontrolü, imza HTML'i  [saf Python]
  update.py             sürüm karşılaştırma, GitHub sorgusu       [saf Python]
  adressbuch.py         Versicherer-Adressbuch: ad bulma/eşleştirme, e-posta önerisi, tablo  [saf Python]
  journal.py            SQLite: vorgaenge (art: ausgang|mandant|eingang|entwurf) + akten
  entwurf.py            entwurf_erstellen(ctx, MailDraft, eml_klasoru) – TÜM taslaklar buradan geçer
  mail_service.py       OutlookClassicDrafter, EmlDrafter       [COM / saf]
  word_service.py       Word okuma, PDF/A; zaman sınırı (sadece kendi Word sürecini kapatır)  [COM]
  pdf_engine.py         0.4: PDF motoru (PyMuPDF) + yerel OCR (Tesseract, exe yanındaki ocr\) – sadece editör açılınca yüklenir
  pdf_sitzung.py        PDF düzenleme oturumu: bellekte kopya, geri al/yinele, önizleme, Speichern unter + karartma kontrolü
  anlagen.py            Anlagen-Assistent mantığı: okuma, numara, uyarılar (aynı/benzer/bozuk/ters), paket (geçici klasör)
  docx_schreiben.py     Word'süz basit .docx (Anlagenverzeichnis)  [saf Python]
  outlook_eingang.py    gelen kutusu arama, .msg kaydetme        [COM]
  eingang_service.py    gelen e-postayı kaydetme + günlüğe yazma
workflows/
  base.py               AppContext(cfg, kanzlei_store, journal, adressbuch), Workflow, Field, Result
  __init__.py           ALL_WORKFLOWS kaydı
  versicherung_brief.py iş akışı 1 (+ isteğe bağlı müvekkil kopyası)
ui/
  main_window.py        sekmeler: Bearbeiten / Akten / Verlauf; menüler; güncelleme şeridi
  akten_tab.py          dosya listesi, dosya geçmişi, içe aktarma, e-posta taslağı
  kanzlei_dialog.py     büro bilgileri + logo + imza önizlemesi
  adressbuch_dialog.py  Versicherer-Adressbuch: görme, arama, düzenleme, ekleme, silme
  pdf_editor.py         „PDF bearbeiten“ (QDialog; Word→PDF akışından ve Anlagen'den de açılır)
  anlagen_tab.py        Anlagen-Assistent sekmesi (ilk açılışta yüklenir) + Kontrollansicht
  pdf_ui.py             ortak: görüntü, arka plan işi (Tesseract), AnhangVorschau (Outlook öncesi ek önizlemesi)
```

### Workflow sözleşmesi

```python
class Workflow:
    id, name, description, file_types
    def __init__(self, ctx: AppContext)        # self.ctx, self.cfg
    def accepts(path) -> bool
    def prepare(path) -> list[Field]           # oku, kontrol penceresinin alanlarını döndür
    def execute(path, values) -> Result        # onaylanan değerlerle işi yap
```

`Field` kontrol penceresini tarif eder: `hint` (kaynak), `choice_hints` (seçenek başına kaynak), `must_choose` (önceden seçili değer yok, kullanıcı seçer), `on_change` (bu alan değişince bağlı alanları yeniden hesapla).

Yeni iş akışı eklemek için `workflows/` altına yeni bir dosya yazılır ve `ALL_WORKFLOWS` listesine bir satır eklenir. Kontrol penceresi `Field` listesinden otomatik oluşur.

### Mimari kurallar

- **İş mantığı ile Windows/COM kodu ayrı tutulur.** Saf Python mantığı `core/` içinde yazılır ve Linux'ta da test edilebilir. COM çağrıları ince servis sınıflarında kalır.
- `win32com` / `pythoncom` sadece fonksiyonların içinde import edilir, böylece testler Windows olmadan çalışır.
- Ayarlanabilir her şey `config.json` dosyasına ve `DEFAULTS` sözlüğüne gider. Yeni bir anahtar eklendiğinde `DEFAULTS` sözlüğüne ve `config.example.json` dosyasına da eklenir.
- E-posta taslakları **sadece** `core/entwurf.py` üzerinden oluşturulur; imza, logo ve mod seçimi orada yapılır.
- Kullanıcıya gösterilen hata mesajı anlaşılır Almanca olur; teknik ayrıntılar günlüğe yazılır.

## 6. Komutlar

```bat
build.bat                                  :: venv, bağımlılıklar, testler, exe (yerel)
.venv\Scripts\activate & python main.py    :: geliştirme sırasında çalıştırma
python -m pytest -q tests                  :: testler
```

Her değişiklikten sonra testler çalıştırılır. Yeni saf Python mantığı için test yazılır.
COM kısmı otomatik test edilemiyorsa proje sahibine kısa bir **elle test adımları** listesi verilir.

## 7. Sürüm ve release

- Sürümü Claude belirler: hata düzeltmesinde PATCH, yeni özellikte MINOR artırılır. `version.py`, `CHANGELOG.md` ve `CHANGELOG-aktuell.md` (Almanca) birlikte güncellenir.
- Release: `version.py` + changelog güncellenir, commit edilir, `main`'e push edilir. GitHub Actions (`release.yml`) etiketi, exe dosyasını, ZIP'i ve Release'i kendisi oluşturur. Elle etiket oluşturulmaz. Ayrıntılar **RELEASE.md** dosyasında.
- Depo: https://github.com/esbora/BnX-Raptor (herkese açık).
- Güncelleme elle kurulur; program yeni sürüm olduğunda sadece uyarır.

## 8. Durum

- [x] 0.1 – Sigorta mektubu → PDF/A → Outlook/.eml taslağı, kontrol penceresi, işlem geçmişi
- [x] 0.2 – Büro bilgileri ve logo, imza, müvekkile kopya, Akten sekmesi, gelen cevapları içe aktarma, güncelleme uyarısı, GitHub release
- [x] 0.3 – Versicherer-Adressbuch; numara seçimi (Versicherungsnummer / Schaden-Nr., konu türe göre); büro adresi otomatik hariç; Word zaman sınırı (kod `v0.3.0-entwicklung` dalında; `main`'e birleştirme = otomatik Release, ayrı onay gerekir)
- [x] Windows'ta hayali mektuplarla test (Word → kontrol penceresi → PDF/A → klasik Outlook)
- [x] Büro şablonunun anonim kopyasıyla test (2026-11-16): sigorta adı, alıcı, numara türü, PDF anteti, klasik Outlook taslağı (konu + ek). Şablonda içerik denetimi yok; numara/e-posta sarı vurgulu (PDF'te de görünür); sağ sütundaki metin kutusu sabit yükseklikte ve taşıyor → "Aktenzeichen" değeri Word'de ve PDF'te görünmüyor (şablon düzeltmesi, kod değil)
- [ ] **Bekliyor:** Yeni Outlook ile doğrudan doğrulama (bu bilgisayarda yeni Outlook'ta hesap yok)
- [ ] **Bekliyor:** Büro bilgisayarında gerçek şablonla son kontrol (Word/Outlook sürümü, Office oturumu)
- [x] GitHub deposu: https://github.com/esbora/BnX-Raptor (herkese açık); `update_repo` varsayılan olarak ayarlı
- [ ] Büronun Word şablonuna içerik denetimlerinin eklenmesi
- [x] 0.4 Faz 0 – PDF motoru prototipi (`v0.4.0-pdf` dalı, yalnızca yerel; 2026-11-17): dijital PDF'te cümle değiştirme,
  deu/tur/eng OCR + taranmış sayfada kelime düzeltme, kalıcı karartma, önizlemeli Outlook taslağı – normal uygulamada
  ve paketli EXE'de geçti. ZIP 49,1 → 112,7 MB. Ayrıntı: aşağıda „Açık kararlar“.
- [x] 0.4.0 (yerel `v0.4.0-pdf`, 2026-11-17): PDF-Editor Faz 1 (sayfalar, gerçek metin değiştirme, deu/tur/eng OCR,
  taranmış kelime düzeltme, kalıcı karartma + kayıt sonrası doğrulama, geri al, „Speichern unter…“) ve
  Anlagen-Assistent (tek ekran, Anlage K1…, Anlagenverzeichnis.docx, Outlook ek doğrulaması). Hayali dilekçe + 10 ekle
  uçtan uca kabul testi normal uygulamada ve paketli EXE'de geçti. Eğiklik düzeltme (deskew) YOK.
- [ ] **Bekliyor:** `release.yml` 0.4 paketine uyarlanmadı (ocr\ klasörü, PyMuPDF ek paketlerinin hariç tutulması,
  lisans metinleri) – lisans/dağıtım kararından sonra. Şu an `main`'e birleştirme bozuk/eksik bir EXE üretir.
- [ ] **Bekliyor:** Büro pilotu: elle yöntem ile Anlagen-Assistent arasında insanla süre ölçümü.

## 9. Yol haritası (her madde ayrı onayla yapılır)

**Kısa vade**
1. ~~**Versicherer-Adressbuch**~~ – 0.3.0'da yapıldı.
2. **Kendi dosya numarası (Aktenzeichen):** Konu satırına ve dosya adına eklenir; Akten listesinde aranabilir.
3. ~~**Ekleri tek PDF'te birleştirme**~~ – 0.4.0 Anlagen-Assistent (ayrı PDF'ler + isteğe bağlı iç kontrol PDF'i).
   Açık: Anlage damgası (sayfaya „Anlage K1“ yazısı), boyut kontrolü (beA sınırları).
4. **Textbausteine:** Her iş akışı için birden fazla e-posta metni; kontrol penceresinde seçilir.
5. **Word düğmesi:** Word menü şeridinde, aktif belgeyi kaydedip programa gönderen bir makro.

**Orta vade**
6. **Wiedervorlage / süre takibi:** Taslakla birlikte Outlook'ta hatırlatma görevi oluşturulur; Akten'de cevap gelmeyen dosyalar vurgulanır.
7. **Gönderildi kontrolü:** "Gesendete Elemente" klasörü taranır ve günlükte "gesendet" olarak işaretlenir.
8. **Otomatik cevap kontrolü:** Program açıkken belirli aralıklarla Outlook taranır (onaylı içe aktarma yine kullanıcıda kalır).
9. **Toplu işlem:** Birden fazla mektup tek bir kontrol tablosunda onaylanır.
10. **Diğer iş akışları:** Müvekkile yazı, karşı tarafa yazı, mahkeme yazısı (beA hazırlığı).

**0.4 sonrası (Anlagen-Assistent'ten sonra)**
- **Outlook → Akte:** Outlook'ta seçilen e-posta ve ekleri dava klasörüne kaydetme.
- **beA ZIP → Akte:** beA'dan indirilen yerel ZIP'i içe aktarma (internet bağlantısı yok).
- **Sachstandsanfrage / Unterlagen nachreichen / Erinnerung:** tek tıkla Almanca taslak (gönderilmez).

**Uzun vade**
11. Büro yazılımı entegrasyonu (RA-MICRO / Advoware / j-lawyer).
12. Çok kullanıcı: `daten_ordner` ağ sürücüsünde; SQLite'tan sunucu veritabanına geçiş değerlendirilir.
13. Kurulum programı (Inno Setup) ve kod imzalama.
14. Günlük kayıtları için saklama süresi ve silme (DSGVO).

## 10. Açık sorular (proje sahibinin cevabı bekleniyor)

- Büroda klasik Outlook mu, yeni Outlook mu kullanılıyor? (Bilinmiyor; program iki durumu da destekliyor ve kendisi algılıyor.)
- Hangi büro yazılımı kullanılıyor? Dava klasörleri nerede ve nasıl adlandırılıyor?
- Program kaç kişi tarafından, kaç bilgisayarda kullanılacak? Ortak ağ sürücüsü var mı?
- Konu satırına büronun kendi dosya numarası da eklensin mi?
- Program ileride başka bürolara da verilecek mi? (Lisans ve kurulumu etkiler.)

## 11. Açık kararlar – PDF motoru ve dağıtım lisansı (proje sahibi verecek)

Durum 2026-11-17: Faz 0 prototipi onaylandı ve yerelde geçti. **Proje lisansı değiştirilmedi, ücretli lisans alınmadı,
0.4 kodu GitHub'a yüklenmedi, PyMuPDF/Tesseract içeren EXE dağıtılmadı.** Bu karar verilene kadar öyle kalır.

| Bileşen | Sürüm | Lisans | Pakete etkisi |
|---|---|---|---|
| PyMuPDF (MuPDF) | 2.1 / 1.28.6 | AGPL-3.0 **veya** Artifex ticari lisansı (fiyat yayımlanmıyor, teklif usulü) | +18,6 MB ZIP; `layout`/onnxruntime ve `mupdf-devel` pakete alınmaz |
| Tesseract | 5.5.3 (resmî Windows kurulumu, SHA-256 doğrulandı) | Apache-2.0 | `ocr\` klasörü 86,5 MB (exe + 33 DLL + deu/tur/eng `tessdata_best` + osd), +45 MB ZIP |

- Öneri (Claude): BnX-Raptor'ı AGPL-3.0 ile lisanslamak (depo zaten açık, maliyet yok). Alternatif: Artifex'ten teklif almak.
- Tesseract'ın yanında gelen MinGW/MSYS2 DLL'lerinin lisansları (ör. libjbig GPL, libiconv/libintl LGPL, libstdc++ GCC
  Runtime Exception) dağıtımdan önce tek tek listelenmeli ve `lizenzen\` klasörüne konmalı.
- Karar bekleyen sorular: (1) proje lisansı, (2) PyMuPDF+Tesseract içeren paketin dağıtımı, (3) 0.4 dalının GitHub'a yüklenmesi.
