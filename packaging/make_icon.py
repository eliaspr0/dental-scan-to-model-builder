"""Generate the app icon (packaging/icon.png, icon.ico, icon.icns) with Pillow. Run: python packaging/make_icon.py

Design: the app's blue rounded square with a white molar-style tooth standing on a flat base slab
(the tooth = the scan, the slab = the printable base the app builds)."""
import os
from PIL import Image, ImageDraw

here = os.path.dirname(os.path.abspath(__file__))
BLUE = (0, 113, 227, 255)
BLUE_DEEP = (0, 84, 180, 255)
WHITE = (255, 255, 255, 255)
S = 1024
SS = 4                                     # supersampling for smooth edges


def bez(p0, p1, p2, p3, n=48):
    pts = []
    for i in range(n + 1):
        t = i / n; u = 1 - t
        pts.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return pts


def tooth_outline():
    """Molar crown with two roots, in a 1024 box (x right, y down)."""
    P = []
    P += bez((300, 330), (300, 250), (370, 215), (430, 232))            # left cusp, rising
    P += bez((430, 232), (470, 243), (490, 262), (512, 262))[1:]        # dip between cusps
    P += bez((512, 262), (534, 262), (554, 243), (594, 232))[1:]
    P += bez((594, 232), (654, 215), (724, 250), (724, 330))[1:]        # right cusp
    P += bez((724, 330), (724, 430), (690, 470), (682, 540))[1:]        # right side, narrowing to the roots
    P += bez((682, 540), (672, 620), (676, 700), (650, 720))[1:]        # right root
    P += bez((650, 720), (622, 738), (590, 700), (570, 610))[1:]
    P += bez((570, 610), (562, 575), (548, 558), (512, 558))[1:]        # notch between the roots
    P += bez((512, 558), (476, 558), (462, 575), (454, 610))[1:]
    P += bez((454, 610), (434, 700), (402, 738), (374, 720))[1:]        # left root
    P += bez((374, 720), (348, 700), (352, 620), (342, 540))[1:]
    P += bez((342, 540), (334, 470), (300, 430), (300, 330))[1:]
    return P


def draw(size=S):
    k = SS
    im = Image.new('RGBA', (S * k, S * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((40 * k, 40 * k, (S - 40) * k, (S - 40) * k), radius=230 * k, fill=BLUE)
    # base slab under the tooth
    d.rounded_rectangle((190 * k, 716 * k, (S - 190) * k, 816 * k), radius=40 * k, fill=WHITE)
    # tooth
    d.polygon([(x * k, y * k) for x, y in tooth_outline()], fill=WHITE)
    # soft highlight line on the crown (keeps it readable as a tooth at small sizes)
    for x, y in bez((372, 335), (372, 305), (390, 285), (420, 280), n=80):
        d.ellipse(((x - 7) * k, (y - 7) * k, (x + 7) * k, (y + 7) * k), fill=BLUE_DEEP)
    return im.resize((size, size), Image.LANCZOS)


if __name__ == '__main__':
    im = draw()
    im.save(os.path.join(here, 'icon.png'))
    im.save(os.path.join(here, 'icon.ico'), sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    try:
        im.save(os.path.join(here, 'icon.icns'))
    except Exception as e:
        print('icns not written:', e)
