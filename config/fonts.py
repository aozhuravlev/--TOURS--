"""
Font configuration for Instagram Stories text overlays.

Defines fonts for round-robin rotation across story series.
All fonts are from Google Fonts with OFL (Open Font License).
**All fonts support Cyrillic (Russian) text.**

Font rotation ensures visual variety:
- Each story series uses ONE font (consistency within series)
- Next series uses the NEXT font in rotation (variety across series)
- After cycling through all fonts, rotation starts over
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FontConfig:
    """Single font configuration."""
    name: str  # Display name (e.g., "Montserrat")
    filename: str  # File name (e.g., "Montserrat-Bold.ttf")
    url: str  # Download URL from Google Fonts GitHub
    category: str  # "sans-serif", "serif", "script", "display"
    weight: str = "Bold"  # Font weight
    size_multiplier: float = 1.0  # Size adjustment (e.g., 1.5 for Caveat)
    is_bold: bool = True  # If True, no background needed (shadow only)


# 20 fonts with Cyrillic support - all already downloaded and verified
FONT_ROTATION: list[FontConfig] = [
    # === Sans-serif fonts (modern, clean) ===
    FontConfig(
        name="Montserrat",
        filename="Montserrat-Bold.ttf",
        url="https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf",
        category="sans-serif",
    ),
    FontConfig(
        name="Poppins",
        filename="Poppins-Bold.ttf",
        url="https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf",
        category="sans-serif",
    ),
    FontConfig(
        name="Roboto",
        filename="Roboto-Bold.ttf",
        url="https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf",
        category="sans-serif",
    ),
    FontConfig(
        name="Lato",
        filename="Lato-Bold.ttf",
        url="https://github.com/google/fonts/raw/main/ofl/lato/Lato-Bold.ttf",
        category="sans-serif",
    ),
    FontConfig(
        name="Open Sans",
        filename="OpenSans-Bold.ttf",
        url="https://github.com/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-Bold.ttf",
        category="sans-serif",
    ),
    FontConfig(
        name="Fira Sans",
        filename="FiraSans-Bold.ttf",
        url="https://raw.githubusercontent.com/mozilla/Fira/master/ttf/FiraSans-Bold.ttf",
        category="sans-serif",
    ),
    FontConfig(
        name="Source Sans",
        filename="SourceSans3-Bold.ttf",
        url="https://raw.githubusercontent.com/adobe-fonts/source-sans/release/TTF/SourceSans3-Bold.ttf",
        category="sans-serif",
    ),
    FontConfig(
        name="Oswald",
        filename="Oswald-Bold.ttf",
        url="https://github.com/googlefonts/OswaldFont/raw/main/fonts/ttf/Oswald-Bold.ttf",
        category="sans-serif",
    ),
    FontConfig(
        name="Ubuntu",
        filename="Ubuntu-Bold.ttf",
        url="https://github.com/google/fonts/raw/main/ufl/ubuntu/Ubuntu-Bold.ttf",
        category="sans-serif",
    ),

    # === Serif fonts (elegant, classic) ===
    FontConfig(
        name="Spectral",
        filename="Spectral-Bold.ttf",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/spectral/Spectral-Bold.ttf",
        category="serif",
    ),
    FontConfig(
        name="Merriweather",
        filename="Merriweather-Bold.ttf",
        url="https://github.com/SorkinType/Merriweather/raw/master/fonts/ttf/Merriweather-Bold.ttf",
        category="serif",
    ),
    FontConfig(
        name="Crimson Text",
        filename="CrimsonText-Bold.ttf",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/crimsontext/CrimsonText-Bold.ttf",
        category="serif",
    ),
    FontConfig(
        name="Alice",
        filename="Alice-Regular.ttf",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/alice/Alice-Regular.ttf",
        category="serif",
        weight="Regular",
        is_bold=False,  # Needs background
    ),
    FontConfig(
        name="Cormorant",
        filename="Cormorant-Bold.ttf",
        url="https://github.com/CatharsisFonts/Cormorant/raw/master/fonts/ttf/Cormorant-Bold.ttf",
        category="serif",
    ),
    FontConfig(
        name="Philosopher",
        filename="Philosopher-Bold.ttf",
        url="https://github.com/google/fonts/raw/main/ofl/philosopher/Philosopher-Bold.ttf",
        category="serif",
    ),
    FontConfig(
        name="Forum",
        filename="Forum-Regular.ttf",
        url="https://github.com/google/fonts/raw/main/ofl/forum/Forum-Regular.ttf",
        category="serif",
        weight="Regular",
        is_bold=False,  # Needs background
    ),

    # === Script/Handwriting fonts with Cyrillic ===
    FontConfig(
        name="Caveat",
        filename="Caveat-Bold.ttf",
        url="https://github.com/googlefonts/caveat/raw/main/fonts/ttf/Caveat-Bold.ttf",
        category="script",
        size_multiplier=1.5,  # Script font needs larger size
    ),
    FontConfig(
        name="Marck Script",
        filename="MarckScript-Regular.ttf",
        url="https://github.com/google/fonts/raw/main/ofl/marckscript/MarckScript-Regular.ttf",
        category="script",
        weight="Regular",
        size_multiplier=1.3,  # Script font
        is_bold=False,  # Needs background
    ),
    FontConfig(
        name="Bad Script",
        filename="BadScript-Regular.ttf",
        url="https://github.com/google/fonts/raw/main/ofl/badscript/BadScript-Regular.ttf",
        category="script",
        weight="Regular",
        size_multiplier=1.3,  # Script font
        is_bold=False,  # Needs background
    ),

    # === Display fonts with Cyrillic ===
    FontConfig(
        name="Lobster",
        filename="Lobster-Regular.ttf",
        url="https://github.com/google/fonts/raw/main/ofl/lobster/Lobster-Regular.ttf",
        category="display",
        weight="Regular",
    ),
]


def get_font_filenames() -> list[str]:
    """Get list of all font filenames for downloading."""
    return [font.filename for font in FONT_ROTATION]


def get_font_by_index(index: int) -> FontConfig:
    """
    Get font config by index (with wrapping).

    Args:
        index: Font index (will wrap if > total fonts)

    Returns:
        FontConfig for the font at given index
    """
    return FONT_ROTATION[index % len(FONT_ROTATION)]


def get_total_fonts() -> int:
    """Get total number of fonts in rotation."""
    return len(FONT_ROTATION)


def get_fonts_by_category(category: str) -> list[FontConfig]:
    """Get all fonts of a specific category."""
    return [f for f in FONT_ROTATION if f.category == category]
