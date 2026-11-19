"""统一视觉：奶油纸张、蜜桃与青绿，和原型里的织女配色呼应。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SPRITES = ASSETS / "sprites"

CHARACTER_ORDER = ("huahua", "xixi")
CHARACTERS = {
    "huahua": {
        "name": "华华",
        "tagline": "温柔小织女",
        "description": "桃粉披帛、青绿裙子，怀里抱着小梭子。说话轻声细语，喜欢把灵感织成画面。",
        "accent": "#E98F73",
        "soft": "#FFE5D7",
    },
    "xixi": {
        "name": "熙熙",
        "tagline": "元气小胖墩",
        "description": "细银椭圆眼镜、珊瑚橘卫衣，抱着奶油白长耳兔。说话轻快，行动力满格。",
        "accent": "#F0644B",
        "soft": "#FFE4C9",
    },
}


def character_key(key: str | None) -> str:
    return key if key in CHARACTERS else "huahua"


def character_name(key: str | None) -> str:
    return CHARACTERS[character_key(key)]["name"]


def sprite_dir(key: str | None) -> Path:
    return SPRITES / character_key(key)


def character_avatar_path(key: str | None) -> Path:
    return ASSETS / "avatars" / f"{character_key(key)}.png"


def character_icon_path(key: str | None) -> Path:
    return ASSETS / "icons" / f"{character_key(key)}.ico"

CREAM = "#FFF8F1"
CREAM_2 = "#FFF2E7"
PAPER = "#FFFCF8"
INK = "#3F3433"
INK_SOFT = "#6F605D"
MUTED = "#9C8A85"
PEACH = "#F4B49C"
PEACH_DEEP = "#E98F73"
PEACH_SOFT = "#FFE5D7"
TEAL = "#5BB8AF"
TEAL_DEEP = "#3E9991"
TEAL_SOFT = "#E2F4F0"
GOLD = "#E6B35B"
LINE = "#F1DED3"
LINE_STRONG = "#E9C9BA"
WHITE = "#FFFFFF"
DANGER = "#D96A5D"
OK = "#4FAE86"

FONT_UI = "Microsoft YaHei UI"
FONT_DISPLAY = "Microsoft YaHei UI"
FONT_ICON = "Segoe Fluent Icons"

ICON_GLYPHS = {
    "settings": "\uE713",
    "close": "\uE8BB",
    "minimize": "\uE921",
    "history": "\uE81C",
    "send": "\uE724",
    "attach": "\uE723",
    "camera": "\uE722",
    "chat": "\uE8BD",
    "image": "\uE91B",
    "video": "\uE714",
    "sparkle": "\uE735",
    "folder": "\uE8B7",
    "copy": "\uE8C8",
    "download": "\uE896",
    "play": "\uE768",
    "refresh": "\uE72C",
    "plus": "\uE710",
    "delete": "\uE74D",
    "back": "\uE72B",
    "search": "\uE721",
    "heart": "\uE00B",
    "bell": "\uE7E7",
    "eye": "\uE7B3",
    "hide": "\uED1A",
    "mic": "\uE720",
    "check": "\uE73E",
    "more": "\uE712",
    "edit": "\uE70F",
    "expand": "\uE740",
    "pin": "\uE718",
    "clock": "\uE823",
    "star": "\uE734",
    "globe": "\uE774",
    "shield": "\uE83D",
    "palette": "\uE790",
    "drive": "\uEDA2",
}


def icon_glyph(name: str) -> str:
    return ICON_GLYPHS.get(name, "\uE8BD")


def font(size: int = 10, weight: int | QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(FONT_UI, size)
    f.setWeight(QFont.Weight(weight))
    return f


_ICON_FONT_FAMILY: str | None = None


def icon_font(size: int = 11) -> QFont:
    global _ICON_FONT_FAMILY
    if _ICON_FONT_FAMILY is None:
        try:
            from PySide6.QtGui import QFontDatabase

            families = set(QFontDatabase.families())
            _ICON_FONT_FAMILY = next(
                (name for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol") if name in families),
                FONT_ICON,
            )
        except Exception:
            _ICON_FONT_FAMILY = FONT_ICON
    f = QFont(_ICON_FONT_FAMILY, size)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def pixmap(name: str, character: str = "huahua") -> QPixmap:
    folder = sprite_dir(character)
    p = folder / f"{name}.png"
    if not p.exists():
        p = folder / "idle.png"
    if not p.exists():
        p = SPRITES / "huahua" / "idle.png"
    return QPixmap(str(p))


def qss() -> str:
    return f"""
    * {{
        font-family: "{FONT_UI}";
        outline: none;
    }}
    QWidget {{
        color: {INK};
        font-size: 13px;
    }}
    QToolTip {{
        background: {INK};
        color: {CREAM};
        border: none;
        border-radius: 7px;
        padding: 6px 9px;
        font-size: 12px;
    }}
    QWidget#Root, QWidget#Transparent {{
        background: transparent;
    }}
    QFrame#Panel {{
        background: rgba(255, 252, 248, 0.985);
        border: 1px solid {LINE};
        border-radius: 26px;
    }}
    QFrame#SoftCard {{
        background: {PAPER};
        border: 1px solid {LINE};
        border-radius: 18px;
    }}
    QFrame#TintCard {{
        background: {PEACH_SOFT};
        border: 1px solid #F8D1C0;
        border-radius: 18px;
    }}
    QFrame#TealCard {{
        background: {TEAL_SOFT};
        border: 1px solid #CBE9E4;
        border-radius: 18px;
    }}
    QFrame#ContextCard {{
        background: #FFFBF8;
        border: 1px solid #F0DFD4;
        border-radius: 15px;
    }}
    QLabel#Title {{
        font-size: 18px;
        font-weight: 700;
        color: {INK};
    }}
    QLabel#SubTitle {{
        color: {MUTED};
        font-size: 11px;
    }}
    QLabel#SectionTitle {{
        font-size: 14px;
        font-weight: 700;
        color: {INK};
    }}
    QLabel#Hint {{
        color: {MUTED};
        font-size: 11px;
    }}
    QLabel#Tiny {{
        color: {MUTED};
        font-size: 10px;
    }}
    QLabel#Badge {{
        color: {TEAL_DEEP};
        background: {TEAL_SOFT};
        border: 1px solid #CBE9E4;
        border-radius: 9px;
        padding: 2px 7px;
        font-size: 10px;
        font-weight: 600;
    }}
    QPushButton {{
        font-family: "{FONT_UI}";
        font-size: 13px;
    }}
    QPushButton#Primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {PEACH}, stop:1 {PEACH_DEEP});
        color: white;
        border: none;
        border-radius: 15px;
        padding: 8px 18px;
        font-weight: 700;
    }}
    QPushButton#Primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F8C0A9, stop:1 #E78366);
    }}
    QPushButton#Primary:pressed {{
        background: {PEACH_DEEP};
    }}
    QPushButton#Primary:disabled {{
        background: #EFD9CF;
        color: #B9A7A0;
    }}
    QPushButton#Teal {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {TEAL}, stop:1 {TEAL_DEEP});
        color: white;
        border: none;
        border-radius: 13px;
        padding: 7px 15px;
        font-weight: 600;
    }}
    QPushButton#Teal:hover {{ background: {TEAL_DEEP}; }}
    QPushButton#Ghost {{
        background: transparent;
        color: {INK_SOFT};
        border: 1px solid transparent;
        border-radius: 12px;
        padding: 7px 12px;
    }}
    QPushButton#Ghost:hover {{
        background: {CREAM_2};
        border-color: {LINE};
        color: {INK};
    }}
    QPushButton#Icon {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 9px;
        color: {INK_SOFT};
        font-family: "Segoe Fluent Icons", "Segoe MDL2 Assets", "Segoe UI Symbol";
        font-size: 15px;
        padding: 0;
    }}
    QPushButton#Icon:hover {{
        background: {CREAM_2};
        border-color: {LINE};
        color: {INK};
    }}
    QPushButton#Icon:pressed {{ background: {PEACH_SOFT}; }}
    QPushButton#ModeTab {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 13px;
        color: {MUTED};
        padding: 8px 10px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#ModeTab:hover {{ background: {CREAM_2}; color: {INK_SOFT}; }}
    QPushButton#ModeTab:checked {{
        background: #FFFBF8;
        color: {PEACH_DEEP};
        border-color: #F1D3C4;
    }}
    QFrame#Segmented {{
        background: #F7EDE7;
        border: 1px solid #EED9CD;
        border-radius: 12px;
    }}
    QPushButton#Segment {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 9px;
        color: #9A8178;
        padding: 3px 8px;
        font-size: 10px;
        font-weight: 600;
    }}
    QPushButton#Segment:hover {{
        background: #FCF5F0;
        color: {INK_SOFT};
    }}
    QPushButton#Segment:checked {{
        background: white;
        border-color: #F0D4C7;
        color: {PEACH_DEEP};
    }}
    QPushButton#Segment:pressed {{ background: {PEACH_SOFT}; }}
    QPushButton#ThoughtToggle {{
        background: transparent;
        border: none;
        color: {MUTED};
        padding: 2px 0;
        font-size: 10px;
        text-align: left;
    }}
    QPushButton#ThoughtToggle:hover {{ color: {PEACH_DEEP}; }}
    QPushButton#Chip {{
        background: white;
        color: {INK_SOFT};
        border: 1px solid {LINE};
        border-radius: 14px;
        padding: 7px 12px;
        font-size: 12px;
        text-align: left;
    }}
    QPushButton#Chip:hover {{
        border-color: {PEACH};
        background: #FFF7F2;
        color: {PEACH_DEEP};
    }}
    QPushButton#NavTab {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 12px;
        color: {INK_SOFT};
        padding: 10px 13px;
        text-align: left;
        font-weight: 600;
    }}
    QPushButton#NavTab:hover {{ background: {CREAM_2}; }}
    QPushButton#NavTab:checked {{
        background: {PEACH_SOFT};
        color: {PEACH_DEEP};
        border-color: #F6D3C2;
    }}
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: white;
        border: 1px solid {LINE};
        border-radius: 11px;
        padding: 7px 10px;
        selection-background-color: {PEACH};
        selection-color: white;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border-color: {PEACH};
        background: #FFFEFC;
    }}
    QComboBox {{ padding-right: 26px; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow {{
        image: url("{ASSETS.as_posix()}/icons/chevron_down.png");
        width: 10px;
        height: 10px;
    }}
    QPlainTextEdit#Composer {{
        background: transparent;
        border: none;
        padding: 2px 2px;
        font-size: 13px;
    }}
    QComboBox QAbstractItemView {{
        background: white;
        border: 1px solid {LINE};
        border-radius: 9px;
        padding: 4px;
        selection-background-color: {PEACH_SOFT};
        selection-color: {INK};
        outline: none;
    }}
    QCheckBox {{
        spacing: 9px;
        color: {INK_SOFT};
    }}
    QCheckBox::indicator {{
        width: 36px; height: 20px;
        border: none;
        image: url("{ASSETS.as_posix()}/switch_off.png");
    }}
    QCheckBox::indicator:checked {{
        image: url("{ASSETS.as_posix()}/switch_on.png");
    }}
    QSlider::groove:horizontal {{
        height: 6px; border-radius: 3px; background: #F1E1D8;
    }}
    QSlider::sub-page:horizontal {{
        height: 6px; border-radius: 3px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {PEACH}, stop:1 {PEACH_DEEP});
    }}
    QSlider::handle:horizontal {{
        width: 18px; height: 18px; margin: -6px 0;
        border-radius: 9px;
        background: white;
        border: 2px solid {PEACH_DEEP};
    }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{
        background: transparent; width: 8px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: #E8D3C9; border-radius: 4px; min-height: 26px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {PEACH}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ height: 8px; background: transparent; }}
    QScrollBar::handle:horizontal {{ background: #E8D3C9; border-radius: 4px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QMenu {{
        background: {PAPER};
        border: 1px solid {LINE_STRONG};
        border-radius: 12px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 8px 26px 8px 12px;
        border-radius: 8px;
        color: {INK};
    }}
    QMenu::item:selected {{ background: {PEACH_SOFT}; color: {PEACH_DEEP}; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: 5px 8px; }}
    QMenu::indicator {{ width: 15px; height: 15px; }}
    QToolTip {{
        background: #5A423A;
        color: #FFF9F4;
        border: none;
        border-radius: 7px;
        padding: 6px 8px;
        font-size: 11px;
    }}
    QFrame#Divider {{ background: {LINE}; max-height: 1px; border: none; }}
    QLabel#BubbleText {{
        color: {INK};
        font-size: 12px;
        line-height: 19px;
    }}
    QLabel#BubbleSub {{
        color: {MUTED};
        font-size: 10px;
    }}
    QLabel#ErrorText {{ color: {DANGER}; font-size: 12px; }}
    QLabel#OkText {{ color: {OK}; font-size: 12px; }}
    QProgressBar {{
        background: {CREAM_2}; border: none; border-radius: 3px; height: 6px;
        text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{
        border-radius: 3px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {PEACH}, stop:1 {TEAL});
    }}
    QToolButton {{
        background: transparent; border: none; border-radius: 9px; padding: 5px;
    }}
    QToolButton:hover {{ background: {CREAM_2}; }}
    """


def draw_soft_shadow(p: QPainter, rect, radius: int = 20, color=QColor(84, 50, 36, 26), dy: int = 8, blur: int = 20):
    """Affordable layered shadow for small custom widgets."""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(blur, 0, -2):
        a = int(color.alpha() * (1 - i / blur) * 0.22)
        c = QColor(color)
        c.setAlpha(max(0, a))
        p.setBrush(c)
        off = dy * (1 - i / blur)
        p.drawRoundedRect(rect.adjusted(-i / 2, -i / 2 + off, i / 2, i / 2 + off), radius + i / 2, radius + i / 2)
    p.restore()


def paint_round_pixmap(p: QPainter, pm: QPixmap, rect, radius: int | None = None):
    p.save()
    path_radius = radius if radius is not None else min(rect.width(), rect.height()) / 2
    p.setClipPath(_round_path(rect, path_radius))
    p.drawPixmap(rect, pm, pm.rect())
    p.restore()


def _round_path(rect, radius):
    from PySide6.QtGui import QPainterPath

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


_AVATAR_CACHE: dict[tuple[int, str], QPixmap] = {}


def avatar_pixmap(size: int, character: str = "huahua") -> QPixmap:
    key = character_key(character)
    cache_key = (size, key)
    if cache_key not in _AVATAR_CACHE:
        pm = QPixmap(str(character_avatar_path(key)))
        if pm.isNull():
            pm = QPixmap(str(ASSETS / "avatar.png"))
        _AVATAR_CACHE[cache_key] = pm.scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
    return _AVATAR_CACHE[cache_key]


def gradient_brush(rect, c1: str = PEACH_SOFT, c2: str = TEAL_SOFT) -> QLinearGradient:
    g = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.bottomRight()))
    g.setColorAt(0, QColor(c1))
    g.setColorAt(1, QColor(c2))
    return g


def pen(color: str, width: float = 1.0) -> QPen:
    p = QPen(QColor(color))
    p.setWidthF(width)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    return p
