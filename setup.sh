#!/bin/bash
set -e

echo "🔧 Installing Colab Manager PRO"
echo "   Repo: https://github.com/leryjo/colab"
echo "================================================"

# Check root
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run as root: sudo bash setup.sh"
    exit 1
fi

# ============================================
# 1. INSTALL SYSTEM DEPENDENCIES
# ============================================
echo ""
echo "[1/5] Installing system dependencies..."

apt update -qq
apt install -y python3 python3-venv git curl wget \
    build-essential tmux nginx libssl-dev libffi-dev

echo "✅ System dependencies installed"

# ============================================
# 2. CREATE VIRTUAL ENVIRONMENT
# ============================================
echo ""
echo "[2/5] Creating Python virtual environment..."

INSTALL_DIR="/opt/colab-manager"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

python3 -m venv venv
source venv/bin/activate

# Upgrade pip inside venv
pip install --upgrade pip

echo "✅ Virtual environment ready"

# ============================================
# 3. INSTALL PYTHON PACKAGES (ALL INSIDE VENV)
# ============================================
echo ""
echo "[3/5] Installing Python packages..."

# Install from requirements.txt
if [ -f "$REPO_DIR/requirements.txt" ]; then
    pip install -r "$REPO_DIR/requirements.txt"
else
    pip install flask flask-cors gunicorn
fi

# Install google-colab-cli inside venv
pip install google-colab-cli

# Install Whisper (optional)
pip install openai-whisper faster-whisper 2>/dev/null || \
    echo "⚠️ Whisper skipped (optional)"

echo "✅ Python packages installed"

# ============================================
# 4. COPY FILES
# ============================================
echo ""
echo "[4/5] Copying application files..."

mkdir -p "$INSTALL_DIR/templates"

cp "$REPO_DIR/app.py" "$INSTALL_DIR/" 2>/dev/null || echo "⚠️ app.py not found"
cp "$REPO_DIR/colab_multi_auth.py" "$INSTALL_DIR/" 2>/dev/null || true
cp -r "$REPO_DIR/templates/"* "$INSTALL_DIR/templates/" 2>/dev/null || echo "⚠️ templates/ not found"

chmod +x "$INSTALL_DIR"/*.py

# Create wrappers using venv python
mkdir -p /usr/local/bin

# Only basic colab-multi (no bulk mode)
cat > /usr/local/bin/colab-multi << EOF
#!/bin/bash
$INSTALL_DIR/venv/bin/python $INSTALL_DIR/colab_multi_auth.py "\$@"
EOF
chmod +x /usr/local/bin/colab-multi

echo "✅ Files copied"

# ============================================
# 5. SYSTEMD SERVICE
# ============================================
echo ""
echo "[5/5] Setting up systemd service..."

cat > /etc/systemd/system/colab-manager.service << EOF
[Unit]
Description=Colab Manager PRO Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/colab-manager
Environment="PATH=/opt/colab-manager/venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/opt/colab-manager/venv/bin/python /opt/colab-manager/app.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/colab-manager.log
StandardError=append:/var/log/colab-manager.log

[Install]
WantedBy=multi-user.target
EOF

touch /var/log/colab-manager.log
chmod 666 /var/log/colab-manager.log

systemctl daemon-reload
systemctl enable colab-manager
systemctl start colab-manager

# Nginx
cat > /etc/nginx/sites-available/colab-manager << 'EOF'
server {
    listen 80;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_read_timeout 86400;
    }
}
EOF

ln -sf /etc/nginx/sites-available/colab-manager /etc/nginx/sites-enabled/ 2>/dev/null || true
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
nginx -t 2>/dev/null && systemctl restart nginx || true

# Firewall
ufw allow 8080/tcp 2>/dev/null || true
ufw allow 80/tcp 2>/dev/null || true

# ============================================
# DONE
# ============================================
IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}' || echo "YOUR_VPS_IP")

echo ""
echo "================================================"
echo "  ✅ INSTALLATION COMPLETE!"
echo "================================================"
echo ""
echo "🌐 Dashboard: http://$IP:8080"
echo ""
echo "📊 Commands:"
echo "   systemctl status colab-manager"
echo "   systemctl restart colab-manager"
echo "   journalctl -u colab-manager -f"
echo ""
echo "🔧 CLI Commands:"
echo "   colab-multi list"
echo "   colab-multi add joko1 --email j1@gmail.com"
echo "   colab-multi auth joko1"
echo "   colab-multi new joko1 s1 --gpu T4"
echo "   colab-multi --help"
echo ""
echo "🔐 Auth Commands:"
echo "   colab-auth --account joko1"
echo "   colab-auth --account joko1 --code XXX"
echo "================================================"
