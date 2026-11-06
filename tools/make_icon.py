#!/usr/bin/env python3
"""Turn the plugin artwork into Android launcher icons.

    python3 tools/make_icon.py --art android-plugin/art/icon-rust-gear.png

Writes an adaptive launcher icon (mipmap-anydpi-v26/ic_launcher.xml plus one
foreground PNG per density) and the matching background colour into
android-plugin/res/, and a flat copy into docs/icon.png for the README.

Android 8.0 (the plugin's minSdk) always masks adaptive icons, so the icon is
built as: opaque artwork at full bleed for the foreground layer, and a solid
background colour sampled from the artwork's corners - when the launcher clips
the corners, what shows through is the same colour the artwork already uses.
Artwork with real transparency is centred inside the 66 % safe zone instead.
"""

import argparse
from pathlib import Path
import sys

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the CI job installs Pillow
    sys.exit("Pillow is required: pip install Pillow")

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "android-plugin" / "res"

# Android adaptive icon: 108 dp canvas with a 72 dp foreground layer.
DENSITIES = {
    "mdpi": 108,
    "hdpi": 162,
    "xhdpi": 216,
    "xxhdpi": 324,
    "xxxhdpi": 432,
}

ADAPTIVE_ICON = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
"""

COLORS = """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">%s</color>
</resources>
"""


def corner_colour(image: Image.Image) -> str:
    """The artwork's own background colour, so masked edges blend in."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    inset = max(4, min(width, height) // 50)
    samples = [
        rgb.getpixel((inset, inset)),
        rgb.getpixel((width - inset, inset)),
        rgb.getpixel((inset, height - inset)),
        rgb.getpixel((width - inset, height - inset)),
    ]
    channels = [sum(sample[i] for sample in samples) // len(samples) for i in range(3)]
    return "#%02X%02X%02X" % tuple(channels)


def has_transparency(image: Image.Image) -> bool:
    if image.mode not in ("RGBA", "LA", "PA"):
        return False
    alpha = image.getchannel("A")
    return alpha.getextrema()[0] < 250


def foreground(art: Image.Image, size: int) -> Image.Image:
    if has_transparency(art):
        # Keep the transparent margin: only the middle 72/108 survives masking.
        inner = round(size * 72 / 108)
        scaled = art.resize((inner, inner), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(scaled, ((size - inner) // 2, (size - inner) // 2), scaled)
        return canvas
    return art.resize((size, size), Image.LANCZOS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--art", type=Path, default=ROOT / "android-plugin" / "art" / "icon-rust-gear.png")
    parser.add_argument("--res", type=Path, default=RES)
    parser.add_argument("--preview", type=Path, default=ROOT / "docs" / "icon.png")
    args = parser.parse_args()

    art = Image.open(args.art)
    if art.size[0] < 432:
        sys.exit(f"{args.art} is only {art.size[0]} px wide; artwork should be at least 432 px")
    background = corner_colour(art)

    for density, size in DENSITIES.items():
        target = args.res / f"mipmap-{density}"
        target.mkdir(parents=True, exist_ok=True)
        foreground(art, size).save(target / "ic_launcher_foreground.png", optimize=True)

    anydpi = args.res / "mipmap-anydpi-v26"
    anydpi.mkdir(parents=True, exist_ok=True)
    (anydpi / "ic_launcher.xml").write_text(ADAPTIVE_ICON, encoding="utf-8")

    values = args.res / "values"
    values.mkdir(parents=True, exist_ok=True)
    (values / "colors.xml").write_text(COLORS % background, encoding="utf-8")

    args.preview.parent.mkdir(parents=True, exist_ok=True)
    art.resize((512, 512), Image.LANCZOS).save(args.preview, optimize=True)

    print(f"background colour: {background}")
    for density, size in DENSITIES.items():
        print(f"mipmap-{density}/ic_launcher_foreground.png ({size} px)")
    print(f"preview: {args.preview}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
