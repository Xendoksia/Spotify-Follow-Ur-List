"""
Spotify Liste Takip – pencereli arayüz.

Çalıştırmak için:  python uygulama.py
(ya da "Spotify Liste Takip.bat" dosyasına çift tıklayın)
"""

import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

import spotify as sp_cekirdek
from spotify import GirisGerekli, SpotifyHatasi, sarki_yazi, tarih

OLAY_ADLARI = {
    "EKLENDI": "+ Eklendi",
    "CIKTI": "− Çıktı",
    "OYNATILAMAZ": "! Oynatılamaz",
    "TEKRAR_OYNATILABILIR": "✓ Düzeldi",
    "ILK_KAYIT": "• İlk kayıt",
}
OLAY_RENKLERI = {
    "EKLENDI": "#1a7f37",
    "CIKTI": "#c62828",
    "OYNATILAMAZ": "#b26a00",
    "TEKRAR_OYNATILABILIR": "#1565c0",
    "ILK_KAYIT": "#666666",
}
ISARETLI, ISARETSIZ = "☑", "☐"


class Uygulama(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Spotify Liste Takip")
        self.geometry("1050x680")
        self.minsize(800, 500)

        self.listeler = {}      # playlist_id -> {ad, sahip, sarki_sayisi, takipte, son_kontrol}
        self.mesgul = False

        stil = ttk.Style(self)
        if "vista" in stil.theme_names():
            stil.theme_use("vista")
        stil.configure("Treeview", rowheight=24)

        self._arayuz_kur()
        self._takip_edilenleri_yukle()
        self._gecmisi_yenile()

        if not self._ayarlar_tamam():
            self.after(200, self._ayarlar_penceresi)

    # ------------------------------------------------------------ arayüz

    def _arayuz_kur(self):
        ust = ttk.Frame(self, padding=(10, 8, 10, 0))
        ust.pack(fill="x")
        ttk.Button(ust, text="⚙ Ayarlar", command=self._ayarlar_penceresi).pack(side="right")
        self.giris_buton = ttk.Button(ust, command=self._giris_yap)
        self.giris_buton.pack(side="right", padx=6)
        self.giris_etiket = ttk.Label(ust, foreground="#1a7f37")
        self.giris_etiket.pack(side="right", padx=6)
        self._giris_durumunu_goster()
        self.durum = ttk.Label(ust, text="Hazır.", foreground="#555")
        self.durum.pack(side="left")

        self.sekmeler = ttk.Notebook(self)
        self.sekmeler.pack(fill="both", expand=True, padx=10, pady=8)
        self._listeler_sekmesi()
        self._gecmis_sekmesi()

    def _listeler_sekmesi(self):
        sekme = ttk.Frame(self.sekmeler, padding=10)
        self.sekmeler.add(sekme, text="  Listeler  ")

        giris = ttk.Frame(sekme)
        giris.pack(fill="x")
        giris.columnconfigure(1, weight=1)

        self.profil_buton = ttk.Button(giris, text="Spotify'daki listelerimi getir", command=self._listelerimi_getir)
        self.profil_buton.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(giris, text="veya liste linki:").grid(row=1, column=0, sticky="w", pady=2)
        self.liste_girdi = ttk.Entry(giris)
        self.liste_girdi.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        self.liste_girdi.bind("<Return>", lambda e: self._link_ile_ekle())
        self.ekle_buton = ttk.Button(giris, text="Listeye ekle", command=self._link_ile_ekle)
        self.ekle_buton.grid(row=1, column=2, sticky="ew", pady=2)

        ttk.Label(
            sekme, foreground="#666",
            text="Takip etmek istediğin listelerin kutucuğuna tıkla, sonra “Seçilenleri kontrol et”e bas.",
        ).pack(anchor="w", pady=(10, 4))

        tablo_cerceve = ttk.Frame(sekme)
        tablo_cerceve.pack(fill="both", expand=True)
        sutunlar = ("takip", "ad", "sahip", "sarki", "son")
        self.liste_tablo = ttk.Treeview(tablo_cerceve, columns=sutunlar, show="headings", selectmode="browse")
        for sutun, baslik, genislik, hiza in (
            ("takip", "Takip", 60, "center"),
            ("ad", "Liste", 380, "w"),
            ("sahip", "Sahibi", 160, "w"),
            ("sarki", "Şarkı", 70, "center"),
            ("son", "Son kontrol", 140, "center"),
        ):
            self.liste_tablo.heading(sutun, text=baslik)
            self.liste_tablo.column(sutun, width=genislik, anchor=hiza, stretch=(sutun == "ad"))
        self.liste_tablo.tag_configure("takipte", background="#e8f5e9")
        kaydirma = ttk.Scrollbar(tablo_cerceve, orient="vertical", command=self.liste_tablo.yview)
        self.liste_tablo.configure(yscrollcommand=kaydirma.set)
        self.liste_tablo.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")
        self.liste_tablo.bind("<Button-1>", self._satira_tiklandi)
        self.liste_tablo.bind("<space>", lambda e: self._secili_satiri_degistir())
        self.liste_tablo.bind("<Double-1>", self._listeyi_spotifyda_ac)

        alt = ttk.Frame(sekme)
        alt.pack(fill="x", pady=(8, 0))
        ttk.Button(alt, text="Tümünü seç", command=lambda: self._hepsini_ayarla(True)).pack(side="left")
        ttk.Button(alt, text="Seçimi kaldır", command=lambda: self._hepsini_ayarla(False)).pack(side="left", padx=6)
        self.kontrol_buton = ttk.Button(alt, text="▶  Seçilenleri kontrol et", command=self._kontrol_et)
        self.kontrol_buton.pack(side="right")

        ttk.Label(sekme, text="Son kontrol sonucu:").pack(anchor="w", pady=(10, 2))
        self.sonuc_kutu = tk.Text(sekme, height=9, wrap="word", font=("Segoe UI", 10),
                                  relief="solid", borderwidth=1, state="disabled")
        self.sonuc_kutu.pack(fill="x")
        for olay, renk in OLAY_RENKLERI.items():
            self.sonuc_kutu.tag_configure(olay, foreground=renk)
        self.sonuc_kutu.tag_configure("baslik", font=("Segoe UI", 10, "bold"))

    def _gecmis_sekmesi(self):
        sekme = ttk.Frame(self.sekmeler, padding=10)
        self.sekmeler.add(sekme, text="  Geçmiş  ")

        ust = ttk.Frame(sekme)
        ust.pack(fill="x")
        ttk.Label(ust, text="Liste:").pack(side="left")
        self.filtre = ttk.Combobox(ust, state="readonly", width=40)
        self.filtre.pack(side="left", padx=6)
        self.filtre.bind("<<ComboboxSelected>>", lambda e: self._gecmisi_yenile())
        ttk.Label(ust, text="Olay:").pack(side="left", padx=(12, 0))
        self.olay_filtre = ttk.Combobox(ust, state="readonly", width=16,
                                        values=["Tümü"] + list(OLAY_ADLARI.values()))
        self.olay_filtre.current(0)
        self.olay_filtre.pack(side="left", padx=6)
        self.olay_filtre.bind("<<ComboboxSelected>>", lambda e: self._gecmisi_yenile())
        ttk.Button(ust, text="CSV'ye aktar", command=self._csv_aktar).pack(side="right")
        ttk.Button(ust, text="Yenile", command=self._gecmisi_yenile).pack(side="right", padx=6)

        tablo_cerceve = ttk.Frame(sekme)
        tablo_cerceve.pack(fill="both", expand=True, pady=(8, 0))
        sutunlar = ("zaman", "liste", "olay", "sarki", "eklenme")
        self.gecmis_tablo = ttk.Treeview(tablo_cerceve, columns=sutunlar, show="headings")
        for sutun, baslik, genislik in (
            ("zaman", "Fark edilme", 130),
            ("liste", "Liste", 200),
            ("olay", "Olay", 110),
            ("sarki", "Şarkı", 400),
            ("eklenme", "Listeye eklenme", 130),
        ):
            self.gecmis_tablo.heading(sutun, text=baslik)
            self.gecmis_tablo.column(sutun, width=genislik, stretch=(sutun == "sarki"))
        for olay, renk in OLAY_RENKLERI.items():
            self.gecmis_tablo.tag_configure(olay, foreground=renk)
        kaydirma = ttk.Scrollbar(tablo_cerceve, orient="vertical", command=self.gecmis_tablo.yview)
        self.gecmis_tablo.configure(yscrollcommand=kaydirma.set)
        self.gecmis_tablo.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")

        ttk.Label(
            sekme, foreground="#666",
            text="“Fark edilme”: değişikliğin görüldüğü kontrolün zamanı. "
                 "Şarkı, bir önceki kontrol ile bu zaman arasında çıkmış/eklenmiştir.",
        ).pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------ yardımcılar

    def _ayarlar_tamam(self):
        ayar = sp_cekirdek.ayarlari_oku()
        return bool(ayar.get("CLIENT_ID") and ayar.get("CLIENT_SECRET"))

    def _durum(self, yazi):
        self.durum.configure(text=yazi)

    def _mesgul_yap(self, mesgul):
        self.mesgul = mesgul
        durum = "disabled" if mesgul else "normal"
        for buton in (self.profil_buton, self.ekle_buton, self.kontrol_buton, self.giris_buton):
            buton.configure(state=durum)
        self.configure(cursor="watch" if mesgul else "")

    def _arka_planda(self, is_fonksiyonu, bitince):
        """Ağ işlerini arka planda yapar ki pencere donmasın."""
        if self.mesgul:
            return
        if not self._ayarlar_tamam():
            self._ayarlar_penceresi()
            return
        self._mesgul_yap(True)

        def calis():
            giris_gerekli = False
            try:
                sonuc, hata = is_fonksiyonu(), None
            except GirisGerekli as h:
                sonuc, hata, giris_gerekli = None, str(h), True
            except SpotifyHatasi as h:
                sonuc, hata = None, str(h)
            except Exception as h:  # beklenmeyen hata da kullanıcıya gösterilsin
                sonuc, hata = None, f"Beklenmeyen hata: {h!r}"
            self.after(0, lambda: self._is_bitti(bitince, sonuc, hata, giris_gerekli))

        threading.Thread(target=calis, daemon=True).start()

    def _is_bitti(self, bitince, sonuc, hata, giris_gerekli=False):
        self._mesgul_yap(False)
        self._giris_durumunu_goster()
        if giris_gerekli:
            self._durum("Giriş gerekli.")
            if messagebox.askyesno("Giriş gerekli", f"{hata}\n\nŞimdi Spotify ile giriş yapılsın mı?", parent=self):
                self._giris_yap()
        elif hata:
            self._durum("Hata.")
            messagebox.showerror("Hata", hata, parent=self)
        else:
            bitince(sonuc)

    # ------------------------------------------------------------ listeler

    def _takip_edilenleri_yukle(self):
        for l in sp_cekirdek.takip_listesi():
            self.listeler[l["playlist_id"]] = {
                "ad": l["ad"], "sahip": "", "sarki_sayisi": "",
                "takipte": True, "son_kontrol": l["son_kontrol"],
            }
        self._liste_tablosunu_ciz()

    def _liste_tablosunu_ciz(self):
        self.liste_tablo.delete(*self.liste_tablo.get_children())
        # Takip edilenler üstte
        sirali = sorted(self.listeler.items(), key=lambda x: (not x[1]["takipte"], x[1]["ad"].lower()))
        for pid, l in sirali:
            self.liste_tablo.insert(
                "", "end", iid=pid, tags=("takipte",) if l["takipte"] else (),
                values=(ISARETLI if l["takipte"] else ISARETSIZ, l["ad"], l["sahip"],
                        l["sarki_sayisi"], tarih(l["son_kontrol"]) or "—"),
            )
        takipte = [l["ad"] for l in self.listeler.values() if l["takipte"]]
        self.filtre.configure(values=["Tümü"] + sorted(takipte, key=str.lower))
        if not self.filtre.get():
            self.filtre.current(0)
        self.kontrol_buton.configure(text=f"▶  Seçilenleri kontrol et ({len(takipte)})")

    def _takip_degistir(self, pid):
        l = self.listeler[pid]
        l["takipte"] = not l["takipte"]
        sp_cekirdek.takip_ayarla(pid, l["ad"], l["takipte"])
        self._liste_tablosunu_ciz()
        if self.liste_tablo.exists(pid):
            self.liste_tablo.selection_set(pid)
            self.liste_tablo.see(pid)

    def _satira_tiklandi(self, olay):
        if self.liste_tablo.identify_region(olay.x, olay.y) != "cell":
            return
        pid = self.liste_tablo.identify_row(olay.y)
        # "Takip" sütunundaki kutucuğa tıklama takibi açar/kapatır
        if pid and self.liste_tablo.identify_column(olay.x) == "#1":
            self._takip_degistir(pid)
            return "break"

    def _secili_satiri_degistir(self):
        secili = self.liste_tablo.selection()
        if secili:
            self._takip_degistir(secili[0])

    def _hepsini_ayarla(self, takipte):
        for pid, l in self.listeler.items():
            if l["takipte"] != takipte:
                l["takipte"] = takipte
                sp_cekirdek.takip_ayarla(pid, l["ad"], takipte)
        self._liste_tablosunu_ciz()

    def _listeyi_spotifyda_ac(self, olay):
        pid = self.liste_tablo.identify_row(olay.y)
        if pid and self.liste_tablo.identify_column(olay.x) != "#1":
            webbrowser.open(f"https://open.spotify.com/playlist/{pid}")

    def _giris_durumunu_goster(self):
        ayar = sp_cekirdek.ayarlari_oku()
        if ayar.get("REFRESH_TOKEN"):
            self.giris_etiket.configure(text=f"● Giriş: {ayar.get('KULLANICI', '')}")
            self.giris_buton.configure(text="Hesap değiştir")
        else:
            self.giris_etiket.configure(text="")
            self.giris_buton.configure(text="Spotify ile giriş yap")

    def _giris_yap(self):
        self._durum("Tarayıcıda Spotify onay sayfası açıldı, “Kabul et”e basın…")

        def bitince(kullanici):
            self._durum(f"Giriş yapıldı: {kullanici}")
            self._listelerimi_getir()

        self._arka_planda(lambda: spotify_baglanti().giris_yap(), bitince)

    def _listelerimi_getir(self):
        self._durum("Listeler getiriliyor…")

        def bitince(sonuc):
            gelenler, baskasinin = sonuc
            for p in gelenler:
                eski = self.listeler.get(p["id"], {})
                self.listeler[p["id"]] = {
                    "ad": p["ad"], "sahip": p["sahip"], "sarki_sayisi": p["sarki_sayisi"],
                    "takipte": eski.get("takipte", False), "son_kontrol": eski.get("son_kontrol"),
                }
            self._liste_tablosunu_ciz()
            ek = (f" (takip ettiğin {len(baskasinin)} başkasının listesi gösterilmedi: "
                  f"Spotify onların şarkılarını vermiyor)") if baskasinin else ""
            self._durum(f"{len(gelenler)} liste bulundu.{ek}")

        self._arka_planda(lambda: spotify_baglanti().kendi_listelerim(), bitince)

    def _link_ile_ekle(self):
        link = self.liste_girdi.get().strip()
        if not link:
            return
        try:
            pid = sp_cekirdek.playlist_id_bul(link)
        except SpotifyHatasi as h:
            messagebox.showerror("Hata", str(h), parent=self)
            return
        self._durum("Liste bilgisi alınıyor…")

        def bitince(ad):
            eski = self.listeler.get(pid, {})
            self.listeler[pid] = {"ad": ad, "sahip": eski.get("sahip", ""),
                                  "sarki_sayisi": eski.get("sarki_sayisi", ""),
                                  "takipte": True, "son_kontrol": eski.get("son_kontrol")}
            sp_cekirdek.takip_ayarla(pid, ad, True)
            self.liste_girdi.delete(0, "end")
            self._liste_tablosunu_ciz()
            self._durum(f"“{ad}” takibe eklendi.")

        self._arka_planda(lambda: spotify_baglanti().liste_adi(pid), bitince)

    # ------------------------------------------------------------ kontrol

    def _kontrol_et(self):
        secilenler = [pid for pid, l in self.listeler.items() if l["takipte"]]
        if not secilenler:
            messagebox.showinfo("Seçim yok", "Önce takip etmek istediğin listelerin kutucuğunu işaretle.",
                                parent=self)
            return

        def is_():
            sp = spotify_baglanti()
            sonuclar = []
            for i, pid in enumerate(secilenler, 1):
                ad = self.listeler[pid]["ad"]
                self.after(0, lambda i=i, ad=ad: self._durum(f"Kontrol ediliyor ({i}/{len(secilenler)}): {ad}"))
                try:
                    sonuclar.append(sp_cekirdek.kontrol(sp, pid))
                except GirisGerekli:
                    raise
                except SpotifyHatasi as h:  # bir liste hata verirse diğerleri yine kontrol edilsin
                    sonuclar.append({"ad": ad, "hata": str(h)})
            return sonuclar

        self._arka_planda(is_, self._kontrol_bitti)

    def _kontrol_bitti(self, sonuclar):
        kutu = self.sonuc_kutu
        kutu.configure(state="normal")
        kutu.delete("1.0", "end")
        toplam_degisiklik = 0
        for s in sonuclar:
            if "hata" in s:
                kutu.insert("end", f"{s['ad']}: ", "baslik")
                kutu.insert("end", f"HATA – {s['hata']}\n", "CIKTI")
                continue
            l = self.listeler.get(s["playlist_id"])
            if l:
                l.update(ad=s["ad"], sarki_sayisi=s["toplam"], son_kontrol=_son_kontrol(s["playlist_id"]))
            kutu.insert("end", f"{s['ad']} ({s['toplam']} şarkı): ", "baslik")
            if s["ilk_kez"]:
                kutu.insert("end", "ilk kayıt alındı, bundan sonraki kontrollerde değişiklikler görünecek.\n",
                            "ILK_KAYIT")
                for sarki in s["kapali"]:
                    kutu.insert("end", f"    ! Türkiye'de oynatılamıyor: {sarki_yazi(sarki)}\n", "OYNATILAMAZ")
                continue
            degisiklikler = [("EKLENDI", x) for x in s["eklenen"]] + [("CIKTI", x) for x in s["cikan"]] + \
                            [("OYNATILAMAZ", x) for x in s["bozulan"]] + [("TEKRAR_OYNATILABILIR", x) for x in s["duzelen"]]
            toplam_degisiklik += len(degisiklikler)
            if not degisiklikler:
                kutu.insert("end", "değişiklik yok.\n")
                continue
            kutu.insert("end", f"{len(degisiklikler)} değişiklik\n")
            for olay, sarki in degisiklikler:
                ek = f"   (eklenme: {tarih(sarki['eklenme'])})" if sarki.get("eklenme") else ""
                kutu.insert("end", f"    {OLAY_ADLARI[olay]:<14} {sarki_yazi(sarki)}{ek}\n", olay)
        kutu.configure(state="disabled")
        self._liste_tablosunu_ciz()
        self._gecmisi_yenile()
        self._durum(f"Kontrol bitti: {len(sonuclar)} liste, {toplam_degisiklik} değişiklik.")

    # ------------------------------------------------------------ geçmiş

    def _gecmisi_yenile(self):
        secili_liste = self.filtre.get()
        pid = None
        if secili_liste and secili_liste != "Tümü":
            pid = next((k for k, v in self.listeler.items() if v["ad"] == secili_liste), None)
        olay_secimi = self.olay_filtre.get()
        olay_kodu = next((k for k, v in OLAY_ADLARI.items() if v == olay_secimi), None)

        self.gecmis_tablo.delete(*self.gecmis_tablo.get_children())
        for r in sp_cekirdek.olaylari_getir(pid):
            if olay_kodu and r["olay"] != olay_kodu:
                continue
            self.gecmis_tablo.insert("", "end", tags=(r["olay"],), values=(
                tarih(r["zaman"]), r["liste"] or "", OLAY_ADLARI.get(r["olay"], r["olay"]),
                sarki_yazi(r), tarih(r["eklenme"]),
            ))

    def _csv_aktar(self):
        dosya = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", initialfile="spotify_gecmis.csv",
            filetypes=[("CSV (Excel)", "*.csv")],
        )
        if dosya:
            adet = sp_cekirdek.csv_aktar(dosya)
            self._durum(f"{adet} kayıt dışa aktarıldı: {dosya}")

    # ------------------------------------------------------------ ayarlar

    def _ayarlar_penceresi(self):
        pencere = tk.Toplevel(self)
        pencere.title("Spotify API ayarları")
        pencere.transient(self)
        pencere.resizable(False, False)
        cerceve = ttk.Frame(pencere, padding=14)
        cerceve.pack(fill="both")

        ttk.Label(cerceve, justify="left", text=(
            "1) developer.spotify.com/dashboard adresinde Spotify hesabınla giriş yap\n"
            "2) “Create app” → isim yaz, Redirect URI: http://127.0.0.1:8888/callback\n"
            "3) “Web API”yi işaretle, kaydet → Settings'ten Client ID ve Client Secret'i kopyala"
        )).grid(row=0, column=0, columnspan=2, sticky="w")
        baglanti = ttk.Label(cerceve, text="Dashboard'u aç", foreground="#1565c0", cursor="hand2")
        baglanti.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 10))
        baglanti.bind("<Button-1>", lambda e: webbrowser.open("https://developer.spotify.com/dashboard"))

        ayar = sp_cekirdek.ayarlari_oku()
        ttk.Label(cerceve, text="Client ID:").grid(row=2, column=0, sticky="w", pady=3)
        id_girdi = ttk.Entry(cerceve, width=45)
        id_girdi.insert(0, ayar.get("CLIENT_ID", ""))
        id_girdi.grid(row=2, column=1, pady=3)
        ttk.Label(cerceve, text="Client Secret:").grid(row=3, column=0, sticky="w", pady=3)
        secret_girdi = ttk.Entry(cerceve, width=45, show="•")
        secret_girdi.insert(0, ayar.get("CLIENT_SECRET", ""))
        secret_girdi.grid(row=3, column=1, pady=3)

        def kaydet():
            yeni = sp_cekirdek.ayarlari_oku()
            yeni["CLIENT_ID"] = id_girdi.get().strip()
            yeni["CLIENT_SECRET"] = secret_girdi.get().strip()
            if not (yeni["CLIENT_ID"] and yeni["CLIENT_SECRET"]):
                messagebox.showwarning("Eksik", "İki alan da dolu olmalı.", parent=pencere)
                return
            if (yeni["CLIENT_ID"], yeni["CLIENT_SECRET"]) != (ayar.get("CLIENT_ID"), ayar.get("CLIENT_SECRET")):
                yeni.pop("REFRESH_TOKEN", None)  # başka uygulamanın oturumu geçersiz olur
            sp_cekirdek.ayarlari_yaz(yeni)
            pencere.destroy()
            self._giris_durumunu_goster()
            self._durum("Ayarlar kaydedildi.")

        ttk.Button(cerceve, text="Kaydet", command=kaydet).grid(row=4, column=1, sticky="e", pady=(10, 0))
        pencere.grab_set()
        id_girdi.focus_set()


def spotify_baglanti():
    return sp_cekirdek.spotify_baglan()


def _son_kontrol(playlist_id):
    with sp_cekirdek.db_ac() as db:
        satir = db.execute("SELECT son_kontrol FROM listeler WHERE playlist_id = ?", (playlist_id,)).fetchone()
        return satir["son_kontrol"] if satir else None


if __name__ == "__main__":
    Uygulama().mainloop()
