"""데모용 제품 일러스트 5종 (직접 그린 원본 그림)."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

S = 1080  # 정사각 일러스트
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)


def base(c1, c2):
    img = Image.new("RGB", (S, S), c1)
    d = ImageDraw.Draw(img)
    for y in range(S):
        t = y / S
        d.line([(0, y), (S, y)], fill=tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)))
    return img


def shadow(img, box, r=40):
    sh = Image.new("L", img.size, 0)
    ImageDraw.Draw(sh).ellipse(box, fill=90)
    sh = sh.filter(ImageFilter.GaussianBlur(r))
    img.paste((0, 0, 0), (0, 0), sh)


def eye(d, x, y, r=16):
    d.ellipse([x - r, y - r, x + r, y + r], fill="white")
    d.ellipse([x - r * .55, y - r * .4, x + r * .55, y + r * .7], fill=(30, 30, 30))
    d.ellipse([x - r * .1, y - r * .25, x + r * .25, y + r * .1], fill="white")


# 5위 참새 티 인퓨저: 머그 위 참새
img = base((255, 238, 214), (246, 205, 170)); shadow(img, (300, 860, 780, 940))
d = ImageDraw.Draw(img)
d.rounded_rectangle([320, 480, 720, 900], 60, fill=(250, 250, 248), outline=(220, 210, 200), width=6)
d.ellipse([320, 440, 720, 530], fill=(160, 95, 45)); d.ellipse([340, 450, 700, 515], fill=(186, 116, 58))
d.arc([660, 560, 840, 760], -90, 90, fill=(250, 250, 248), width=36)
for x in (420, 520, 610):
    d.arc([x - 30, 250, x + 30, 420], 200, 340, fill=(255, 255, 255), width=8)
d.ellipse([420, 330, 610, 470], fill=(150, 105, 70))          # 몸
d.ellipse([540, 290, 650, 400], fill=(150, 105, 70))          # 머리
d.ellipse([560, 330, 640, 400], fill=(245, 230, 210))         # 볼
d.polygon([(645, 345), (700, 360), (645, 372)], fill=(240, 170, 60))
eye(d, 600, 335, 12)
d.polygon([(430, 400), (330, 470), (360, 500), (450, 440)], fill=(110, 75, 50))  # 꼬리(차에 잠김)
d.ellipse([450, 360, 560, 440], fill=(120, 85, 55))           # 날개
img.save(OUT / "5.png")

# 4위 개구리 수세미 거치대
img = base((214, 240, 250), (175, 215, 235)); shadow(img, (300, 880, 780, 960))
d = ImageDraw.Draw(img)
d.rectangle([0, 0, S, 300], fill=(235, 240, 242))
for x in range(0, S, 120):
    d.line([(x, 0), (x, 300)], fill=(210, 218, 222), width=4)
d.ellipse([300, 380, 780, 860], fill=(110, 190, 90))
d.ellipse([320, 300, 480, 460], fill=(110, 190, 90)); d.ellipse([600, 300, 760, 460], fill=(110, 190, 90))
eye(d, 400, 380, 45); eye(d, 680, 380, 45)
d.chord([360, 520, 720, 800], 0, 180, fill=(170, 40, 60))
d.rounded_rectangle([390, 560, 690, 700], 30, fill=(250, 215, 60))
d.rounded_rectangle([390, 640, 690, 700], 20, fill=(70, 150, 80))
for i in range(6):
    d.ellipse([440 + i * 40, 590, 455 + i * 40, 605], fill=(230, 190, 40))
for x, y in ((360, 820), (720, 820), (540, 880)):
    d.ellipse([x - 10, y - 16, x + 10, y + 16], fill=(120, 190, 240))
img.save(OUT / "4.png")

# 3위 나무늘보 케이블 클립
img = base((240, 232, 220), (215, 200, 180)); shadow(img, (200, 900, 880, 980))
d = ImageDraw.Draw(img)
d.rectangle([0, 520, S, 600], fill=(170, 120, 75)); d.rectangle([0, 600, S, 640], fill=(140, 95, 55))
d.line([(0, 760), (300, 700), (560, 690), (800, 720), (S, 780)], fill=(250, 250, 250), width=26, joint="curve")
d.ellipse([420, 560, 660, 840], fill=(150, 115, 85))
d.ellipse([440, 470, 640, 650], fill=(150, 115, 85))
d.ellipse([470, 520, 610, 630], fill=(235, 215, 185))
d.ellipse([480, 545, 525, 585], fill=(90, 60, 40)); d.ellipse([555, 545, 600, 585], fill=(90, 60, 40))
eye(d, 502, 565, 10); eye(d, 578, 565, 10)
d.arc([515, 585, 565, 615], 20, 160, fill=(70, 45, 30), width=5)
d.rounded_rectangle([380, 650, 470, 760], 40, fill=(130, 95, 70)); d.rounded_rectangle([610, 650, 700, 760], 40, fill=(130, 95, 70))
d.rounded_rectangle([420, 450, 480, 560], 30, fill=(130, 95, 70)); d.rounded_rectangle([600, 450, 660, 560], 30, fill=(130, 95, 70))
img.save(OUT / "3.png")

# 2위 악어 냄비뚜껑 받침
img = base((255, 232, 225), (240, 200, 190)); shadow(img, (220, 880, 860, 960))
d = ImageDraw.Draw(img)
d.ellipse([260, 160, 820, 760], fill=(200, 225, 235), outline=(150, 170, 180), width=14)
d.ellipse([480, 130, 600, 200], fill=(60, 60, 60))
d.rounded_rectangle([260, 700, 820, 900], 80, fill=(90, 170, 80))
d.polygon([(260, 740), (820, 700), (820, 760), (260, 790)], fill=(240, 240, 230))  # 이빨 라인
for x in range(290, 800, 50):
    d.polygon([(x, 760), (x + 25, 730), (x + 50, 760)], fill="white")
eye(d, 360, 690, 34); eye(d, 720, 690, 34)
d.ellipse([320, 640, 400, 700], outline=(90, 170, 80), width=10); d.ellipse([680, 640, 760, 700], outline=(90, 170, 80), width=10)
for x in range(320, 780, 90):
    d.ellipse([x, 830, x + 40, 860], fill=(70, 140, 65))
img.save(OUT / "2.png")

# 1위 기지개 고양이 폰 거치대
img = base((60, 55, 90), (120, 90, 120)); shadow(img, (260, 900, 820, 980))
d = ImageDraw.Draw(img)
d.ellipse([760, 80, 1000, 320], fill=(255, 220, 150))
d.rounded_rectangle([340, 130, 740, 560], 50, fill=(30, 30, 35))
d.rounded_rectangle([360, 150, 720, 540], 36, fill=(120, 200, 255))
d.polygon([(500, 290), (500, 400), (600, 345)], fill="white")
d.rounded_rectangle([420, 520, 660, 900], 110, fill=(250, 250, 248))          # 몸통(길게)
d.ellipse([400, 520, 500, 620], fill=(250, 250, 248)); d.ellipse([580, 520, 680, 620], fill=(250, 250, 248))  # 앞발
d.ellipse([440, 700, 640, 860], fill=(250, 250, 248))
d.polygon([(470, 720), (490, 650), (525, 715)], fill=(250, 250, 248)); d.polygon([(555, 715), (590, 650), (610, 720)], fill=(250, 250, 248))
d.polygon([(482, 712), (492, 675), (512, 710)], fill=(250, 190, 200)); d.polygon([(568, 710), (588, 675), (598, 712)], fill=(250, 190, 200))
d.arc([480, 760, 530, 800], 200, 340, fill=(60, 60, 60), width=6); d.arc([550, 760, 600, 800], 200, 340, fill=(60, 60, 60), width=6)
d.polygon([(530, 805), (550, 805), (540, 818)], fill=(240, 150, 170))
d.arc([640, 760, 840, 940], 180, 300, fill=(250, 250, 248), width=36)
img.save(OUT / "1.png")
print("ok")
