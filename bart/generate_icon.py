"""
Generate assets/bart.ico — dark rounded square with teal waveform bars.
Run once: python -m bart.generate_icon
"""
import struct
import zlib
from pathlib import Path

ASSETS_DIR = Path(__file__).parent.parent / "assets"


def _make_ico_image(size: int) -> bytes:
    """Return raw RGBA bytes for a square icon of the given size."""
    half = size // 2
    bar_count = 9
    bg = (13, 13, 13, 255)
    bar_color = (78, 205, 196, 255)
    # Heights for bars (relative 0-1), symmetric
    heights = [0.40, 0.60, 0.75, 0.88, 1.00, 0.88, 0.75, 0.60, 0.40]

    # Pixels as flat RGBA list
    pixels = [bg] * (size * size)

    margin_x = max(2, size // 8)
    margin_y = max(2, size // 8)
    usable_w = size - 2 * margin_x
    usable_h = size - 2 * margin_y

    bar_gap = max(1, usable_w // (bar_count * 2))
    bar_w = max(1, (usable_w - (bar_count - 1) * bar_gap) // bar_count)
    x_start = margin_x

    for i, rel_h in enumerate(heights):
        bar_h = max(2, int(usable_h * rel_h))
        bx = x_start + i * (bar_w + bar_gap)
        by = margin_y + (usable_h - bar_h)
        for row in range(bar_h):
            for col in range(bar_w):
                px = bx + col
                py = by + row
                if 0 <= px < size and 0 <= py < size:
                    pixels[py * size + px] = bar_color

    # Round corners: clear pixels outside rounded rect
    radius = max(4, size // 8)
    for y in range(size):
        for x in range(size):
            in_rect = (
                x >= radius and x < size - radius or
                y >= radius and y < size - radius
            )
            if not in_rect:
                # Check if in corner circle
                cx_dist = min(abs(x - radius), abs(x - (size - 1 - radius)))
                cy_dist = min(abs(y - radius), abs(y - (size - 1 - radius)))
                if (cx_dist ** 2 + cy_dist ** 2) > radius ** 2:
                    pixels[y * size + x] = (0, 0, 0, 0)

    # Pack as raw RGBA bytes
    raw = bytearray()
    for r, g, b, a in pixels:
        raw += bytes([r, g, b, a])
    return bytes(raw)


def _rgba_to_png(rgba_bytes: bytes, width: int, height: int) -> bytes:
    """Minimal PNG encoder for RGBA images."""
    def write_chunk(chunk_type: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        return length + chunk_type + data + crc

    # Build scanlines with filter byte 0 (None) prepended
    raw_rows = bytearray()
    stride = width * 4
    for row in range(height):
        raw_rows.append(0)  # filter type None
        raw_rows += rgba_bytes[row * stride:(row + 1) * stride]

    compressed = zlib.compress(bytes(raw_rows), 9)

    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + write_chunk(b"IHDR", ihdr_data)
        + write_chunk(b"IDAT", compressed)
        + write_chunk(b"IEND", b"")
    )
    return png


def _build_ico(sizes=(16, 32, 48, 64, 128, 256)) -> bytes:
    """Build a multi-resolution ICO file from PNG images."""
    images = []
    for size in sizes:
        rgba = _make_ico_image(size)
        png_data = _rgba_to_png(rgba, size, size)
        images.append((size, png_data))

    # ICO header: ICONDIR
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)  # reserved, type=1 (ICO), count

    # Directory entries (ICONDIRENTRY), each 16 bytes
    offset = 6 + count * 16
    entries = b""
    for size, png_data in images:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII",
            w, h,       # width, height (0 = 256)
            0,          # color count (0 = no palette)
            0,          # reserved
            1,          # color planes
            32,         # bits per pixel
            len(png_data),
            offset,
        )
        offset += len(png_data)

    data = header + entries
    for _, png_data in images:
        data += png_data
    return data


def generate():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    ico_path = ASSETS_DIR / "bart.ico"
    ico_data = _build_ico()
    ico_path.write_bytes(ico_data)
    print(f"[icon] wrote {ico_path} ({len(ico_data)} bytes)")
    return ico_path


if __name__ == "__main__":
    generate()
