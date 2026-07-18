#!/bin/bash
#
# create_new_session.sh
# Membuat "new session" yang terisolasi dengan venv + tmux sendiri
# agar tidak bentrok dengan global atau session lain.
#
# Penggunaan:
#   ./create_new_session.sh nama_session_unik
#
# Setiap session punya:
# - Folder sendiri di /home/workdir/artifacts/sessions/<nama>/
# - Virtual environment sendiri (.venv)
# - Tmux session sendiri dengan nama sama (otomatis activate venv)
#
# Catatan: Karena 'screen' tidak tersedia di environment ini,
#          script ini menggunakan 'tmux' (sudah terinstall & lebih bagus).
#

set -e

SESSION_NAME="$1"

if [ -z "$SESSION_NAME" ]; then
    echo "❌ Error: Nama session wajib diisi!"
    echo "Cara pakai: $0 <nama_session>"
    echo "Contoh: $0 my-project-2026"
    exit 1
fi

# Validasi nama (hindari karakter aneh yang bikin error di path/tmux)
if [[ ! "$SESSION_NAME" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "❌ Error: Nama session hanya boleh huruf, angka, underscore (_) dan dash (-)"
    exit 1
fi

BASE_DIR="/home/workdir/artifacts/sessions"
SESSION_DIR="$BASE_DIR/$SESSION_NAME"

if [ -d "$SESSION_DIR" ]; then
    echo "⚠️  Session '$SESSION_NAME' sudah ada di $SESSION_DIR"
    echo "   Kalau mau buat ulang, hapus dulu foldernya atau pakai nama lain."
    exit 1
fi

echo "🚀 Membuat new session: $SESSION_NAME"
echo "   Lokasi: $SESSION_DIR"

mkdir -p "$SESSION_DIR"
cd "$SESSION_DIR"

echo "📦 Membuat virtual environment (.venv)..."
python3 -m venv .venv --prompt "($SESSION_NAME)"

echo "✅ Virtual environment selesai dibuat."

# Buat script start.sh yang otomatis handle tmux + activate venv
cat > start.sh << 'SCRIPT_EOF'
#!/bin/bash
# Auto-generated start script for this session
# Jalankan: ./start.sh

SESSION_NAME="__SESSION_NAME__"
SESSION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_ACTIVATE="$SESSION_DIR/.venv/bin/activate"

if ! command -v tmux &> /dev/null; then
    echo "❌ tmux tidak ditemukan!"
    exit 1
fi

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "🔗 Session tmux '$SESSION_NAME' sudah berjalan. Attach..."
    tmux attach -t "$SESSION_NAME"
else
    echo "🆕 Membuat tmux session baru: $SESSION_NAME"
    echo "   (venv otomatis aktif di dalamnya)"
    
    tmux new-session -d \
        -s "$SESSION_NAME" \
        -c "$SESSION_DIR" \
        bash -c "
            source '$VENV_ACTIVATE'
            export PS1='($SESSION_NAME) \u@\h:\w\$ '
            echo '✅ venv aktif. Ketik \"deactivate\" untuk keluar dari venv.'
            echo '   Untuk detach tmux: tekan Ctrl+B lalu d'
            exec bash
        "
    
    tmux attach -t "$SESSION_NAME"
fi
SCRIPT_EOF

# Ganti placeholder dengan nama session asli
sed -i "s/__SESSION_NAME__/$SESSION_NAME/g" start.sh
chmod +x start.sh

echo ""
echo "✅ New session '$SESSION_NAME' berhasil dibuat!"
echo ""
echo "📍 Cara menjalankan / attach ke session ini:"
echo "   cd $SESSION_DIR"
echo "   ./start.sh"
echo ""
echo "🔧 Di dalam tmux session:"
echo "   - venv sudah aktif otomatis (lihat prompt)"
echo "   - Detach (background): Ctrl+B lalu tekan d"
echo "   - Attach lagi nanti: ./start.sh atau tmux attach -t $SESSION_NAME"
echo "   - Kill session: tmux kill-session -t $SESSION_NAME"
echo ""
echo "📋 Lihat semua tmux session yang sedang jalan:"
echo "   tmux ls"
echo ""
echo "💡 Tips: Setiap new session pakai venv + tmux berbeda → tidak akan tabrakan!"
echo ""

# Bonus: buat README.md kecil di dalam session
cat > README.md << EOF
# Session: $SESSION_NAME

Dibuat pada: $(date '+%Y-%m-%d %H:%M:%S')

## Struktur
- .venv/          → Virtual environment Python terisolasi
- start.sh        → Script untuk start/attach tmux session (venv otomatis aktif)
- README.md       → File ini

## Cara pakai cepat
\`\`\`bash
cd $SESSION_DIR
./start.sh
\`\`\`

## Untuk menjalankan Python di venv ini (tanpa tmux)
\`\`\`bash
source .venv/bin/activate
python --version
# ... jalankan script kamu ...
deactivate
\`\`\`

## Cleanup
\`\`\`bash
tmux kill-session -t $SESSION_NAME
rm -rf $SESSION_DIR
\`\`\`
EOF

echo "📝 README.md juga dibuat di dalam folder session."
echo ""
echo "Sekarang kamu bisa langsung jalankan:"
echo "  cd $SESSION_DIR && ./start.sh"
echo ""