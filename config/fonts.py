"""
Font configuration for Instagram Stories text overlays.

Defines 20 fonts for round-robin rotation across story series.
All fonts are from Google Fonts with OFL (Open Font License).

Font rotation ensures visual variety:
- Each story series uses ONE font (consistency within series)
- Next series uses the NEXT font in rotation (variety across series)
- After 20 series, rotation cycles back to first font
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


# 20 fonts for rotation, ordered for visual variety
# Mix of categories to ensure diverse appearance
# URLs verified and working as of 2026-01
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
        name="Bebas Neue",
        filename="BebasNeue-Regular.ttf",
        url="https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf",
        category="display",
        weight="Regular",  # Bebas Neue only has Regular weight (already bold look)
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
    ),

    # === Script/Handwriting fonts (creative, personal) ===
    FontConfig(
        name="Shadows Into Light",
        filename="ShadowsIntoLight.ttf",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/shadowsintolight/ShadowsIntoLight.ttf",
        category="script",
        weight="Regular",
    ),
    FontConfig(
        name="Pacifico",
        filename="Pacifico-Regular.ttf",
        url="https://github.com/googlefonts/Pacifico/raw/main/fonts/ttf/Pacifico-Regular.ttf",
        category="script",
        weight="Regular",
    ),
    FontConfig(
        name="Caveat",
        filename="Caveat-Bold.ttf",
        url="https://github.com/googlefonts/caveat/raw/main/fonts/ttf/Caveat-Bold.ttf",
        category="script",
    ),
    FontConfig(
        name="Great Vibes",
        filename="GreatVibes-Regular.ttf",
        url="https://github.com/google/fonts/raw/main/ofl/greatvibes/GreatVibes-Regular.ttf",
        category="script",
        weight="Regular",
    ),
    FontConfig(
        name="Architects Daughter",
        filename="ArchitectsDaughter-Regular.ttf",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/architectsdaughter/ArchitectsDaughter-Regular.ttf",
        category="script",
        weight="Regular",
    ),

    # === Display fonts (decorative, eye-catching) ===
    FontConfig(
        name="Lobster",
        filename="Lobster-Regular.ttf",
        url="https://github.com/google/fonts/raw/main/ofl/lobster/Lobster-Regular.ttf",
        category="display",
        weight="Regular",
    ),
    FontConfig(
        name="Righteous",
        filename="Righteous-Regular.ttf",
        url="https://raw.githubusercontent.com/google/fonts/main/ofl/righteous/Righteous-Regular.ttf",
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


# Legacy font list for backward compatibility with existing download script
FONT_FILES_LEGACY = {
    "Montserrat-Bold.ttf": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf",
    "Montserrat-SemiBold.ttf": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-SemiBold.ttf",
    "Montserrat-Medium.ttf": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Medium.ttf",
    "Montserrat-Regular.ttf": "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Regular.ttf",
    "OpenSans-Bold.ttf": "https://github.com/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-Bold.ttf",
    "OpenSans-SemiBold.ttf": "https://github.com/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-SemiBold.ttf",
    "OpenSans-Regular.ttf": "https://github.com/googlefonts/opensans/raw/main/fonts/ttf/OpenSans-Regular.ttf",
}
