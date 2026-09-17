"""Generate the app icon. Run once; the .ico is then reused by every build."""

from pathlib import Path

from PIL import Image, ImageDraw

BG = (27, 29, 35)
ACCENT = (79, 156, 249)
LIGHT = (230, 232, 238)


def render(size):
    scale = 8
    px = size * scale
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = int(px * 0.22)
    draw.rounded_rectangle([0, 0, px - 1, px - 1], radius=radius, fill=BG)

    # A waveform: bars rising and falling across the middle of the tile.
    heights = [0.18, 0.34, 0.55, 0.82, 0.62, 0.95, 0.48, 0.70, 0.30, 0.16]
    bar_w = px * 0.062
    gap = (px - bar_w * len(heights)) / (len(heights) + 1)
    centre = px / 2
    for index, height in enumerate(heights):
        x = gap + index * (bar_w + gap)
        half = px * 0.36 * height
        colour = ACCENT if index % 2 == 0 else LIGHT
        draw.rounded_rectangle(
            [x, centre - half, x + bar_w, centre + half],
            radius=bar_w / 2, fill=colour,
        )

    return img.resize((size, size), Image.LANCZOS)


def main():
    out = Path(__file__).parent / "revolv.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [render(s) for s in sizes]
    images[-1].save(out, format="ICO",
                    sizes=[(s, s) for s in sizes], append_images=images[:-1])
    print("wrote", out, out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
