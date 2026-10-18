# Spotify Liste Takip

Spotify çalma listelerinden şarkılar "kendiliğinden" kayboluyor mu? Bu program listelerinin geçmişini tutar:
hangi şarkı **ne zaman eklendi**, hangisi **ne zaman çıktı**, hangisi **artık çalınamaz** hale geldi.

Spotify bir şarkının listeden ne zaman çıktığını saklamaz. Program her kontrolde listenin o anki halini kaydeder
ve bir önceki kontrolle karşılaştırır. Böylece kaybolan şarkıların adı, sanatçısı ve listeye eklenme tarihi elinde kalır.

## Özellikler

- Spotify hesabınla giriş yapıp listelerini (gizli listeler dahil) tek tuşla getirme
- İstediğin listeleri işaretleyip takip etme
- Her kontrolde değişiklik raporu:
  - **+ Eklendi**: listeye yeni gelen şarkı ve eklenme tarihi
  - **− Çıktı**: listeden kaybolan şarkı, ne zaman eklendiği ve en son ne zaman görüldüğü
  - **! Oynatılamaz**: listede duran ama artık Türkiye'de çalınamayan şarkı (lisans süresi biten şarkılar Spotify'da gri görünür ya da gizlenir; kaybolan şarkıların çoğu aslında bunlardır)
  - **✓ Düzeldi**: tekrar çalınabilir hale gelen şarkı
- Liste ve olay türüne göre süzülebilen geçmiş ekranı
- Geçmişi Excel'de açılabilen CSV dosyasına aktarma
- Ek kurulum yok: sadece Python'un kendi kütüphaneleri kullanılır

## Gereksinimler

- Windows, macOS veya Linux
- [Python 3.9+](https://www.python.org/downloads/). Windows'ta kurarken "Add Python to PATH" kutusunu işaretleyin.
- Bir Spotify hesabı. Spotify, geliştirici uygulaması oluşturan hesabın **Premium** olmasını istiyor.

## Kurulum

### 1. Dosyaları indir

```
git clone https://github.com/Xendoksia/Spotify-Follow-Ur-List.git
```

ya da GitHub'da **Code → Download ZIP** ile indirip bir klasöre çıkar.

### 2. Spotify geliştirici uygulaması oluştur (bir kerelik)

1. https://developer.spotify.com/dashboard adresine Spotify hesabınla giriş yap.
2. **Create app** butonuna bas ve formu doldur:
   - **App name / description:** istediğin herhangi bir şey
   - **Redirect URI:** `http://127.0.0.1:8888/callback` yaz ve **Add**'e bas. Birebir aynı olmalı.
   - **Which API/SDKs:** **Web API**'yi işaretle
3. Kaydet, sonra uygulamanın **Settings** sayfasından **Client ID** ve **Client Secret** değerlerini kopyala.

### 3. Programı çalıştır

```
python uygulama.py
```

Windows'ta **`Spotify Liste Takip.bat`** dosyasına çift tıklaman da yeterli.

İlk açılışta çıkan ayar penceresine Client ID ve Client Secret değerlerini gir. Sonra **Spotify ile giriş yap**
butonuna bas ve tarayıcıda açılan sayfada onay ver. Bunu bir kere yapman yeterli, program oturumu hatırlar.

## Kullanım

1. **Spotify'daki listelerimi getir** butonuna bas.
2. Takip etmek istediğin listelerin **☐** kutucuğuna tıkla. Bir listeye çift tıklarsan Spotify'da açılır.
3. **▶ Seçilenleri kontrol et** butonuna bas.
4. Sonuçları **Geçmiş** sekmesinde gör, istersen **CSV'ye aktar**.

Her listenin ilk kontrolü başlangıç kaydını alır. Değişiklikler ikinci kontrolden itibaren görünür.
Ne kadar sık kontrol edersen bir şarkının ne zaman çıktığını o kadar kesin bilirsin.

### Komut satırı

```
python spotify.py giris                                      # Spotify hesabıyla giriş
python spotify.py kontrol https://open.spotify.com/playlist/...  # listeyi kontrol et
python spotify.py gecmis                                     # geçmişi yazdır
python spotify.py csv gecmis.csv                             # geçmişi CSV'ye aktar
```

Komut satırı kullanılacaksa önce `config.example.json` dosyasını `config.json` adıyla kopyalayıp
Client ID ve Client Secret değerlerini içine yaz.

## Sınırlamalar

- **Sadece kendi listelerin:** Spotify'ın 2026 kurallarına göre program sadece **senin oluşturduğun veya ortak
  düzenlediğin** listelerin şarkılarını okuyabilir. Başkalarının listeleri, takip etsen bile kontrol edilemez.
- **Kontrol sıklığı:** Program sadece sen çalıştırdığında kontrol yapar. Bir şarkının çıkış zamanı "bir önceki kontrol
  ile bu kontrol arasında" olarak görünür.
- **Kullanıcı sınırı:** Spotify'ın geliştirici modunda bir uygulamayla en fazla 5 kişi giriş yapabilir. Bu yüzden
  herkesin kendi Client ID'sini oluşturması gerekir.

## Veriler ve gizlilik

Bütün veriler sadece senin bilgisayarında, program klasöründe durur:

| Dosya | İçerik |
|---|---|
| `config.json` | Client ID, Client Secret ve Spotify oturumu. **Kimseyle paylaşma.** |
| `gecmis.db` | Listelerinin ve değişikliklerin geçmişi (SQLite) |

İkisi de `.gitignore` dosyasında listelendiği için GitHub'a gönderilmez. Program, Spotify dışında hiçbir yere bağlanmaz.

## Dosyalar

| Dosya | Açıklama |
|---|---|
| `uygulama.py` | Pencereli arayüz (tkinter) |
| `spotify.py` | Spotify bağlantısı, karşılaştırma mantığı, veritabanı ve komut satırı |
| `Spotify Liste Takip.bat` | Windows'ta çift tıklayıp açmak için |
| `config.example.json` | Komut satırı için örnek ayar dosyası |

## Lisans

[MIT](LICENSE): serbestçe kullanabilir, değiştirebilir ve paylaşabilirsin.

---

Bu proje Spotify ile bağlantılı değildir ve Spotify tarafından onaylanmamıştır.
Spotify verileri [Spotify Web API](https://developer.spotify.com/documentation/web-api) üzerinden alınır.
