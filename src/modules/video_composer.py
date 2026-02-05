"""
Video composer using FFmpeg.

Creates Instagram Stories videos from:
- Static photo (scaled/cropped to 9:16)
- Music track (trimmed to duration)

Supports:
- Motion effects (zoom, pan, Ken Burns variants)
- Text overlays with semi-transparent background
"""

import logging
import subprocess
import shutil
import textwrap
import tempfile
import random
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageOps

# Import imagetext-py for emoji support
try:
    from imagetext_py import FontDB, Writer, Paint, EmojiOptions
    IMAGETEXT_AVAILABLE = True
except ImportError:
    IMAGETEXT_AVAILABLE = False

# Enable AVIF/HEIF support
try:
    import pillow_heif
    pillow_heif.register_heif_opener()  # Also handles AVIF
except ImportError:
    pass  # AVIF/HEIF support not available

# Import font rotation config
try:
    from config.fonts import FONT_ROTATION, get_font_by_index as get_font_config, get_total_fonts
    FONT_ROTATION_AVAILABLE = True
except ImportError:
    FONT_ROTATION_AVAILABLE = False

logger = logging.getLogger(__name__)


# Default fonts path (will be set during initialization)
DEFAULT_FONTS_DIR = Path(__file__).parent.parent.parent / "assets" / "fonts"


def _get_ffmpeg_path() -> str:
    """
    Get path to FFmpeg executable.

    Tries imageio-ffmpeg first (bundled with full codecs),
    falls back to system FFmpeg.
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg
        raise RuntimeError(
            "FFmpeg not found. Install via:\n"
            "  pip install imageio-ffmpeg\n"
            "  or: sudo apt install ffmpeg"
        )


# Instagram safe zones (pixels from edge)
SAFE_TOP = 250      # Status bar + profile header
SAFE_BOTTOM = 250   # Swipe up / reply area
SAFE_SIDE = 100     # Left/right margins

# Position variations for text
TEXT_POSITIONS = [
    ("bottom", "center"),
    ("bottom", "left"),
    ("bottom", "right"),
    ("top", "center"),
    ("top", "left"),
    ("top", "right"),
]


# Probability of choosing static (no motion) effect
# Set to 1.0 to disable motion effects (client feedback: effects interfere with text readability)
STATIC_PROBABILITY = 1.0


@dataclass
class MotionEffect:
    """A visual motion effect for story videos."""
    name: str
    z_expr: str  # FFmpeg zoompan z expression (empty for static)
    x_expr: str  # FFmpeg zoompan x expression
    y_expr: str  # FFmpeg zoompan y expression

    @property
    def is_static(self) -> bool:
        return self.name == "static"


# Motion effects available for random selection
MOTION_EFFECTS = [
    MotionEffect(
        name="zoom_in_center",
        z_expr="min(zoom+{zoom_speed:.6f},1.2)",
        x_expr="iw/2-(iw/zoom/2)",
        y_expr="ih/2-(ih/zoom/2)",
    ),
    MotionEffect(
        name="zoom_out_center",
        z_expr="max(1.2-on*0.2/{total_frames},1.0)",
        x_expr="iw/2-(iw/zoom/2)",
        y_expr="ih/2-(ih/zoom/2)",
    ),
    MotionEffect(
        name="pan_left_right",
        z_expr="1.15",
        x_expr="on*(iw-iw/zoom)/{total_frames}",
        y_expr="ih/2-(ih/zoom/2)",
    ),
    MotionEffect(
        name="pan_right_left",
        z_expr="1.15",
        x_expr="(iw-iw/zoom)-on*(iw-iw/zoom)/{total_frames}",
        y_expr="ih/2-(ih/zoom/2)",
    ),
    MotionEffect(
        name="zoom_in_top_left",
        z_expr="min(zoom+{zoom_speed:.6f},1.2)",
        x_expr="0",
        y_expr="0",
    ),
    MotionEffect(
        name="zoom_in_top_right",
        z_expr="min(zoom+{zoom_speed:.6f},1.2)",
        x_expr="iw-iw/zoom",
        y_expr="0",
    ),
    MotionEffect(
        name="zoom_in_bottom_left",
        z_expr="min(zoom+{zoom_speed:.6f},1.2)",
        x_expr="0",
        y_expr="ih-ih/zoom",
    ),
    MotionEffect(
        name="zoom_in_bottom_right",
        z_expr="min(zoom+{zoom_speed:.6f},1.2)",
        x_expr="iw-iw/zoom",
        y_expr="ih-ih/zoom",
    ),
    MotionEffect(
        name="static",
        z_expr="",
        x_expr="",
        y_expr="",
    ),
]

# Lookup by name
_EFFECTS_BY_NAME = {e.name: e for e in MOTION_EFFECTS}
# Non-static effects for random selection
_NON_STATIC_EFFECTS = [e for e in MOTION_EFFECTS if not e.is_static]


@dataclass
class TextOverlayConfig:
    """Text overlay settings for Stories."""
    font_path: Optional[Path] = None  # Path to .ttf font file
    font_size: int = 54  # Base font size in pixels (+20% from 45)
    font_color: str = "white"
    background_color: str = "black"
    background_opacity: float = 0.6  # 0.0 - 1.0
    padding: int = 20  # Padding around text
    shadow_offset: int = 3  # Shadow offset in pixels
    shadow_color: str = "black"
    max_width_chars: int = 35  # Max characters per line before wrap (wider = flatter)
    line_spacing: int = 1  # Space between lines (imagetext-py multiplier)
    emoji_font_path: Optional[Path] = None  # Fallback font for emoji
    # Per-story variations
    position: tuple = ("bottom", "center")  # (vertical, horizontal)
    use_background: bool = True  # If False, only shadow (for bold fonts)
    size_multiplier: float = 1.0  # Font size adjustment


@dataclass
class VideoConfig:
    """Video composition settings."""
    width: int = 1080
    height: int = 1920
    duration: int = 15  # seconds
    bitrate: str = "4000k"
    audio_bitrate: str = "192k"
    fps: int = 30
    codec: str = "libx264"
    preset: str = "medium"  # ultrafast, fast, medium, slow
    crf: int = 23  # Quality: 18-28, lower = better
    text_overlay: TextOverlayConfig = field(default_factory=TextOverlayConfig)


class VideoComposer:
    """
    Creates video files from photos and music using FFmpeg.

    Supports:
    - Basic static photo + music
    - Ken Burns effect (slow zoom)
    - Text overlays with semi-transparent background
    - Custom duration matching music length
    """

    def __init__(
        self,
        output_dir: Path,
        config: Optional[VideoConfig] = None,
        fonts_dir: Optional[Path] = None,
    ):
        """
        Initialize video composer.

        Args:
            output_dir: Directory for output video files
            config: Video settings (uses defaults if not provided)
            fonts_dir: Directory containing font files
        """
        self.output_dir = Path(output_dir)
        self.config = config or VideoConfig()
        self.ffmpeg_path = _get_ffmpeg_path()
        self.fonts_dir = Path(fonts_dir) if fonts_dir else DEFAULT_FONTS_DIR

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Find default font
        self._default_font = self._find_default_font()

        # Find emoji font for fallback
        self._emoji_font = self._find_emoji_font()

        logger.info(f"Using FFmpeg: {self.ffmpeg_path}")
        if self._default_font:
            logger.info(f"Default font: {self._default_font.name}")
        if self._emoji_font:
            logger.info(f"Emoji font: {self._emoji_font.name}")

    def _find_default_font(self) -> Optional[Path]:
        """Find a suitable default font for text overlays."""
        if not self.fonts_dir.exists():
            logger.warning(f"Fonts directory not found: {self.fonts_dir}")
            return None

        # Priority order for fonts
        preferred_fonts = [
            "Montserrat-Bold.ttf",
            "Montserrat-SemiBold.ttf",
            "Roboto-Bold.ttf",
            "OpenSans-Bold.ttf",
            "NotoSans-Bold.ttf",
        ]

        # Try preferred fonts first
        for font_name in preferred_fonts:
            font_path = self.fonts_dir / font_name
            if font_path.exists():
                return font_path

        # Fall back to any .ttf file
        ttf_files = list(self.fonts_dir.glob("*.ttf"))
        if ttf_files:
            return ttf_files[0]

        return None

    def _find_emoji_font(self) -> Optional[Path]:
        """Find emoji font for fallback rendering."""
        if not self.fonts_dir.exists():
            return None

        # Emoji font names
        emoji_fonts = [
            "NotoEmoji-Regular.ttf",
            "NotoColorEmoji.ttf",
            "NotoEmoji-Bold.ttf",
        ]

        for font_name in emoji_fonts:
            font_path = self.fonts_dir / font_name
            if font_path.exists():
                return font_path

        return None

    def _is_emoji(self, char: str) -> bool:
        """Check if character is an emoji."""
        code = ord(char)
        # Emoji ranges (simplified)
        emoji_ranges = [
            (0x1F600, 0x1F64F),  # Emoticons
            (0x1F300, 0x1F5FF),  # Misc Symbols and Pictographs
            (0x1F680, 0x1F6FF),  # Transport and Map
            (0x1F1E0, 0x1F1FF),  # Flags
            (0x2600, 0x26FF),    # Misc symbols
            (0x2700, 0x27BF),    # Dingbats
            (0xFE00, 0xFE0F),    # Variation Selectors
            (0x1F900, 0x1F9FF),  # Supplemental Symbols
            (0x1FA00, 0x1FA6F),  # Chess Symbols
            (0x1FA70, 0x1FAFF),  # Symbols Extended-A
            (0x231A, 0x231B),    # Watch, Hourglass
            (0x23E9, 0x23F3),    # AV symbols
            (0x23F8, 0x23FA),    # AV symbols
            (0x25AA, 0x25AB),    # Squares
            (0x25B6, 0x25B6),    # Play button
            (0x25C0, 0x25C0),    # Reverse button
            (0x25FB, 0x25FE),    # Squares
            (0x2614, 0x2615),    # Umbrella, Hot beverage
            (0x2648, 0x2653),    # Zodiac
            (0x267F, 0x267F),    # Wheelchair
            (0x2693, 0x2693),    # Anchor
            (0x26A1, 0x26A1),    # High voltage
            (0x26AA, 0x26AB),    # Circles
            (0x26BD, 0x26BE),    # Soccer, Baseball
            (0x26C4, 0x26C5),    # Snowman, Sun
            (0x26CE, 0x26CE),    # Ophiuchus
            (0x26D4, 0x26D4),    # No entry
            (0x26EA, 0x26EA),    # Church
            (0x26F2, 0x26F3),    # Fountain, Golf
            (0x26F5, 0x26F5),    # Sailboat
            (0x26FA, 0x26FA),    # Tent
            (0x26FD, 0x26FD),    # Fuel pump
            (0x2702, 0x2702),    # Scissors
            (0x2705, 0x2705),    # Check mark
            (0x2708, 0x270D),    # Airplane to Writing hand
            (0x270F, 0x270F),    # Pencil
            (0x2712, 0x2712),    # Black nib
            (0x2714, 0x2714),    # Check mark
            (0x2716, 0x2716),    # X mark
            (0x271D, 0x271D),    # Cross
            (0x2721, 0x2721),    # Star of David
            (0x2728, 0x2728),    # Sparkles
            (0x2733, 0x2734),    # Eight spoked asterisk
            (0x2744, 0x2744),    # Snowflake
            (0x2747, 0x2747),    # Sparkle
            (0x274C, 0x274C),    # Cross mark
            (0x274E, 0x274E),    # Cross mark
            (0x2753, 0x2755),    # Question marks
            (0x2757, 0x2757),    # Exclamation
            (0x2763, 0x2764),    # Heart exclamation, Heart
            (0x2795, 0x2797),    # Plus, Minus, Divide
            (0x27A1, 0x27A1),    # Right arrow
            (0x27B0, 0x27B0),    # Curly loop
            (0x27BF, 0x27BF),    # Double curly loop
            (0x2934, 0x2935),    # Arrows
            (0x2B05, 0x2B07),    # Arrows
            (0x2B1B, 0x2B1C),    # Squares
            (0x2B50, 0x2B50),    # Star
            (0x2B55, 0x2B55),    # Circle
            (0x3030, 0x3030),    # Wavy dash
            (0x303D, 0x303D),    # Part alternation mark
            (0x3297, 0x3297),    # Circled Ideograph Congratulation
            (0x3299, 0x3299),    # Circled Ideograph Secret
        ]
        return any(start <= code <= end for start, end in emoji_ranges)

    def _has_emoji(self, text: str) -> bool:
        """Check if text contains any emoji."""
        return any(self._is_emoji(c) for c in text)

    def _strip_emoji(self, text: str) -> str:
        """Remove emoji from text (for fonts that don't support emoji)."""
        return ''.join(c for c in text if not self._is_emoji(c))

    def _calc_line_width(self, draw, line: str, font, emoji_font) -> int:
        """Calculate line width accounting for emoji with different font."""
        if not emoji_font or not self._has_emoji(line):
            bbox = draw.textbbox((0, 0), line, font=font)
            return bbox[2] - bbox[0]

        # Calculate width character by character
        total_width = 0
        for char in line:
            char_font = emoji_font if self._is_emoji(char) else font
            bbox = draw.textbbox((0, 0), char, font=char_font)
            total_width += bbox[2] - bbox[0]
        return total_width

    def _draw_text_with_emoji(
        self,
        draw,
        x: int,
        y: int,
        line: str,
        font,
        emoji_font,
        fill: str,
    ) -> None:
        """Draw text line with emoji support using fallback font."""
        if not emoji_font or not self._has_emoji(line):
            draw.text((x, y), line, font=font, fill=fill)
            return

        # Draw character by character
        current_x = x
        for char in line:
            char_font = emoji_font if self._is_emoji(char) else font
            draw.text((current_x, y), char, font=char_font, fill=fill)
            bbox = draw.textbbox((0, 0), char, font=char_font)
            current_x += bbox[2] - bbox[0]

    def get_available_fonts(self) -> list[Path]:
        """
        Get list of all available font files for rotation.

        Returns:
            List of paths to available font files (TTF/OTF)
        """
        if not self.fonts_dir.exists():
            return []

        # If font rotation config is available, use it to get ordered list
        if FONT_ROTATION_AVAILABLE:
            available = []
            for font_config in FONT_ROTATION:
                font_path = self.fonts_dir / font_config.filename
                if font_path.exists():
                    available.append(font_path)
                else:
                    # Try OTF variant for Inter
                    otf_path = self.fonts_dir / font_config.filename.replace('.ttf', '.otf')
                    if otf_path.exists():
                        available.append(otf_path)
            return available

        # Fallback: return all TTF/OTF files
        ttf_files = list(self.fonts_dir.glob("*.ttf"))
        otf_files = list(self.fonts_dir.glob("*.otf"))
        return sorted(ttf_files + otf_files)

    def get_font_by_index(self, index: int) -> Optional[Path]:
        """
        Get font path by rotation index.

        Uses the font rotation config to map index to font file.
        Falls back to next available font if requested font is missing.

        Args:
            index: Font rotation index (0-based)

        Returns:
            Path to font file, or default font if not found
        """
        if not FONT_ROTATION_AVAILABLE:
            logger.warning("Font rotation config not available, using default font")
            return self._default_font

        total = get_total_fonts()
        wrapped_index = index % total

        # Try to get the font at the requested index
        font_config = get_font_config(wrapped_index)
        font_path = self.fonts_dir / font_config.filename

        # Handle OTF variant (Inter uses .otf)
        if not font_path.exists():
            otf_path = self.fonts_dir / font_config.filename.replace('.ttf', '.otf')
            if otf_path.exists():
                font_path = otf_path

        if font_path.exists():
            logger.info(f"Using font [{wrapped_index}]: {font_config.name}")
            return font_path

        # Font not found, try to find next available font
        logger.warning(f"Font not found: {font_config.filename}, searching for fallback...")

        for offset in range(1, total):
            fallback_index = (wrapped_index + offset) % total
            fallback_config = get_font_config(fallback_index)
            fallback_path = self.fonts_dir / fallback_config.filename

            if not fallback_path.exists():
                otf_path = self.fonts_dir / fallback_config.filename.replace('.ttf', '.otf')
                if otf_path.exists():
                    fallback_path = otf_path

            if fallback_path.exists():
                logger.info(f"Fallback to font [{fallback_index}]: {fallback_config.name}")
                return fallback_path

        # Ultimate fallback to default
        logger.warning("No rotation fonts available, using default font")
        return self._default_font

    def get_font_count(self) -> int:
        """
        Get total number of fonts in rotation.

        Returns:
            Number of fonts configured for rotation
        """
        if FONT_ROTATION_AVAILABLE:
            return get_total_fonts()
        return len(self.get_available_fonts())

    def _wrap_text(self, text: str, max_chars: int = 25) -> list[str]:
        """
        Wrap text into lines that fit within max characters.

        Args:
            text: Text to wrap
            max_chars: Maximum characters per line

        Returns:
            List of text lines
        """
        # Use textwrap for proper word wrapping
        return textwrap.wrap(text, width=max_chars)

    def _escape_text_for_ffmpeg(self, text: str) -> str:
        """
        Escape special characters for FFmpeg drawtext filter.

        FFmpeg drawtext requires escaping: ' : \ and some others
        """
        # Escape backslashes first
        text = text.replace("\\", "\\\\")
        # Escape single quotes
        text = text.replace("'", "\\'")
        # Escape colons (used as parameter separator)
        text = text.replace(":", "\\:")
        return text

    def _add_text_overlay_pillow(
        self,
        image_path: Path,
        text: str,
        output_path: Path,
        text_config: "TextOverlayConfig",
    ) -> Path:
        """
        Add text overlay to image using imagetext-py (with emoji support) or PIL.

        Args:
            image_path: Path to source image
            text: Text to overlay
            output_path: Path for output image
            text_config: Text styling configuration

        Returns:
            Path to image with overlay
        """
        cfg = text_config

        # Load image and apply EXIF orientation
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)  # Fix rotation from EXIF metadata

        # Resize/crop to Instagram Story dimensions (1080x1920)
        target_w, target_h = self.config.width, self.config.height
        img_w, img_h = img.size

        # Calculate scale to cover the target area
        scale = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)

        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Center crop to target dimensions
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))

        # Convert to RGBA for transparency support
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        # Wrap text into lines
        lines = self._wrap_text(text, cfg.max_width_chars)
        wrapped_text = "\n".join(lines)

        # Get font path
        font_path = cfg.font_path or self._default_font

        # Use imagetext-py if available (for emoji support)
        if IMAGETEXT_AVAILABLE:
            img = self._render_text_with_imagetext(
                img, wrapped_text, font_path, cfg, target_w, target_h
            )
        else:
            img = self._render_text_with_pil(
                img, lines, font_path, cfg, target_w, target_h
            )

        # Save as RGB (JPEG doesn't support alpha)
        img_rgb = img.convert("RGB")
        img_rgb.save(output_path, "JPEG", quality=95)

        logger.debug(f"Created image with text overlay: {output_path}")
        return output_path

    def _render_text_with_imagetext(
        self,
        img: Image.Image,
        text: str,
        font_path: Path,
        cfg: "TextOverlayConfig",
        target_w: int,
        target_h: int,
    ) -> Image.Image:
        """Render text with emoji support using imagetext-py."""
        from imagetext_py import FontDB, Paint, EmojiOptions, text_size_multiline, draw_text_multiline, Canvas

        # Register font
        font_name = f"font_{font_path.stem}"
        FontDB.LoadFromPath(font_name, str(font_path))
        FontDB.SetDefaultEmojiOptions(EmojiOptions())
        font = FontDB.Query(font_name)

        # Split text into lines for imagetext-py
        lines = text.split('\n')

        # Calculate actual font size with multiplier
        actual_font_size = int(cfg.font_size * cfg.size_multiplier)

        # Calculate text dimensions
        text_w, text_h = text_size_multiline(
            lines, actual_font_size, font,
            line_spacing=cfg.line_spacing,
            draw_emojis=True,
        )

        # Ensure text fits within screen safe zones
        max_text_w = target_w - 2 * SAFE_SIDE
        if text_w > max_text_w:
            original_text = ' '.join(lines)
            current_max_chars = cfg.max_width_chars
            while text_w > max_text_w and current_max_chars > 15:
                current_max_chars -= 3
                lines = textwrap.wrap(original_text, width=current_max_chars)
                text_w, text_h = text_size_multiline(
                    lines, actual_font_size, font,
                    line_spacing=cfg.line_spacing,
                    draw_emojis=True,
                )
            logger.info(
                f"Re-wrapped text: {cfg.max_width_chars}->{current_max_chars} chars, "
                f"width={text_w}px (max={max_text_w}px)"
            )

        # Calculate position based on cfg.position
        vertical, horizontal = cfg.position
        padding = cfg.padding

        # Vertical position (respecting Instagram safe zones)
        if vertical == "top":
            start_y = SAFE_TOP + padding
        else:  # bottom
            start_y = target_h - SAFE_BOTTOM - text_h - padding

        # Horizontal position
        if horizontal == "left":
            start_x = SAFE_SIDE
        elif horizontal == "right":
            start_x = target_w - text_w - SAFE_SIDE
        else:  # center
            start_x = (target_w - text_w) // 2

        # Draw background only if use_background is True (for non-bold fonts)
        if cfg.use_background:
            bg_left = start_x - padding
            bg_top = start_y - padding
            bg_right = start_x + text_w + padding
            bg_bottom = start_y + text_h + padding

            # Clamp background to screen bounds (safety net)
            bg_left = max(bg_left, 0)
            bg_right = min(bg_right, target_w)

            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            bg_opacity = int(cfg.background_opacity * 255)
            overlay_draw.rounded_rectangle(
                [bg_left, bg_top, bg_right, bg_bottom],
                radius=10,
                fill=(0, 0, 0, bg_opacity),
            )
            img = Image.alpha_composite(img, overlay)

        # Convert PIL Image to imagetext-py Canvas
        canvas = Canvas.from_image(img)

        # Draw shadow (always, for readability)
        shadow_offset = cfg.shadow_offset if cfg.use_background else cfg.shadow_offset + 1
        if shadow_offset > 0:
            draw_text_multiline(
                canvas, lines,
                start_x + shadow_offset, start_y + shadow_offset,
                0, 0, text_w, actual_font_size, font,
                Paint.Color((0, 0, 0, 200)),  # Semi-transparent shadow
                line_spacing=cfg.line_spacing,
                draw_emojis=True,
            )

        # Draw main text
        draw_text_multiline(
            canvas, lines,
            start_x, start_y,
            0, 0, text_w, actual_font_size, font,
            Paint.Color((255, 255, 255, 255)),
            line_spacing=cfg.line_spacing,
            draw_emojis=True,
        )

        # Convert back to PIL Image
        result_img = canvas.to_image()

        logger.debug(f"Rendered text: pos={cfg.position}, bg={cfg.use_background}, size={actual_font_size}")
        return result_img

    def _render_text_with_pil(
        self,
        img: Image.Image,
        lines: list[str],
        font_path: Path,
        cfg: "TextOverlayConfig",
        target_w: int,
        target_h: int,
    ) -> Image.Image:
        """Render text using PIL (fallback without emoji support)."""
        draw = ImageDraw.Draw(img)

        # Load font
        try:
            font = ImageFont.truetype(str(font_path), cfg.font_size)
        except Exception as e:
            logger.warning(f"Failed to load font {font_path}: {e}")
            font = ImageFont.load_default()

        # Strip emoji if present (PIL can't render them)
        text = "\n".join(lines)
        if self._has_emoji(text):
            lines = [self._strip_emoji(line) for line in lines]
            logger.warning("Stripped emoji from text (imagetext-py not available)")

        # Calculate text dimensions
        line_heights = []
        line_widths = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_widths.append(bbox[2] - bbox[0])
            line_heights.append(bbox[3] - bbox[1])

        line_height = max(line_heights) if line_heights else cfg.font_size
        total_height = len(lines) * (line_height + cfg.line_spacing)
        max_width = max(line_widths) if line_widths else 0

        # Ensure text fits within screen safe zones
        max_text_w = target_w - 2 * SAFE_SIDE
        if max_width > max_text_w:
            original_text = ' '.join(lines)
            current_max_chars = cfg.max_width_chars
            while max_width > max_text_w and current_max_chars > 15:
                current_max_chars -= 3
                lines = textwrap.wrap(original_text, width=current_max_chars)
                line_widths = []
                line_heights = []
                for line in lines:
                    bbox = draw.textbbox((0, 0), line, font=font)
                    line_widths.append(bbox[2] - bbox[0])
                    line_heights.append(bbox[3] - bbox[1])
                line_height = max(line_heights) if line_heights else cfg.font_size
                total_height = len(lines) * (line_height + cfg.line_spacing)
                max_width = max(line_widths) if line_widths else 0
            logger.info(
                f"PIL re-wrapped text: {cfg.max_width_chars}->{current_max_chars} chars, "
                f"width={max_width}px (max={max_text_w}px)"
            )

        # Position: bottom of safe zone
        safe_zone_bottom = target_h - 340
        bottom_margin = 40
        start_y = safe_zone_bottom - total_height - bottom_margin

        # Draw background
        padding = cfg.padding
        bg_left = (target_w - max_width) // 2 - padding
        bg_top = start_y - padding
        bg_right = (target_w + max_width) // 2 + padding
        bg_bottom = start_y + total_height + padding

        # Clamp background to screen bounds (safety net)
        bg_left = max(bg_left, 0)
        bg_right = min(bg_right, target_w)

        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        bg_opacity = int(cfg.background_opacity * 255)
        overlay_draw.rounded_rectangle(
            [bg_left, bg_top, bg_right, bg_bottom],
            radius=10,
            fill=(0, 0, 0, bg_opacity),
        )
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        # Draw text
        y = start_y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (target_w - text_width) // 2

            if cfg.shadow_offset > 0:
                draw.text(
                    (x + cfg.shadow_offset, y + cfg.shadow_offset),
                    line, font=font, fill=cfg.shadow_color
                )
            draw.text((x, y), line, font=font, fill=cfg.font_color)
            y += line_height + cfg.line_spacing

        return img

    def _get_media_duration(self, media_path: Path) -> Optional[float]:
        """
        Get duration of audio/video file using ffprobe.

        Returns:
            Duration in seconds, or None if unable to determine
        """
        # ffprobe should be in the same directory as ffmpeg
        ffprobe_path = str(Path(self.ffmpeg_path).parent / "ffprobe")
        if not Path(ffprobe_path).exists():
            ffprobe_path = "ffprobe"  # Fall back to system ffprobe

        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(media_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as e:
            logger.warning(f"Could not get duration for {media_path}: {e}")

        return None

    def _generate_output_filename(self, prefix: str = "story") -> Path:
        """Generate unique output filename with timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.mp4"
        return self.output_dir / filename

    def _apply_exif_orientation(self, photo_path: Path) -> tuple[Path, bool]:
        """
        Apply EXIF orientation to photo if needed.

        FFmpeg doesn't reliably handle EXIF rotation, so we pre-process
        the image with PIL and save to a temp file if rotation is needed.

        Args:
            photo_path: Path to original photo

        Returns:
            Tuple of (path_to_use, needs_cleanup) - if needs_cleanup is True,
            the returned path is a temp file that should be deleted after use.
        """
        try:
            with Image.open(photo_path) as img:
                # Check if EXIF orientation exists and requires rotation
                exif = img.getexif()
                orientation = exif.get(274)  # 274 is the EXIF orientation tag

                if orientation and orientation != 1:
                    # Orientation requires transformation
                    img_fixed = ImageOps.exif_transpose(img)
                    temp_path = self.output_dir / f"_temp_exif_{datetime.now().strftime('%Y%m%d_%H%M%S%f')}.jpg"

                    # Convert to RGB if necessary
                    if img_fixed.mode in ('RGBA', 'P'):
                        img_fixed = img_fixed.convert('RGB')

                    img_fixed.save(temp_path, format='JPEG', quality=95)
                    logger.debug(f"Applied EXIF rotation (orientation={orientation}) to temp file")
                    return temp_path, True

        except Exception as e:
            logger.warning(f"Failed to check/apply EXIF orientation: {e}")

        return photo_path, False

    @staticmethod
    def _pick_random_effect(static_probability: float = STATIC_PROBABILITY) -> MotionEffect:
        """Pick a random motion effect, with a chance of static."""
        if random.random() < static_probability:
            return _EFFECTS_BY_NAME["static"]
        return random.choice(_NON_STATIC_EFFECTS)

    def _build_motion_command(
        self,
        effect: MotionEffect,
        photo_path: Path,
        music_path: Path,
        output_path: Path,
        duration: float,
        music_offset: float = 0,
    ) -> list[str]:
        """Build FFmpeg command for a given motion effect."""
        if effect.is_static:
            return self._build_static_command(
                photo_path, music_path, output_path, duration, music_offset,
            )

        w = self.config.width
        h = self.config.height
        fps = self.config.fps
        total_frames = int(duration * fps)
        zoom_speed = 0.2 / total_frames

        z = effect.z_expr.format(zoom_speed=zoom_speed, total_frames=total_frames)
        x = effect.x_expr.format(total_frames=total_frames)
        y = effect.y_expr.format(total_frames=total_frames)

        vf = (
            f"scale=8000:-1,"
            f"zoompan="
            f"z='{z}':"
            f"x='{x}':"
            f"y='{y}':"
            f"d={total_frames}:"
            f"s={w}x{h}:"
            f"fps={fps},"
            f"setsar=1"
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-loop", "1",
            "-i", str(photo_path),
        ]

        if music_offset > 0:
            cmd.extend(["-ss", f"{music_offset:.3f}"])
        cmd.extend(["-i", str(music_path)])

        cmd.extend([
            "-vf", vf,
            "-c:v", self.config.codec,
            "-preset", self.config.preset,
            "-crf", str(self.config.crf),
            "-c:a", "aac",
            "-b:a", self.config.audio_bitrate,
            "-t", f"{duration:.3f}",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            str(output_path),
        ])

        return cmd

    def compose_story(
        self,
        photo_path: Path,
        music_path: Path,
        output_path: Optional[Path] = None,
        duration: Optional[float] = None,
        ken_burns: bool = False,
        music_offset: float = 0,
        motion_effect: Optional[str] = None,
    ) -> Path:
        """
        Create a story video from photo and music.

        Args:
            photo_path: Path to input photo
            music_path: Path to input music file
            output_path: Custom output path (auto-generated if None)
            duration: Video duration in seconds (uses config default or music length)
            ken_burns: Legacy parameter (use motion_effect instead)
            music_offset: Start position in music file (seconds)
            motion_effect: Effect name, "random", or None.
                "random" — pick random effect (including static with STATIC_PROBABILITY).
                None — use ken_burns param for backward compatibility.
                Specific name — use that effect.

        Returns:
            Path to created video file

        Raises:
            FileNotFoundError: If input files don't exist
            RuntimeError: If FFmpeg fails
        """
        photo_path = Path(photo_path)
        music_path = Path(music_path)

        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")
        if not music_path.exists():
            raise FileNotFoundError(f"Music not found: {music_path}")

        if output_path is None:
            output_path = self._generate_output_filename()
        else:
            output_path = Path(output_path)

        # Apply EXIF orientation (FFmpeg doesn't handle it reliably)
        actual_photo_path, cleanup_temp = self._apply_exif_orientation(photo_path)

        try:
            # Determine duration
            if duration is None:
                music_duration = self._get_media_duration(music_path)
                if music_duration and music_duration <= 60:
                    duration = music_duration
                else:
                    duration = float(self.config.duration)

            # Resolve motion effect
            if motion_effect is not None:
                # New API
                if motion_effect == "random":
                    effect = self._pick_random_effect()
                elif motion_effect == "static":
                    effect = _EFFECTS_BY_NAME["static"]
                else:
                    effect = _EFFECTS_BY_NAME.get(motion_effect)
                    if not effect:
                        logger.warning(f"Unknown motion effect '{motion_effect}', using random")
                        effect = self._pick_random_effect()
            else:
                # Legacy ken_burns compat
                if ken_burns:
                    effect = _EFFECTS_BY_NAME["zoom_in_center"]
                else:
                    effect = _EFFECTS_BY_NAME["static"]

            logger.info(
                f"Composing video: {photo_path.name} + {music_path.name} "
                f"({duration:.2f}s, offset={music_offset:.2f}s, effect={effect.name})"
            )

            # Build FFmpeg command
            cmd = self._build_motion_command(
                effect, actual_photo_path, music_path, output_path, duration, music_offset
            )

            # Execute FFmpeg
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 minutes max
                )

                if result.returncode != 0:
                    logger.error(f"FFmpeg error: {result.stderr}")
                    raise RuntimeError(f"FFmpeg failed: {result.stderr[:500]}")

            except subprocess.TimeoutExpired:
                raise RuntimeError("FFmpeg timed out after 5 minutes")

            if not output_path.exists():
                raise RuntimeError(f"Output file was not created: {output_path}")

            file_size = output_path.stat().st_size / (1024 * 1024)  # MB
            logger.info(f"Video created: {output_path.name} ({file_size:.1f} MB)")

            return output_path

        finally:
            # Clean up temp EXIF-corrected file if created
            if cleanup_temp and actual_photo_path.exists():
                actual_photo_path.unlink()
                logger.debug(f"Cleaned up temp EXIF file: {actual_photo_path}")

    def compose_story_with_overlay(
        self,
        photo_path: Path,
        music_path: Path,
        text: str,
        output_path: Optional[Path] = None,
        duration: Optional[float] = None,
        ken_burns: bool = True,
        text_config: Optional[TextOverlayConfig] = None,
        music_offset: float = 0,
        motion_effect: Optional[str] = None,
    ) -> Path:
        """
        Create a story video with text overlay.

        Args:
            photo_path: Path to input photo
            music_path: Path to input music file
            text: Text to overlay on the video
            output_path: Custom output path (auto-generated if None)
            duration: Video duration in seconds
            ken_burns: Legacy parameter (use motion_effect instead)
            text_config: Text overlay settings (uses defaults if None)
            music_offset: Start position in music file (seconds)
            motion_effect: Effect name, "random", or None (see compose_story)

        Returns:
            Path to created video file
        """
        photo_path = Path(photo_path)
        music_path = Path(music_path)

        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")
        if not music_path.exists():
            raise FileNotFoundError(f"Music not found: {music_path}")

        # Use provided config or default
        txt_cfg = text_config or self.config.text_overlay

        # Check if font is available
        font_path = txt_cfg.font_path or self._default_font
        if not font_path or not font_path.exists():
            logger.warning("No font found, falling back to compose_story without overlay")
            return self.compose_story(
                photo_path=photo_path,
                music_path=music_path,
                output_path=output_path,
                duration=duration,
                ken_burns=ken_burns,
                music_offset=music_offset,
                motion_effect=motion_effect,
            )

        # Update config with actual font path
        txt_cfg.font_path = font_path

        logger.info(f"Composing video with overlay: {photo_path.name}")
        logger.debug(f"Overlay text: {text[:50]}...")

        # Step 1: Create image with text overlay using PIL
        # Use temp file for intermediate image
        temp_image = self.output_dir / f"_temp_overlay_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

        try:
            self._add_text_overlay_pillow(
                image_path=photo_path,
                text=text,
                output_path=temp_image,
                text_config=txt_cfg,
            )
            logger.debug(f"Created temp image with overlay: {temp_image}")

            # Step 2: Create video from the processed image
            video_path = self.compose_story(
                photo_path=temp_image,
                music_path=music_path,
                output_path=output_path,
                duration=duration,
                ken_burns=ken_burns,
                music_offset=music_offset,
                motion_effect=motion_effect,
            )

            return video_path

        finally:
            # Clean up temp image
            if temp_image.exists():
                temp_image.unlink()
                logger.debug(f"Cleaned up temp image: {temp_image}")

    def _build_static_command(
        self,
        photo_path: Path,
        music_path: Path,
        output_path: Path,
        duration: float,
        music_offset: float = 0,
    ) -> list[str]:
        """
        Build FFmpeg command for static photo video.

        Scales and pads photo to 9:16 aspect ratio.
        """
        w = self.config.width
        h = self.config.height

        # Video filter: scale to fit, pad to exact dimensions, center
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1"
        )

        cmd = [
            self.ffmpeg_path,
            "-y",  # Overwrite output
            "-loop", "1",  # Loop image
            "-i", str(photo_path),
        ]

        # Add music with optional offset
        if music_offset > 0:
            cmd.extend(["-ss", f"{music_offset:.3f}"])
        cmd.extend(["-i", str(music_path)])

        cmd.extend([
            "-vf", vf,
            "-c:v", self.config.codec,
            "-preset", self.config.preset,
            "-crf", str(self.config.crf),
            "-c:a", "aac",
            "-b:a", self.config.audio_bitrate,
            "-t", f"{duration:.3f}",  # Precision to milliseconds
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",  # Web optimization
            "-shortest",  # End when shortest input ends
            str(output_path),
        ])

        return cmd

    def _build_ken_burns_command(
        self,
        photo_path: Path,
        music_path: Path,
        output_path: Path,
        duration: float,
        music_offset: float = 0,
    ) -> list[str]:
        """
        Build FFmpeg command with Ken Burns effect (slow zoom in).

        Creates a gentle zoom from 1.0x to 1.2x over the duration.
        """
        w = self.config.width
        h = self.config.height
        fps = self.config.fps
        total_frames = int(duration * fps)

        # Zoom from 1.0 to 1.2 over duration
        # zoompan: z = zoom level, d = duration in frames
        # Expression: zoom starts at 1.0, increases by 0.2/total_frames per frame
        zoom_speed = 0.2 / total_frames

        vf = (
            f"scale=8000:-1,"  # Scale up for quality during zoom
            f"zoompan="
            f"z='min(zoom+{zoom_speed:.6f},1.2)':"  # Zoom factor
            f"x='iw/2-(iw/zoom/2)':"  # Center X
            f"y='ih/2-(ih/zoom/2)':"  # Center Y
            f"d={total_frames}:"  # Duration in frames
            f"s={w}x{h}:"  # Output size
            f"fps={fps},"
            f"setsar=1"
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-loop", "1",
            "-i", str(photo_path),
        ]

        # Add music with optional offset
        if music_offset > 0:
            cmd.extend(["-ss", f"{music_offset:.3f}"])
        cmd.extend(["-i", str(music_path)])

        cmd.extend([
            "-vf", vf,
            "-c:v", self.config.codec,
            "-preset", self.config.preset,
            "-crf", str(self.config.crf),
            "-c:a", "aac",
            "-b:a", self.config.audio_bitrate,
            "-t", f"{duration:.3f}",  # Precision to milliseconds
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            str(output_path),
        ])

        return cmd

    def compose_post_image(
        self,
        photo_path: Path,
        output_path: Optional[Path] = None,
        aspect_ratio: str = "4:5",
    ) -> Path:
        """
        Prepare image for Instagram feed post.

        Args:
            photo_path: Path to input photo
            output_path: Custom output path
            aspect_ratio: Target aspect ratio ("4:5", "1:1", "1.91:1")

        Returns:
            Path to processed image
        """
        photo_path = Path(photo_path)

        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")

        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.output_dir / f"post_{timestamp}.jpg"

        # Calculate dimensions based on aspect ratio
        if aspect_ratio == "4:5":
            w, h = 1080, 1350
        elif aspect_ratio == "1:1":
            w, h = 1080, 1080
        else:  # 1.91:1 landscape
            w, h = 1080, 566

        # FFmpeg command to crop and scale
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}"
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", str(photo_path),
            "-vf", vf,
            "-q:v", "2",  # High quality JPEG
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr[:500]}")

        logger.info(f"Post image created: {output_path.name}")
        return output_path

    def _random_story_duration(
        self,
        min_seconds: float = 5.0,
        max_seconds: float = 8.0,
    ) -> float:
        """
        Generate random story duration with hundredths precision.

        This avoids detection patterns from fixed-length videos.

        Args:
            min_seconds: Minimum duration
            max_seconds: Maximum duration

        Returns:
            Random duration like 5.48, 7.22, etc.
        """
        return round(random.uniform(min_seconds, max_seconds), 2)

    def compose_story_series(
        self,
        stories: list[dict],
        music_path: Path,
        ken_burns: bool = True,
        story_duration: Optional[float] = None,
        min_duration: float = 5.0,
        max_duration: float = 8.0,
        text_config: Optional[TextOverlayConfig] = None,
        motion_effects: bool = True,
    ) -> list[Path]:
        """
        Create a series of story videos with continuous music.

        Each video uses a sequential segment of the same music track,
        creating a continuous listening experience when played in order.

        Args:
            stories: List of dicts with 'photo_path' and 'text' keys
            music_path: Path to music file (will be split into segments)
            ken_burns: Legacy parameter (ignored when motion_effects is set)
            story_duration: Fixed duration for all stories (None = random per story)
            min_duration: Minimum random duration (default: 5.0 seconds)
            max_duration: Maximum random duration (default: 8.0 seconds)
            text_config: Optional text overlay config (with font from rotation)
            motion_effects: If True, pick random effect per story. If False, all static.

        Returns:
            List of paths to created video files
        """
        music_path = Path(music_path)
        if not music_path.exists():
            raise FileNotFoundError(f"Music not found: {music_path}")

        # Get total music duration
        music_duration = self._get_media_duration(music_path)

        # Pre-generate durations for each story
        durations = []
        for _ in stories:
            if story_duration is not None:
                durations.append(float(story_duration))
            else:
                durations.append(self._random_story_duration(min_duration, max_duration))

        total_needed = sum(durations)

        if not music_duration:
            music_duration = total_needed + 30  # Estimate if can't detect

        if music_duration < total_needed:
            logger.warning(
                f"Music ({music_duration:.1f}s) shorter than needed ({total_needed:.1f}s). "
                f"Last stories may have overlapping/repeated music."
            )

        video_paths = []
        music_offset = 0.0

        # Get fonts from config — select ONE font for entire series
        series_font_path = None
        series_font_cfg = None
        if FONT_ROTATION_AVAILABLE:
            for font_config in FONT_ROTATION:
                font_path = self.fonts_dir / font_config.filename
                if font_path.exists():
                    if series_font_path is None:
                        # Use font from text_config if provided, otherwise first available
                        if text_config and text_config.font_path:
                            series_font_path = text_config.font_path
                            # Find matching config
                            for fc in FONT_ROTATION:
                                if fc.filename == text_config.font_path.name:
                                    series_font_cfg = fc
                                    break
                            if not series_font_cfg:
                                series_font_cfg = font_config
                        else:
                            series_font_path = font_path
                            series_font_cfg = font_config

        for i, story in enumerate(stories):
            photo_path = Path(story["photo_path"])
            text = story.get("text", "")
            duration = durations[i]

            # If music would run out, loop back
            if music_offset + duration > music_duration:
                music_offset = music_offset % music_duration

            # Pick motion effect for this story
            if motion_effects:
                effect = self._pick_random_effect()
            else:
                effect = _EFFECTS_BY_NAME["static"]

            # Create per-story text config with SAME font but random position
            story_text_config = text_config
            if text and series_font_path:
                # Random position for this story (variety within series)
                position = random.choice(TEXT_POSITIONS)

                story_text_config = TextOverlayConfig(
                    font_path=series_font_path,
                    position=position,
                    use_background=not series_font_cfg.is_bold,  # Bold fonts don't need bg
                    size_multiplier=series_font_cfg.size_multiplier,
                )
                logger.info(
                    f"Composing story {i + 1}/{len(stories)}: "
                    f"font={series_font_cfg.name}, pos={position}, bg={not series_font_cfg.is_bold}, "
                    f"effect={effect.name}"
                )
            else:
                logger.info(
                    f"Composing story {i + 1}/{len(stories)}: "
                    f"duration={duration:.2f}s, music_offset={music_offset:.2f}s, "
                    f"effect={effect.name}"
                )

            if text:
                video_path = self.compose_story_with_overlay(
                    photo_path=photo_path,
                    music_path=music_path,
                    text=text,
                    duration=duration,
                    text_config=story_text_config,
                    music_offset=music_offset,
                    motion_effect=effect.name,
                )
            else:
                video_path = self.compose_story(
                    photo_path=photo_path,
                    music_path=music_path,
                    duration=duration,
                    music_offset=music_offset,
                    motion_effect=effect.name,
                )

            video_paths.append(video_path)
            music_offset += duration  # Advance to next segment

        logger.info(f"Story series complete: {len(video_paths)} videos, total {total_needed:.2f}s")
        return video_paths

    def cleanup_old_files(self, keep_days: int = 7) -> int:
        """
        Remove output files older than specified days.

        Returns:
            Number of files deleted
        """
        import time

        deleted = 0
        cutoff = time.time() - (keep_days * 24 * 60 * 60)

        for file in self.output_dir.iterdir():
            if file.is_file() and file.stat().st_mtime < cutoff:
                file.unlink()
                deleted += 1
                logger.debug(f"Deleted old file: {file.name}")

        if deleted:
            logger.info(f"Cleaned up {deleted} old files from output directory")

        return deleted
