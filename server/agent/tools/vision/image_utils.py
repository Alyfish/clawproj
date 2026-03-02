"""
Image validation and preprocessing utilities.

Handles: base64 decoding, format detection, size validation,
resize to max dimension, RGBA→RGB conversion, JPEG compression.

Reference: anthropic-cookbook/multimodal/best_practices_for_vision.ipynb
"""
from __future__ import annotations

import base64
import io
import logging
from PIL import Image

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024       # 5MB raw input limit
MAX_IMAGE_DIMENSION = 2048                     # px on longest side
RECOMPRESS_THRESHOLD = 1 * 1024 * 1024        # recompress if > 1MB
JPEG_QUALITY = 85

SUPPORTED_FORMATS = {
    "JPEG": "image/jpeg",
    "JPG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


class ImageValidationError(ValueError):
    """Raised when image validation fails."""
    pass


class ProcessedImage:
    """Result of image preprocessing."""
    def __init__(self, base64_data: str, media_type: str, width: int, height: int,
                 original_size_bytes: int, processed_size_bytes: int, was_resized: bool):
        self.base64_data = base64_data
        self.media_type = media_type
        self.width = width
        self.height = height
        self.original_size_bytes = original_size_bytes
        self.processed_size_bytes = processed_size_bytes
        self.was_resized = was_resized

    def to_api_block(self) -> dict:
        """Return the image block for Claude's messages API."""
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": self.media_type,
                "data": self.base64_data
            }
        }


def validate_and_preprocess(image_base64: str) -> ProcessedImage:
    """
    Validate a base64-encoded image and preprocess for Claude's vision API.

    Steps:
    1. Strip data URI prefix if present
    2. Decode base64
    3. Validate size (≤5MB)
    4. Validate format (JPEG, PNG, WebP)
    5. Resize if longest side > 2048px
    6. Recompress if > 1MB (JPEG @ 85% quality)

    Returns ProcessedImage with base64 data ready for the API.
    Raises ImageValidationError on failure.
    """
    if not image_base64:
        raise ImageValidationError("No image data provided")

    # Strip data URI prefix: "data:image/png;base64,..." → "..."
    if image_base64.startswith("data:") and "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]

    # Remove any whitespace (some encoders add newlines)
    image_base64 = image_base64.strip()

    # Decode base64
    try:
        raw_bytes = base64.b64decode(image_base64)
    except Exception:
        raise ImageValidationError("Invalid base64 encoding — cannot decode")

    original_size = len(raw_bytes)

    # Check size
    if original_size > MAX_IMAGE_SIZE_BYTES:
        raise ImageValidationError(
            f"Image too large: {original_size / 1024 / 1024:.1f}MB "
            f"(max {MAX_IMAGE_SIZE_BYTES / 1024 / 1024:.0f}MB)"
        )

    # Open with Pillow — validate format
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.verify()  # checks for corruption
        img = Image.open(io.BytesIO(raw_bytes))  # re-open (verify closes it)
    except Exception as e:
        raise ImageValidationError(f"Cannot open image: {e}")

    format_name = (img.format or "").upper()
    if format_name not in SUPPORTED_FORMATS:
        raise ImageValidationError(
            f"Unsupported format: {format_name or 'unknown'}. "
            f"Supported: JPEG, PNG, WebP"
        )

    media_type = SUPPORTED_FORMATS[format_name]
    width, height = img.size
    longest = max(width, height)

    needs_resize = longest > MAX_IMAGE_DIMENSION
    needs_recompress = original_size > RECOMPRESS_THRESHOLD

    if needs_resize or needs_recompress:
        # Resize
        if needs_resize:
            scale = MAX_IMAGE_DIMENSION / longest
            new_width = int(width * scale)
            new_height = int(height * scale)
            img = img.resize((new_width, new_height), Image.LANCZOS)
            width, height = new_width, new_height
            logger.info(f"Vision: resized {longest}px → {max(width, height)}px")

        # Convert RGBA/palette → RGB for JPEG
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if "A" in img.mode:
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background

        # Encode as JPEG
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        processed_bytes = buffer.getvalue()
        out_b64 = base64.b64encode(processed_bytes).decode("utf-8")
        media_type = "image/jpeg"
        processed_size = len(processed_bytes)
        logger.info(f"Vision: compressed {original_size // 1024}KB → {processed_size // 1024}KB")
    else:
        out_b64 = base64.b64encode(raw_bytes).decode("utf-8")
        processed_size = original_size

    return ProcessedImage(
        base64_data=out_b64,
        media_type=media_type,
        width=width,
        height=height,
        original_size_bytes=original_size,
        processed_size_bytes=processed_size,
        was_resized=needs_resize
    )


def create_test_image(text_lines: list[str] | None = None) -> str:
    """
    Create a small test PNG with text. Returns base64-encoded PNG.
    Default: flight booking test image.
    """
    from PIL import ImageDraw, ImageFont

    if text_lines is None:
        text_lines = [
            "British Airways BA 287",
            "SFO -> LHR",
            "Departure: 2025-04-15 10:30",
            "Arrival: 2025-04-16 05:45",
            "Price: $499 | Economy",
            "Confirmation: XKCD42",
        ]

    line_height = 30
    padding = 20
    img_width = 500
    img_height = padding * 2 + line_height * len(text_lines)

    img = Image.new("RGB", (img_width, img_height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    font = None
    for font_path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "/System/Library/Fonts/Helvetica.ttc",                # macOS
        "/System/Library/Fonts/SFNSText.ttf",                 # macOS alt
    ]:
        try:
            font = ImageFont.truetype(font_path, 18)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    colors = [(0, 0, 0), (0, 0, 128), (80, 80, 80), (80, 80, 80), (0, 100, 0), (128, 0, 0)]
    for i, line in enumerate(text_lines):
        color = colors[i % len(colors)]
        draw.text((padding, padding + i * line_height), line, fill=color, font=font)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
