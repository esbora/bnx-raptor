# CLAUDE.md – BnX-Raptor

Bu dosya Claude Code için proje talimatıdır. Her oturumun başında okunur.

## 1. Proje nedir?

**BnX-Raptor**, Almanya'daki bir avukatlık bürosu için yazılmış bir **Windows masaüstü programıdır**.
Amacı avukatın tekrar eden yazışma işlerini tek ekrandan, birkaç tıklamayla yapmaktır.
Program zamanla büyüyecek; her yeni iş ayrı bir **iş akışı (workflow) modülü** olarak eklenecek.

Mevcut sürüm: `version.py` dosyasına bakın (şu an 0.2.0). Değişiklikler `CHANGELOG.md` dosyasında.

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
- Veri: SQLite (`verlauf.sqlite`, tablolar `vorgaenge` ve `akten`), büro bilgileri `kanzlei.json` ve logo dosyası
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
  extractor.py          metinden e-posta/numara bulma            [saf Python]
  eingang.py            numara eşleştirme, .eml okuma, dosya adı  [saf Python]
  kanzlei.py            Kanzlei verisi, IBAN/USt-IdNr. kontrolü, imza HTML'i  [saf Python]
  update.py             sürüm karşılaştırma, GitHub sorgusu       [saf Python]
  journal.py            SQLite: vorgaenge (art: ausgang|mandant|eingang|entwurf) + akten
  entwurf.py            entwurf_erstellen(ctx, MailDraft, eml_klasoru) – TÜM taslaklar buradan geçer
  mail_service.py       OutlookClassicDrafter, EmlDrafter       [COM / saf]
  word_service.py       Word okuma, PDF/A                        [COM]
  outlook_eingang.py    gelen kutusu arama, .msg kaydetme        [COM]
  eingang_service.py    gelen e-postayı kaydetme + günlüğe yazma
workflows/
  base.py               AppContext(cfg, kanzlei_store, journal), Workflow, Field, Result
  __init__.py           ALL_WORKFLOWS kaydı
  versicherung_brief.py iş akışı 1 (+ isteğe bağlı müvekkil kopyası)
ui/
  main_window.py        sekmeler: Bearbeiten / Akten / Verlauf; menüler; güncelleme şeridi
  akten_tab.py          dosya listesi, dosya geçmişi, içe aktarma, e-posta taslağı
  kanzlei_dialog.py     büro bilgileri + logo + imza önizlemesi
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
- [ ] Windows'ta gerçek bir büro mektubuyla ilk test (arama kalıplarının ayarlanması)
- [x] GitHub deposu: https://github.com/esbora/BnX-Raptor (herkese açık); `update_repo` varsayılan olarak ayarlı
- [ ] Büronun Word şablonuna içerik denetimlerinin eklenmesi

## 9. Yol haritası (her madde ayrı onayla yapılır)

**Kısa vade**
1. **Versicherer-Adressbuch:** Sigorta adı → e-posta adresi. Onaylanan işlemlerden öğrenir.
2. **Kendi dosya numarası (Aktenzeichen):** Konu satırına ve dosya adına eklenir; Akten listesinde aranabilir.
3. **Ekleri tek PDF'te birleştirme:** Ekler damgalanır (Anlage K1, K2 …); boyut kontrolü yapılır.
4. **Textbausteine:** Her iş akışı için birden fazla e-posta metni; kontrol penceresinde seçilir.
5. **Word düğmesi:** Word menü şeridinde, aktif belgeyi kaydedip programa gönderen bir makro.

**Orta vade**
6. **Wiedervorlage / süre takibi:** Taslakla birlikte Outlook'ta hatırlatma görevi oluşturulur; Akten'de cevap gelmeyen dosyalar vurgulanır.
7. **Gönderildi kontrolü:** "Gesendete Elemente" klasörü taranır ve günlükte "gesendet" olarak işaretlenir.
8. **Otomatik cevap kontrolü:** Program açıkken belirli aralıklarla Outlook taranır (onaylı içe aktarma yine kullanıcıda kalır).
9. **Toplu işlem:** Birden fazla mektup tek bir kontrol tablosunda onaylanır.
10. **Diğer iş akışları:** Müvekkile yazı, karşı tarafa yazı, mahkeme yazısı (beA hazırlığı).

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
