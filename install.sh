#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

APP_NAME="Linux Guardian"
INSTALL_DIR="/usr/share/linux-guardian"
REPO_URL="https://github.com/hoomaanf/linux_guardian.git"

echo -e "${BLUE}"
echo "=================================================="
echo "        $APP_NAME Installer"
echo "=================================================="
echo -e "${NC}"

# ============================================
# Check root
# ============================================
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

# ============================================
# Detect distribution by package manager
# ============================================
detect_distro() {
    if command -v pacman &> /dev/null; then
        echo "arch"
    elif command -v apt &> /dev/null || command -v apt-get &> /dev/null; then
        echo "debian"
    elif command -v dnf &> /dev/null; then
        echo "fedora"
    elif command -v yum &> /dev/null; then
        echo "rhel"
    elif command -v zypper &> /dev/null; then
        echo "opensuse"
    elif command -v apk &> /dev/null; then
        echo "alpine"
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)

echo -e "${YELLOW}Detected package manager: $DISTRO${NC}"
echo ""

# ============================================
# Check if running from git clone or standalone
# ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/main.py" ]; then
    echo -e "${GREEN}✓ Found local files in: $SCRIPT_DIR${NC}"
    SOURCE_DIR="$SCRIPT_DIR"
else
    echo -e "${YELLOW}⚠ Local files not found. Cloning from GitHub...${NC}"
    
    if ! command -v git &> /dev/null; then
        echo -e "${RED}❌ git not found. Installing...${NC}"
        case "$DISTRO" in
            arch)   $SUDO pacman -S --needed git --noconfirm ;;
            debian) $SUDO apt update && $SUDO apt install -y git ;;
            fedora|rhel) $SUDO dnf install -y git ;;
            opensuse) $SUDO zypper install -y git ;;
            alpine) $SUDO apk add git ;;
            *) echo -e "${RED}Please install git manually${NC}"; exit 1 ;;
        esac
    fi
    
    TEMP_DIR=$(mktemp -d)
    echo -e "${YELLOW}📥 Cloning repository...${NC}"
    git clone --depth 1 "$REPO_URL" "$TEMP_DIR"
    SOURCE_DIR="$TEMP_DIR"
fi

# ============================================
# Install dependencies
# ============================================
echo -e "${YELLOW}📦 Installing dependencies...${NC}"
echo ""

case "$DISTRO" in
    arch)
        echo -e "${GREEN}Installing with pacman...${NC}"
        $SUDO pacman -Sy --needed \
            python \
            python-pip \
            python-pyqt6 \
            python-psutil \
            python-requests \
            python-importlib-metadata \
            python-platformdirs \
            git \
            --noconfirm
        ;;
        
    debian|ubuntu)
        echo -e "${GREEN}Installing with apt...${NC}"
        $SUDO apt update
        $SUDO apt install -y \
            python3 \
            python3-pip \
            python3-pyqt6 \
            python3-pyqt6.qtwebengine \
            python3-psutil \
            python3-requests \
            python3-importlib-metadata \
            python3-platformdirs \
            git
        ;;
        
    fedora)
        echo -e "${GREEN}Installing with dnf...${NC}"
        $SUDO dnf install -y \
            python3 \
            python3-pip \
            python3-pyqt6 \
            python3-pyqt6-devel \
            python3-psutil \
            python3-requests \
            python3-importlib-metadata \
            python3-platformdirs \
            git
        ;;
        
    rhel)
        echo -e "${GREEN}Installing with yum...${NC}"
        $SUDO yum install -y \
            python3 \
            python3-pip \
            python3-psutil \
            git
        echo -e "${YELLOW}⚠ Some packages not available, installing via pip...${NC}"
        ;;
        
    opensuse)
        echo -e "${GREEN}Installing with zypper...${NC}"
        $SUDO zypper install -y \
            python3 \
            python3-pip \
            python3-qt6 \
            python3-psutil \
            python3-requests \
            python3-importlib-metadata \
            python3-platformdirs \
            git
        ;;
        
    alpine)
        echo -e "${GREEN}Installing with apk...${NC}"
        $SUDO apk add \
            python3 \
            py3-pip \
            py3-pyqt6 \
            py3-psutil \
            py3-requests \
            py3-importlib-metadata \
            py3-platformdirs \
            git
        ;;
        
    *)
        echo -e "${RED}❌ No supported package manager found!${NC}"
        echo "Please install dependencies manually:"
        echo "  - Python 3.10+"
        echo "  - PyQt6"
        echo "  - psutil"
        echo "  - requests"
        echo "  - importlib-metadata"
        echo "  - platformdirs"
        echo "  - git"
        exit 1
        ;;
esac

# ============================================
# Install required pip packages
# ============================================
echo -e "${YELLOW}📦 Installing pip packages...${NC}"

PIP_PACKAGES="psutil requests importlib-metadata platformdirs"

for pkg in $PIP_PACKAGES; do
    if ! python3 -c "import $pkg" >/dev/null 2>&1; then
        echo "Installing $pkg..."
        if [ "$DISTRO" = "arch" ]; then
            pip3 install --break-system-packages "$pkg" 2>/dev/null || pip3 install --user "$pkg"
        else
            pip3 install --user "$pkg" 2>/dev/null || $SUDO pip3 install "$pkg"
        fi
    fi
done

# ============================================
# Install application
# ============================================
echo ""
echo -e "${GREEN}📁 Installing application...${NC}"

$SUDO rm -rf "$INSTALL_DIR"
$SUDO mkdir -p "$INSTALL_DIR"

# Copy application files
$SUDO cp -r \
    "$SOURCE_DIR"/app \
    "$SOURCE_DIR"/tests \
    "$INSTALL_DIR" 2>/dev/null || true

[ -f "$SOURCE_DIR/main.py" ] && $SUDO cp "$SOURCE_DIR/main.py" "$INSTALL_DIR"
[ -f "$SOURCE_DIR/README.md" ] && $SUDO cp "$SOURCE_DIR/README.md" "$INSTALL_DIR"
[ -f "$SOURCE_DIR/requirements.txt" ] && $SUDO cp "$SOURCE_DIR/requirements.txt" "$INSTALL_DIR"

# Create necessary directories
$SUDO mkdir -p "$INSTALL_DIR/app/icon"
$SUDO mkdir -p "$INSTALL_DIR/screenshots"

# Copy icon if exists
if [ -f "$SOURCE_DIR/app/icon/logo.png" ]; then
    $SUDO cp "$SOURCE_DIR/app/icon/logo.png" "$INSTALL_DIR/app/icon/"
fi

# ============================================
# Create launcher
# ============================================
echo -e "${YELLOW}🚀 Creating launcher...${NC}"

cat <<'EOF' | $SUDO tee /usr/local/bin/linux-guardian >/dev/null
#!/bin/sh
exec python3 /usr/share/linux-guardian/main.py "$@"
EOF

$SUDO chmod +x /usr/local/bin/linux-guardian

# ============================================
# Install icons
# ============================================
echo -e "${YELLOW}🎨 Installing icons...${NC}"

$SUDO mkdir -p /usr/share/icons/hicolor/{256x256,128x128,64x64,48x48,32x32,16x16}/apps

if [ -f "$SOURCE_DIR/app/icon/logo.png" ]; then
    $SUDO cp "$SOURCE_DIR/app/icon/logo.png" /usr/share/icons/hicolor/256x256/apps/linux-guardian.png
    $SUDO cp "$SOURCE_DIR/app/icon/logo.png" /usr/share/pixmaps/linux-guardian.png
elif [ -f "$SOURCE_DIR/logo.png" ]; then
    $SUDO cp "$SOURCE_DIR/logo.png" /usr/share/icons/hicolor/256x256/apps/linux-guardian.png
    $SUDO cp "$SOURCE_DIR/logo.png" /usr/share/pixmaps/linux-guardian.png
fi

# ============================================
# Create desktop file
# ============================================
echo -e "${YELLOW}📁 Creating desktop entry...${NC}"

cat <<'EOF' | $SUDO tee /usr/share/applications/linux-guardian.desktop >/dev/null
[Desktop Entry]
Version=1.0
Type=Application
Name=Linux Guardian
Comment=System Security and Optimization Tool
Exec=linux-guardian
Icon=linux-guardian
Terminal=false
Categories=System;Utility;
StartupWMClass=LinuxGuardian
EOF

# ============================================
# Create quarantine and logs directories
# ============================================
echo -e "${YELLOW}📂 Creating data directories...${NC}"

DATA_DIR="$HOME/.local/share/linux-guardian"
QUARANTINE_DIR="$DATA_DIR/quarantine"
LOGS_DIR="$DATA_DIR/logs"

mkdir -p "$QUARANTINE_DIR"
mkdir -p "$LOGS_DIR"

echo -e "${GREEN}✓ Data directory: $DATA_DIR${NC}"
echo -e "${GREEN}✓ Quarantine: $QUARANTINE_DIR${NC}"
echo -e "${GREEN}✓ Logs: $LOGS_DIR${NC}"

# ============================================
# Update caches
# ============================================
if command -v update-desktop-database >/dev/null; then
    $SUDO update-desktop-database /usr/share/applications 2>/dev/null || true
fi

if command -v gtk-update-icon-cache >/dev/null; then
    $SUDO gtk-update-icon-cache -f /usr/share/icons/hicolor 2>/dev/null || true
fi

# ============================================
# Cleanup
# ============================================
if [ -d "$TEMP_DIR" ] && [ "$SOURCE_DIR" = "$TEMP_DIR" ]; then
    rm -rf "$TEMP_DIR"
    echo -e "${GREEN}✓ Cleaned up temporary files${NC}"
fi

# ============================================
# Test installation
# ============================================
echo ""
echo -e "${YELLOW}🔍 Testing installation...${NC}"

if command -v linux-guardian >/dev/null; then
    echo -e "${GREEN}✅ Command 'linux-guardian' is available${NC}"
else
    echo -e "${RED}❌ Command 'linux-guardian' not found in PATH${NC}"
fi

if [ -f "$INSTALL_DIR/main.py" ]; then
    echo -e "${GREEN}✅ Application files installed correctly${NC}"
else
    echo -e "${RED}❌ Application files not found at $INSTALL_DIR${NC}"
fi

# ============================================
# Done
# ============================================
echo ""
echo -e "${GREEN}====================================${NC}"
echo -e "${GREEN} ✅ Installation completed successfully${NC}"
echo -e "${GREEN}====================================${NC}"
echo ""
echo -e "${YELLOW}📖 How to run:${NC}"
echo ""
echo -e "  ${GREEN}1. From terminal:${NC}"
echo "     linux-guardian"
echo ""
echo -e "  ${GREEN}2. From application menu:${NC}"
echo "     Search for 'Linux Guardian'"
echo ""
echo -e "${GREEN}🛡️  Protect your system with Linux Guardian!${NC}"
echo ""