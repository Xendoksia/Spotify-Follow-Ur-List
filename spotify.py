"""
Spotify çalma listesi geçmiş takipçisi (çekirdek + komut satırı).

Her kontrolde listenin o anki halini alır, bir önceki kayıtla karşılaştırır ve
eklenen / çıkan / oynatılamaz hale gelen şarkıları tarih-saatiyle birlikte
veritabanına (gecmis.db) yazar. Pencereli arayüz için: python uygulama.py

Komut satırı kullanımı:
    python spotify.py giris                            -> Spotify hesabıyla giriş (bir kere)
    python spotify.py kontrol <playlist linki> [...]   -> listeyi kontrol et, değişiklikleri kaydet
    python spotify.py gecmis  [playlist linki]         -> kayıtlı değişiklik geçmişini göster
    python spotify.py csv     [dosya.csv]              -> tüm geçmişi CSV'ye aktar

Gerekli: config.json (CLIENT_ID ve CLIENT_SECRET) – bkz. config.example.json
"""

import base64
import csv
import json
import re
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

KLASOR = Path(__file__).resolve().parent
DB_YOLU = KLASOR / "gecmis.db"
CONFIG_YOLU = KLASOR / "config.json"
PAZAR = "TR"  # şarkının Türkiye'de oynatılabilir olup olmadığını kontrol etmek için


YONLENDIRME = "http://127.0.0.1:8888/callback"  # Spotify Dashboard'daki Redirect URI ile birebir aynı olmalı
IZINLER = "playlist-read-private playlist-read-collaborative"


class SpotifyHatasi(Exception):
    pass


class GirisGerekli(SpotifyHatasi):
    pass


# ---------------------------------------------------------------- Ayarlar

def ayarlari_oku():
    if CONFIG_YOLU.exists():
        return json.loads(CONFIG_YOLU.read_text(encoding="utf-8"))
    return {}


def ayarlari_yaz(ayar):
    CONFIG_YOLU.write_text(json.dumps(ayar, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- Spotify API

class Spotify:
    def __init__(self, client_id, client_secret):
        if not client_id or not client_secret:
            raise SpotifyHatasi("CLIENT_ID ve CLIENT_SECRET girilmemiş.")
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = None
        self._token_bitis = 0

    def token_istegi(self, veri):
        kimlik = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        istek = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=urllib.parse.urlencode(veri).encode(),
            headers={"Authorization": f"Basic {kimlik}"},
        )
        try:
            with urllib.request.urlopen(istek, timeout=30) as yanit:
                return json.load(yanit)
        except urllib.error.HTTPError as hata:
            govde = hata.read().decode(errors="replace")
            if "invalid_client" in govde:
                raise SpotifyHatasi("Client ID / Client Secret hatalı. Ayarlar'dan kontrol edin.")
            if "invalid_grant" in govde:
                ayar = ayarlari_oku()
                ayar.pop("REFRESH_TOKEN", None)
                ayarlari_yaz(ayar)
                raise GirisGerekli("Spotify oturumu sona ermiş, tekrar giriş yapın.")
            raise SpotifyHatasi(f"Spotify girişi başarısız ({hata.code}): {govde}")
        except urllib.error.URLError as hata:
            raise SpotifyHatasi(f"Spotify'a bağlanılamadı: {hata.reason}")

    def _token_al(self):
        if self._token and time.time() < self._token_bitis:
            return self._token
        ayar = ayarlari_oku()
        if not ayar.get("REFRESH_TOKEN"):
            raise GirisGerekli("Önce “Spotify ile giriş yap” butonuyla giriş yapın.")
        veri = self.token_istegi({"grant_type": "refresh_token", "refresh_token": ayar["REFRESH_TOKEN"]})
        if veri.get("refresh_token") and veri["refresh_token"] != ayar["REFRESH_TOKEN"]:
            ayar["REFRESH_TOKEN"] = veri["refresh_token"]
            ayarlari_yaz(ayar)
        self._token = veri["access_token"]
        self._token_bitis = time.time() + veri.get("expires_in", 3600) - 60
        return self._token

    def giris_yap(self, zaman_asimi=180):
        """Tarayıcıda Spotify onay sayfasını açar, dönüşü yerel sunucuyla yakalar, oturumu kaydeder."""
        durum = secrets.token_urlsafe(16)
        gelen = {}

        class Isleyici(BaseHTTPRequestHandler):
            def do_GET(self):
                adres = urllib.parse.urlparse(self.path)
                if adres.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                gelen.update({k: v[0] for k, v in urllib.parse.parse_qs(adres.query).items()})
                basarili = "code" in gelen
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                mesaj = ("Giriş tamamlandı, bu sekmeyi kapatıp programa dönebilirsiniz." if basarili
                         else "Giriş iptal edildi veya başarısız oldu.")
                self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'>"
                                 f"<h2>{mesaj}</h2></body></html>".encode("utf-8"))

            def log_message(self, *args):
                pass

        try:
            sunucu = HTTPServer(("127.0.0.1", 8888), Isleyici)
        except OSError:
            raise SpotifyHatasi("8888 portu kullanımda. Açık kalan başka bir giriş penceresi varsa kapatıp tekrar deneyin.")
        sunucu.timeout = 1
        webbrowser.open("https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": YONLENDIRME,
            "scope": IZINLER, "state": durum,
        }))
        bitis = time.time() + zaman_asimi
        try:
            while "code" not in gelen and "error" not in gelen and time.time() < bitis:
                sunucu.handle_request()
        finally:
            sunucu.server_close()

        if "error" in gelen:
            if gelen["error"] == "access_denied":
                raise SpotifyHatasi("Giriş iptal edildi.")
            raise SpotifyHatasi(f"Spotify girişi başarısız: {gelen['error']}")
        if "code" not in gelen:
            raise SpotifyHatasi("Giriş zaman aşımına uğradı. Tarayıcıda onay sayfası açılmadıysa "
                                "Dashboard'daki Redirect URI'nin tam olarak " + YONLENDIRME + " olduğunu kontrol edin.")
        if gelen.get("state") != durum:
            raise SpotifyHatasi("Giriş doğrulanamadı, tekrar deneyin.")

        veri = self.token_istegi({"grant_type": "authorization_code", "code": gelen["code"],
                                  "redirect_uri": YONLENDIRME})
        ayar = ayarlari_oku()
        ayar["REFRESH_TOKEN"] = veri["refresh_token"]
        self._token = veri["access_token"]
        self._token_bitis = time.time() + veri.get("expires_in", 3600) - 60
        ben = self.get("/me")
        ayar["KULLANICI"] = ben.get("display_name") or ben.get("id")
        ayarlari_yaz(ayar)
        return ayar["KULLANICI"]

    def get(self, url):
        if not url.startswith("http"):
            url = "https://api.spotify.com/v1" + url
        for deneme in range(3):
            istek = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._token_al()}"})
            try:
                with urllib.request.urlopen(istek, timeout=30) as yanit:
                    return json.load(yanit)
            except urllib.error.HTTPError as hata:
                if hata.code == 429 and deneme < 2:  # çok hızlı istek: Spotify'ın söylediği kadar bekle
                    time.sleep(int(hata.headers.get("Retry-After", "2")))
                    continue
                govde = hata.read().decode(errors="replace")
                raise SpotifyHatasi(f"Spotify API hatası {hata.code}: {govde}", ) from hata
            except urllib.error.URLError as hata:
                raise SpotifyHatasi(f"Spotify'a bağlanılamadı: {hata.reason}")

    def kendi_listelerim(self):
        """Giriş yapan hesabın listeleri (gizliler dahil).
        Spotify sadece sahibi olunan / ortak düzenlenen listelerin şarkılarını verdiği için
        başkalarının takip edilen listeleri ayrı döndürülür."""
        ben = self.get("/me")
        benim, baskasinin = [], []
        url = "/me/playlists?limit=50"
        while url:
            sayfa = self.get(url)
            for p in sayfa.get("items") or []:
                if not p or not p.get("id"):
                    continue
                sahip = p.get("owner") or {}
                toplam = (p.get("items") or p.get("tracks") or {}).get("total")
                liste = {
                    "id": p["id"],
                    "ad": p.get("name") or p["id"],
                    "sahip": sahip.get("display_name") or sahip.get("id") or "",
                    "sarki_sayisi": toplam if toplam is not None else "",
                }
                (benim if sahip.get("id") == ben.get("id") or p.get("collaborative") else baskasinin).append(liste)
            url = sayfa.get("next")
        return benim, baskasinin

    def liste_adi(self, playlist_id):
        try:
            return self.get(f"/playlists/{playlist_id}?fields=name").get("name") or playlist_id
        except SpotifyHatasi as hata:
            if "404" in str(hata):
                raise SpotifyHatasi("Liste bulunamadı. Liste herkese açık (public) mı? Link doğru mu?")
            raise

    def liste_sarkilari(self, playlist_id):
        parametre = urllib.parse.urlencode({"limit": 100, "market": PAZAR})
        try:
            sayfa = self.get(f"/playlists/{playlist_id}/items?{parametre}")
        except SpotifyHatasi as hata:
            if "403" in str(hata):
                raise SpotifyHatasi("Spotify bu listenin şarkılarını vermiyor: sadece sahibi olduğunuz "
                                    "veya ortak düzenlediğiniz listeler kontrol edilebilir.")
            raise
        sarkilar = []
        while True:
            for oge in sayfa.get("items") or []:
                parca = oge.get("track") or oge.get("item")
                if not parca or not parca.get("uri"):
                    continue
                sarkilar.append({
                    # Aynı şarkı silinip tekrar eklenirse added_at değişir; bu yüzden anahtar ikisinin birleşimi
                    "anahtar": f"{parca['uri']}|{oge.get('added_at')}",
                    "uri": parca["uri"],
                    "ad": parca.get("name") or "(isimsiz)",
                    "sanatci": ", ".join(a["name"] for a in parca.get("artists") or [] if a.get("name")),
                    "album": (parca.get("album") or {}).get("name") or "",
                    "eklenme": oge.get("added_at") or "",
                    "ekleyen": (oge.get("added_by") or {}).get("id") or "",
                    "oynatilabilir": 0 if parca.get("is_playable") is False else 1,
                })
            if not sayfa.get("next"):
                return sarkilar
            sayfa = self.get(sayfa["next"])


def spotify_baglan():
    ayar = ayarlari_oku()
    return Spotify(ayar.get("CLIENT_ID"), ayar.get("CLIENT_SECRET"))


def playlist_id_bul(link):
    eslesme = re.search(r"playlist[/:]([A-Za-z0-9]{22})", link)
    if eslesme:
        return eslesme.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{22}", link.strip()):
        return link.strip()
    raise SpotifyHatasi(f"Geçerli bir Spotify playlist linki değil: {link}")


# ---------------------------------------------------------------- Veritabanı

def db_ac():
    db = sqlite3.connect(DB_YOLU)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS listeler (
            playlist_id TEXT PRIMARY KEY,
            ad TEXT,
            son_kontrol TEXT
        );
        CREATE TABLE IF NOT EXISTS sarkilar (
            playlist_id TEXT,
            anahtar TEXT,
            uri TEXT, ad TEXT, sanatci TEXT, album TEXT,
            eklenme TEXT, ekleyen TEXT,
            oynatilabilir INTEGER,
            ilk_gorulme TEXT,
            son_gorulme TEXT,
            listede INTEGER,
            PRIMARY KEY (playlist_id, anahtar)
        );
        CREATE TABLE IF NOT EXISTS olaylar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id TEXT,
            zaman TEXT,
            olay TEXT,
            uri TEXT, ad TEXT, sanatci TEXT, album TEXT,
            eklenme TEXT
        );
    """)
    # Takip listesi (arayüzde işaretlenen listeler)
    sutunlar = {r["name"] for r in db.execute("PRAGMA table_info(listeler)")}
    if "takipte" not in sutunlar:
        db.execute("ALTER TABLE listeler ADD COLUMN takipte INTEGER DEFAULT 0")
        db.commit()
    return db


def takip_listesi():
    with db_ac() as db:
        return [dict(r) for r in db.execute("SELECT * FROM listeler WHERE takipte = 1 ORDER BY ad")]


def takip_ayarla(playlist_id, ad, takipte):
    with db_ac() as db:
        db.execute(
            "INSERT INTO listeler (playlist_id, ad, takipte) VALUES (?, ?, ?) "
            "ON CONFLICT(playlist_id) DO UPDATE SET ad = excluded.ad, takipte = excluded.takipte",
            (playlist_id, ad, 1 if takipte else 0),
        )


def olay_yaz(db, playlist_id, zaman, olay, s):
    db.execute(
        "INSERT INTO olaylar (playlist_id, zaman, olay, uri, ad, sanatci, album, eklenme) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (playlist_id, zaman, olay, s.get("uri", ""), s.get("ad", ""), s.get("sanatci", ""),
         s.get("album", ""), s.get("eklenme", "")),
    )


def olaylari_getir(playlist_id=None):
    sorgu = "SELECT o.*, l.ad AS liste FROM olaylar o LEFT JOIN listeler l USING (playlist_id)"
    parametre = ()
    if playlist_id:
        sorgu += " WHERE o.playlist_id = ?"
        parametre = (playlist_id,)
    with db_ac() as db:
        return [dict(r) for r in db.execute(sorgu + " ORDER BY o.id DESC", parametre)]


def tarih(iso):
    """ISO tarihini okunur hale getirir (UTC -> yerel saat)."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso


def sarki_yazi(s):
    return f"{s['sanatci']} - {s['ad']}" if s.get("sanatci") else s.get("ad", "")


# ---------------------------------------------------------------- Kontrol

def kontrol(sp, playlist_id):
    """Listeyi çeker, önceki kayıtla karşılaştırır, olayları yazar ve sonucu döndürür."""
    liste_adi = sp.liste_adi(playlist_id)
    guncel = sp.liste_sarkilari(playlist_id)
    simdi = datetime.now().astimezone().isoformat(timespec="seconds")

    with db_ac() as db:
        satir = db.execute("SELECT son_kontrol FROM listeler WHERE playlist_id = ?", (playlist_id,)).fetchone()
        ilk_kez = satir is None or satir["son_kontrol"] is None
        db.execute(
            "INSERT INTO listeler (playlist_id, ad, son_kontrol) VALUES (?, ?, ?) "
            "ON CONFLICT(playlist_id) DO UPDATE SET ad = excluded.ad, son_kontrol = excluded.son_kontrol",
            (playlist_id, liste_adi, simdi),
        )

        onceki = {
            r["anahtar"]: dict(r)
            for r in db.execute("SELECT * FROM sarkilar WHERE playlist_id = ? AND listede = 1", (playlist_id,))
        }
        guncel_map = {s["anahtar"]: s for s in guncel}

        sonuc = {
            "playlist_id": playlist_id,
            "ad": liste_adi,
            "toplam": len(guncel),
            "ilk_kez": ilk_kez,
            "eklenen": [s for k, s in guncel_map.items() if k not in onceki],
            "cikan": [s for k, s in onceki.items() if k not in guncel_map],
            "bozulan": [s for k, s in guncel_map.items()
                        if k in onceki and onceki[k]["oynatilabilir"] and not s["oynatilabilir"]],
            "duzelen": [s for k, s in guncel_map.items()
                        if k in onceki and not onceki[k]["oynatilabilir"] and s["oynatilabilir"]],
            "kapali": [s for s in guncel if not s["oynatilabilir"]],
        }

        for s in guncel:
            db.execute(
                "INSERT INTO sarkilar (playlist_id, anahtar, uri, ad, sanatci, album, eklenme, ekleyen, "
                "oynatilabilir, ilk_gorulme, son_gorulme, listede) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1) "
                "ON CONFLICT(playlist_id, anahtar) DO UPDATE SET ad = excluded.ad, sanatci = excluded.sanatci, "
                "album = excluded.album, oynatilabilir = excluded.oynatilabilir, "
                "son_gorulme = excluded.son_gorulme, listede = 1",
                (playlist_id, s["anahtar"], s["uri"], s["ad"], s["sanatci"], s["album"], s["eklenme"],
                 s["ekleyen"], s["oynatilabilir"], simdi, simdi),
            )
        for s in sonuc["cikan"]:
            db.execute("UPDATE sarkilar SET listede = 0 WHERE playlist_id = ? AND anahtar = ?",
                       (playlist_id, s["anahtar"]))

        if ilk_kez:
            olay_yaz(db, playlist_id, simdi, "ILK_KAYIT", {"ad": f"{len(guncel)} şarkı kaydedildi"})
            sonuc.update(eklenen=[], cikan=[], bozulan=[], duzelen=[])
        else:
            for olay, anahtar in (("EKLENDI", "eklenen"), ("CIKTI", "cikan"),
                                  ("OYNATILAMAZ", "bozulan"), ("TEKRAR_OYNATILABILIR", "duzelen")):
                for s in sonuc[anahtar]:
                    olay_yaz(db, playlist_id, simdi, olay, s)
    return sonuc


def csv_aktar(dosya="gecmis.csv"):
    satirlar = list(reversed(olaylari_getir()))
    # utf-8-sig + ';' ayırıcı: Türkçe Excel'de doğrudan düzgün açılır
    with open(dosya, "w", newline="", encoding="utf-8-sig") as f:
        yazici = csv.writer(f, delimiter=";")
        yazici.writerow(["Kontrol zamanı", "Liste", "Olay", "Sanatçı", "Şarkı", "Albüm", "Listeye eklenme", "URI"])
        for r in satirlar:
            yazici.writerow([tarih(r["zaman"]), r["liste"], r["olay"], r["sanatci"], r["ad"],
                             r["album"], tarih(r["eklenme"]), r["uri"]])
    return len(satirlar)


# ---------------------------------------------------------------- Komut satırı

def _sonuc_yazdir(sonuc):
    print(f"Liste: {sonuc['ad']}  ({sonuc['toplam']} şarkı)")
    if sonuc["ilk_kez"]:
        print("İlk kayıt alındı. Bundan sonraki kontrollerde değişiklikler kaydedilecek.")
        for s in sonuc["kapali"]:
            print(f"   ! Türkiye'de oynatılamıyor: {sarki_yazi(s)}")
        return
    if not (sonuc["eklenen"] or sonuc["cikan"] or sonuc["bozulan"] or sonuc["duzelen"]):
        print("Değişiklik yok.")
    for s in sonuc["eklenen"]:
        print(f"  + EKLENDİ      {sarki_yazi(s)}   (eklenme: {tarih(s['eklenme'])})")
    for s in sonuc["cikan"]:
        print(f"  - ÇIKTI        {sarki_yazi(s)}   (eklenmişti: {tarih(s['eklenme'])}, "
              f"son görülme: {tarih(s['son_gorulme'])})")
    for s in sonuc["bozulan"]:
        print(f"  ! OYNATILAMAZ  {sarki_yazi(s)}")
    for s in sonuc["duzelen"]:
        print(f"  ✓ DÜZELDİ      {sarki_yazi(s)}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    komut, argumanlar = sys.argv[1].lower(), sys.argv[2:]
    try:
        if komut == "giris":
            print(f"Giriş yapıldı: {spotify_baglan().giris_yap()}")
        elif komut == "kontrol" and argumanlar:
            sp = spotify_baglan()
            for link in argumanlar:
                _sonuc_yazdir(kontrol(sp, playlist_id_bul(link)))
        elif komut == "gecmis":
            pid = playlist_id_bul(argumanlar[0]) if argumanlar else None
            for r in reversed(olaylari_getir(pid)):
                ek = f"  (eklenme: {tarih(r['eklenme'])})" if r["eklenme"] else ""
                print(f"{tarih(r['zaman'])}  [{r['liste']}]  {r['olay']:<20} {sarki_yazi(r)}{ek}")
        elif komut == "csv":
            dosya = argumanlar[0] if argumanlar else "gecmis.csv"
            print(f"{csv_aktar(dosya)} kayıt '{dosya}' dosyasına yazıldı.")
        else:
            print(__doc__)
    except SpotifyHatasi as hata:
        sys.exit(str(hata))


if __name__ == "__main__":
    main()
