# 🚀 Colab Manager PRO (Clean Version)

> Multi-Account Google Colab Dashboard dengan Inline Console, Running Time, dan Permanent Delete

**Versi Bersih** — Tanpa fitur bulk operations dan tanpa Whisper.

---

## ✨ Fitur Utama

- ✅ **Multi Account Management** — Kelola banyak akun Google Colab sekaligus
- ✅ **Inline Console** — Console langsung di dalam dashboard (tanpa popup)
- ✅ **Auto Account Detection** — Console otomatis menggunakan akun yang benar per session
- ✅ **Running Time Session** — Menampilkan berapa lama session sudah berjalan
- ✅ **Permanent Delete** — Hapus session secara permanen via web maupun terminal
- ✅ **Global Clean Inactive** — Satu tombol untuk hapus semua session non-aktif secara permanen
- ✅ **colab-multi clean** — Perintah CLI untuk membersihkan session stale
- ✅ **Session "unknown" disembunyikan** — Dashboard lebih bersih
- ✅ **One-click Installer** — `setup.sh` otomatis setup systemd + nginx

---

## 📁 Struktur Project

```
colab-manager-pro/
├── app.py                      # Main Flask backend
├── colab_multi_auth.py         # Multi-account CLI manager
├── requirements.txt
├── setup.sh                    # One-click installer
├── README.md
└── templates/
    └── index.html              # Web Dashboard UI
```

---

## 🚀 Instalasi Cepat (Recommended)

```bash
# Clone repository
git clone https://github.com/leryjo/colab-manager-pro.git
cd colab-manager-pro

# Jalankan installer otomatis
chmod +x setup.sh
sudo ./setup.sh
```

Setelah selesai, dashboard bisa diakses di:
```
http://IP_VPS_KAMU:8080
```

---

## ▶️ Cara Menjalankan Manual

```bash
cd colab-manager-pro

# Buat virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install google-colab-cli

# Jalankan dashboard
python app.py
```

---

## 🔧 Perintah `colab-multi`

```bash
# Tambah akun baru
colab-multi add joko1 --email joko1@gmail.com

# List semua akun
colab-multi list

# Autentikasi akun
colab-multi auth joko1

# Buat session baru
colab-multi new joko1 sesi1 --gpu T4

# Lihat session
colab-multi run joko1 sessions

# Bersihkan session inactive/stale
colab-multi clean
colab-multi clean --account joko1
```

---

## 🌐 Fitur Web Dashboard

| Fitur                        | Keterangan |
|-----------------------------|------------|
| **Inline Console**          | Buka console langsung di card session |
| **Running Time**            | Tampil icon ⏱️ (contoh: 2h 15m) |
| **Permanent Delete**        | Tombol 🗑️ Delete di setiap session |
| **Clean All Inactive**      | Tombol di toolbar untuk hapus semua non-aktif permanen |
| **Auto Account**            | Tidak perlu switch akun manual untuk console |
| **Multi Account**           | Semua session dari semua akun ditampilkan |

---

## 🔐 Cara Autentikasi Akun via Dashboard

1. Buka `http://IP:8080`
2. Klik tombol **+** (Add Account)
3. Masukkan nama akun → **Tambah**
4. Klik **Login Google Account** pada akun tersebut
5. Klik **Dapatkan URL Login** → buka URL di browser
6. Login Google → copy **authorization code**
7. Paste code → klik **Verifikasi**

Selesai! Akun siap digunakan.

---

## 🛠️ Mengelola Service

```bash
# Cek status
sudo systemctl status colab-manager

# Restart
sudo systemctl restart colab-manager

# Lihat log
sudo journalctl -u colab-manager -f
```

---

## ❓ Troubleshooting

| Masalah | Solusi |
|---------|--------|
| Port 8080 tidak bisa diakses | `sudo ufw allow 8080` |
| Session tidak muncul | Klik tombol **Sync** di dashboard |
| Console tidak connect | Pastikan akun sudah di-auth, lalu coba lagi |
| `colab: not found` | Jalankan ulang `setup.sh` |
| Token expired | Gunakan `colab-multi auth <nama_akun>` |

---

## 📜 Lisensi

MIT License — Bebas digunakan dan dimodifikasi.

---

**Dibuat untuk komunitas Colab Indonesia** 🔥

Repo: https://github.com/leryjo/colab-manager-pro

Jika ada pertanyaan atau ingin request fitur baru, silakan buat issue di repository ini.
