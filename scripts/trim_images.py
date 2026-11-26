"""Trim the flat page-background margin around rendered diagrams, keeping a small even border."""
import sys

from PIL import Image, ImageChops

PAD = 28


def trim(path):
    image = Image.open(path).convert('RGB')
    background = Image.new('RGB', image.size, image.getpixel((2, 2)))
    box = ImageChops.difference(image, background).point(lambda v: 255 if v > 6 else 0).getbbox()
    if box:
        left, top, right, bottom = box
        box = (max(left - PAD, 0), max(top - PAD, 0), min(right + PAD, image.width), min(bottom + PAD, image.height))
        image.crop(box).save(path)
    return image.size, box


if __name__ == '__main__':
    for target in sys.argv[1:]:
        print(target.rsplit('/', 1)[-1], trim(target))
