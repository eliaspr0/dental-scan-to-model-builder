"""Generate the app icon (packaging/icon.png, icon.ico, icon.icns) with Pillow. Run: python packaging/make_icon.py"""
import os
from PIL import Image, ImageDraw

here = os.path.dirname(os.path.abspath(__file__))
S = 1024
im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=230, fill=(0, 113, 227, 255))
# horseshoe arch (the model's footprint) + flat base slab
d.arc((220, 200, S - 220, 760), 180, 360, fill=(255, 255, 255, 255), width=120)
d.rectangle((220, 470, 340, 560), fill=(255, 255, 255, 255)); d.rectangle((S - 340, 470, S - 220, 560), fill=(255, 255, 255, 255))
d.rounded_rectangle((200, 700, S - 200, 800), radius=40, fill=(255, 255, 255, 255))
im.save(os.path.join(here, 'icon.png'))
im.save(os.path.join(here, 'icon.ico'), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
try:
    im.save(os.path.join(here, 'icon.icns'))
except Exception as e:
    print('icns not written:', e)
