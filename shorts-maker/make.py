"""명령줄 사용 예:
python make.py --product "전자레인지 계란찜기" --notes "3분 완성, 설거지 쉬움" \
    --link https://link.coupang.com/a/xxxx clip1.mp4 photo1.jpg
"""
import argparse
from pathlib import Path

from shortsmaker.pipeline import ALL_KEYS, make_all

ap = argparse.ArgumentParser(description="쇼핑 쇼츠 자동 제작기")
ap.add_argument("media", nargs="+", type=Path, help="상품 영상/사진 (직접 찍었거나 사용 허락된 것)")
ap.add_argument("--product", required=True, help="상품명")
ap.add_argument("--notes", default="", help="특징·장점 메모")
ap.add_argument("--link", default="", help="쿠팡 파트너스 등 제휴 링크")
ap.add_argument("--only", nargs="*", choices=ALL_KEYS, help="일부 버전만 만들기")
ap.add_argument("--out", type=Path, default=Path("output"))
a = ap.parse_args()

for p in make_all(a.product, a.notes, a.media, a.out, a.only, a.link):
    print("→", p)
