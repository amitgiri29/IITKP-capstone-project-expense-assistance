"""Generate the fictitious SPARKS AI Lab logo assets (SVG + PNG) under assets/brand/.

Style follows the approved mock-ups: a rose spark on a white tile with a rose-violet-indigo
gradient ring, the SPARKS wordmark and a rose "AI LAB" chip.

    .venv/bin/python scripts/make_brand.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'assets' / 'brand'
ROSE, VIOLET, INDIGO, INK = '#F43F5E', '#8B5CF6', '#4F46E5', '#0F172A'
SPARK_TEXT, CHIP_BG, CHIP_BORDER, CHIP_TEXT = '#E11D48', '#FFF1F2', '#FECDD3', '#BE123C'
# Four-point spark from the mock-up, on a 24x24 grid.
SPARK = [(12, 2), (14.39, 9.61), (22, 12), (14.39, 14.39), (12, 22), (9.61, 14.39), (2, 12), (9.61, 9.61)]


def mark_svg(size=256):
    ring, radius = size * 0.07, size * 0.28
    inner = size - 2 * ring
    scale = inner * 0.62 / 24
    offset = ring + (inner - 24 * scale) / 2
    points = ' '.join('%.2f,%.2f' % (offset + x * scale, offset + y * scale) for x, y in SPARK)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" aria-label="SPARKS AI Lab">
  <defs><linearGradient id="ring" x1="0" y1="1" x2="1" y2="0">
    <stop offset="0" stop-color="{ROSE}"/><stop offset="0.5" stop-color="{VIOLET}"/><stop offset="1" stop-color="{INDIGO}"/>
  </linearGradient></defs>
  <rect width="{size}" height="{size}" rx="{radius:.1f}" fill="url(#ring)"/>
  <rect x="{ring:.1f}" y="{ring:.1f}" width="{inner:.1f}" height="{inner:.1f}" rx="{radius - ring * 0.6:.1f}" fill="#FFFFFF"/>
  <polygon points="{points}" fill="{SPARK_TEXT}"/>
</svg>
'''


def logo_svg():
    mark = mark_svg(96).split('>', 1)[1].rsplit('</svg>', 1)[0]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="520" height="120" viewBox="0 0 520 120" role="img" aria-label="SPARKS AI Lab">
  <g transform="translate(12,12)">{mark}</g>
  <text x="128" y="76" font-family="Inter, Helvetica, Arial, sans-serif" font-size="46" font-weight="800" fill="{INK}" letter-spacing="3">SPARKS</text>
  <rect x="342" y="40" width="132" height="46" rx="8" fill="{CHIP_BG}" stroke="{CHIP_BORDER}" stroke-width="2"/>
  <text x="408" y="72" text-anchor="middle" font-family="Inter, Helvetica, Arial, sans-serif" font-size="24" font-weight="700" fill="{CHIP_TEXT}" letter-spacing="1">AI LAB</text>
</svg>
'''


def _gradient(size):
    image = Image.new('RGBA', (size, size))
    draw = ImageDraw.Draw(image)
    stops = [Image.new('RGB', (1, 1), c).getpixel((0, 0)) for c in (ROSE, VIOLET, INDIGO)]
    for i in range(size * 2):
        t = i / (size * 2)
        a, b, u = (stops[0], stops[1], t / 0.5) if t < 0.5 else (stops[1], stops[2], (t - 0.5) / 0.5)
        colour = tuple(int(a[k] + (b[k] - a[k]) * u) for k in range(3)) + (255,)
        draw.line([(i - size, size), (i, 0)], fill=colour, width=2)
    return image


def mark_png(size=512):
    scale = 4
    big = size * scale
    ring, radius = big * 0.07, big * 0.28
    image = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(radius), fill=255)
    image.paste(_gradient(big), (0, 0), mask)
    draw = ImageDraw.Draw(image)
    inner = big - 2 * ring
    draw.rounded_rectangle([ring, ring, big - ring, big - ring], radius=int(radius - ring * 0.6), fill='#FFFFFF')
    k = inner * 0.62 / 24
    offset = ring + (inner - 24 * k) / 2
    draw.polygon([(offset + x * k, offset + y * k) for x, y in SPARK], fill=SPARK_TEXT)
    return image.resize((size, size), Image.LANCZOS)


def _font(size, weight='bold'):
    for path in ['/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/System/Library/Fonts/Helvetica.ttc',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def logo_png():
    width, height, s = 520, 120, 3
    image = Image.new('RGBA', (width * s, height * s), (0, 0, 0, 0))
    mark = mark_png(96 * s)
    image.paste(mark, (12 * s, 12 * s), mark)
    draw = ImageDraw.Draw(image)
    draw.text((128 * s, 36 * s), 'SPARKS', font=_font(46 * s), fill=INK)
    draw.rounded_rectangle([342 * s, 40 * s, 474 * s, 86 * s], radius=8 * s, fill=CHIP_BG, outline=CHIP_BORDER, width=2 * s)
    draw.text((408 * s, 63 * s), 'AI LAB', font=_font(24 * s), fill=CHIP_TEXT, anchor='mm')
    return image.resize((width, height), Image.LANCZOS)


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob('sparks-ai-lab-logo-on-dark.*'):
        stale.unlink()
    (OUT / 'sparks-ai-lab-mark.svg').write_text(mark_svg(), encoding='utf-8')
    (OUT / 'sparks-ai-lab-logo.svg').write_text(logo_svg(), encoding='utf-8')
    mark_png(512).save(OUT / 'sparks-ai-lab-mark.png')
    mark_png(64).save(OUT / 'sparks-ai-lab-favicon.png')
    logo_png().save(OUT / 'sparks-ai-lab-logo.png')
    print('wrote', sorted(p.name for p in OUT.iterdir()))
