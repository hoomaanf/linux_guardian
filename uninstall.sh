#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

APP_NAME="Linux Guardian"
INSTALL_DIR="/usr/share/linux-guardian"
DATA_DIR="$HOME/.local/share/linux-guardian"

echo -e "${BLUE}"
echo "=================================================="
echo "        $APP_NAME Uninstaller"
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
# Confirmation
# ============================================
echo -e "${YELLOW}⚠ This will remove $APP_NAME from your system.${NC}"
echo ""
echo -e "${YELLOW}What would you like to remove?${NC}"
echo ""
echo "  1) Remove application only (keep data: quarantine, logs, settings)"
echo "  2) Remove application AND all data (quarantine, logs, settings)"
echo "  3) Cancel"
echo ""
read -p "Choose option [1-3]: " OPTION

case $OPTION in
    1)
        REMOVE_DATA=false
        ;;
    2)
        REMOVE_DATA=true
        echo -e "${RED}⚠ WARNING: This will permanently delete all quarantine files and logs!${NC}"
        read -p "Are you sure? [y/N]: " CONFIRM
        if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
            echo -e "${GREEN}Operation cancelled.${NC}"
            exit 0
        fi
        ;;
    *)
        echo -e "${GREEN}Operation cancelled.${NC}"
        exit 0
        ;;
esac

echo ""

# ============================================
# Remove application files
# ============================================
echo -e "${YELLOW}🗑️ Removing application files...${NC}"

if [ -d "$INSTALL_DIR" ]; then
    $SUDO rm -rf "$INSTALL_DIR"
    echo -e "${GREEN}✓ Removed $INSTALL_DIR${NC}"
else
    echo -e "${YELLOW}⚠ $INSTALL_DIR not found${NC}"
fi

# ============================================
# Remove launcher
# ============================================
if [ -f "/usr/local/bin/linux-guardian" ]; then
    $SUDO rm -f "/usr/local/bin/linux-guardian"
    echo -e "${GREEN}✓ Removed /usr/local/bin/linux-guardian${NC}"
fi

# ============================================
# Remove desktop file
# ============================================
if [ -f "/usr/share/applications/linux-guardian.desktop" ]; then
    $SUDO rm -f "/usr/share/applications/linux-guardian.desktop"
    echo -e "${GREEN}✓ Removed desktop entry${NC}"
fi

# ============================================
# Remove icons
# ============================================
echo -e "${YELLOW}🗑️ Removing icons...${NC}"

for size in 256x256 128x128 64x64 48x48 32x32 16x16; do
    if [ -f "/usr/share/icons/hicolor/$size/apps/linux-guardian.png" ]; then
        $SUDO rm -f "/usr/share/icons/hicolor/$size/apps/linux-guardian.png"
    fi
done

if [ -f "/usr/share/pixmaps/linux-guardian.png" ]; then
    $SUDO rm -f "/usr/share/pixmaps/linux-guardian.png"
fi

echo -e "${GREEN}✓ Icons removed${NC}"

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
# Remove data directory (if selected)
# ============================================
if [ "$REMOVE_DATA" = true ]; then
    echo -e "${YELLOW}🗑️ Removing data directory...${NC}"
    
    if [ -d "$DATA_DIR" ]; then
        rm -rf "$DATA_DIR"
        echo -e "${GREEN}✓ Removed $DATA_DIR${NC}"
    else
        echo -e "${YELLOW}⚠ $DATA_DIR not found${NC}"
    fi
else
    echo -e "${GREEN}✓ Data preserved at: $DATA_DIR${NC}"
fi

# ============================================
# Check for pip packages (optional removal)
# ============================================
echo ""
echo -e "${YELLOW}📦 Do you want to remove pip packages installed for $APP_NAME?${NC}"
read -p "Remove pip packages? [y/N]: " REMOVE_PIP

if [[ "$REMOVE_PIP" =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Removing pip packages...${NC}"
    
    PIP_PACKAGES="psutil requests importlib-metadata platformdirs"
    
    for pkg in $PIP_PACKAGES; do
        if pip3 show "$pkg" >/dev/null 2>&1; then
            echo "Uninstalling $pkg..."
            pip3 uninstall -y "$pkg" 2>/dev/null || true
        fi
    done
    
    echo -e "${GREEN}✓ Pip packages removed${NC}"
fi

# ============================================
# Done
# ============================================
echo ""
echo -e "${GREEN}====================================${NC}"
echo -e "${GREEN} ✅ $APP_NAME uninstalled successfully${NC}"
echo -e "${GREEN}====================================${NC}"
echo ""

if [ "$REMOVE_DATA" = false ]; then
    echo -e "${YELLOW}💡 Your data (quarantine, logs) is still at:${NC}"
    echo "   $DATA_DIR"
    echo ""
    echo -e "${YELLOW}   To remove it manually:${NC}"
    echo "   rm -rf $DATA_DIR"
fi

echo ""
echo -e "${GREEN}🛡️  Thank you for using Linux Guardian!${NC}"