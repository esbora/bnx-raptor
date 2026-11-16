# Yeni sürüm yayınlama (Release)

Sürüm numarası **MAJOR.MINOR.PATCH** biçimindedir (ör. `0.3.1`):
- **PATCH** (0.3.0 → 0.3.1): hata düzeltmesi
- **MINOR** (0.3.1 → 0.4.0): yeni özellik
- **MAJOR** (0.x → 1.0.0): büyük değişiklik / ilk kararlı sürüm

## Adımlar

1. `version.py` içindeki numarayı artırın: `__version__ = "0.3.0"`
2. `CHANGELOG-aktuell.md` dosyasına bu sürümdeki yenilikleri **Almanca** yazın
   (avukat bunu güncelleme penceresinde görür). Aynı metni `CHANGELOG.md` dosyasının en üstüne ekleyin.
3. Testleri çalıştırın: `python -m pytest -q tests`
4. Kaydedip etiketleyin:
   ```
   git add -A
   git commit -m "Release 0.3.0"
   git tag v0.3.0
   git push
   git push --tags
   ```
5. GitHub kendisi `.exe` dosyasını oluşturur ve **Releases** sayfasına `BnX-Raptor-v0.3.0.zip` yükler
   (5–10 dakika). Durumu GitHub'da **Actions** sekmesinden izleyebilirsiniz.

Etiket ile `version.py` uyuşmazsa yayın bilerek durdurulur.

## Büroda güncelleme (elle)

Program açılırken GitHub'daki son sürüme bakar. Yeni sürüm varsa üstte sarı bir uyarı şeridi çıkar.
Şeride tıklanınca değişiklikler gösterilir ve **Herunterladen** düğmesi ZIP dosyasını indirir.

1. BnX-Raptor'u kapatın.
2. ZIP dosyasını açın, içindeki dosyaları program klasörüne kopyalayın (üzerine yazın).
3. Programı yeniden başlatın.

`config.json`, büro bilgileri, logo ve dosyalar (Akten) korunur. ZIP içinde `config.json` yoktur,
diğerleri ise `%APPDATA%\BnX-Raptor` klasöründedir.

## Önemli: depo görünürlüğü

Güncelleme kontrolü GitHub'a giriş yapmadan çalışır. Bunun için
**Releases kısmının herkese açık olması** gerekir:
- Seçenek A: kod deposu herkese açık (kodda büro ya da müvekkil verisi yoktur).
- Seçenek B: kod gizli bir depoda kalır, ZIP dosyaları ayrı ve herkese açık bir
  "BnX-Raptor-Releases" deposunda yayınlanır.

`config.json` → `"update_repo": "kullanici/depo"`
