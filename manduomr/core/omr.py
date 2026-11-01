"""Independent, conservative reader for the LocalOMR-60 v1 form.

No proprietary templates are included. Unknown sheets fail closed.
"""
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import hashlib
import cv2
import numpy as np
from PIL import Image, ImageOps, ImageSequence
import pypdfium2 as pdfium

WIDTH, HEIGHT = 1240, 1754
FORM = 'LocalOMR-60-v1'
MARKERS = np.float32([[60, 60], [1180, 60], [1180, 1694], [60, 1694]])
SIGNATURE = (1, 0, 1, 1, 0, 0, 1, 0)
MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_PAGES = 2000


def answer_centers(q):
    col, row = divmod(q, 20)
    return [(185 + col * 365 + k * 43, 560 + row * 48) for k in range(5)]


def id_centers(pos):
    return [(800 + pos * 48, 185 + d * 28) for d in range(10)]


def png_bytes(img):
    stream = BytesIO()
    img.save(stream, format='PNG')
    return stream.getvalue()


def from_png(blob):
    return Image.open(BytesIO(blob)).convert('RGB')


def pixel_hash(img):
    rgb = img.convert('RGB')
    return hashlib.sha256(f'{rgb.size}'.encode() + rgb.tobytes()).hexdigest()


def load_pages(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('파일당 1GB 이내로 나누어 불러오세요.')
    if path.suffix.lower() == '.pdf':
        doc = pdfium.PdfDocument(str(path))
        try:
            if len(doc) > MAX_PAGES:
                raise ValueError('한 파일은 2,000쪽 이내로 나누어 주세요.')
            for i in range(len(doc)):
                page = doc[i]
                try:
                    w, h = page.get_size()
                    scale = min(300 / 72, 3500 / max(w, h))
                    bitmap = page.render(scale=scale)
                    try:
                        yield i + 1, bitmap.to_pil().convert('RGB').copy()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        finally:
            doc.close()
    else:
        with Image.open(path) as src:
            if getattr(src, 'n_frames', 1) > MAX_PAGES:
                raise ValueError('한 파일은 2,000쪽 이내로 나누어 주세요.')
            for i, frame in enumerate(ImageSequence.Iterator(src)):
                rgb = ImageOps.exif_transpose(frame).convert('RGB')
                rgb.thumbnail((3500, 3500))
                yield i + 1, rgb.copy()


def align(img):
    rgb = np.array(img.convert('RGB'))
    for turns in range(4):
        arr = np.ascontiguousarray(np.rot90(rgb, turns))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape
        _, mask = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)
            area = cv2.contourArea(contour)
            if (0.009 * w < cw < 0.04 * w and 0.65 < cw / ch < 1.5
                    and area / (cw * ch) > .72):
                candidates.append((x + cw / 2, y + ch / 2))
        points = []
        for right, bottom in [(False, False), (True, False), (True, True), (False, True)]:
            nearby = [(x, y) for x, y in candidates
                      if (x > .83*w if right else x < .17*w)
                      and (y > .86*h if bottom else y < .14*h)]
            if not nearby:
                break
            tx, ty = (w * .952 if right else w * .048), (h * .966 if bottom else h * .034)
            points.append(min(nearby, key=lambda p: (p[0]-tx)**2 + (p[1]-ty)**2))
        if len(points) != 4:
            continue
        matrix = cv2.getPerspectiveTransform(np.float32(points), MARKERS)
        normal = cv2.warpPerspective(arr, matrix, (WIDTH, HEIGHT), borderValue=(255,255,255))
        ng = cv2.cvtColor(normal, cv2.COLOR_RGB2GRAY)
        observed = tuple(int(ng[90-4:90+5, 180+i*24-4:180+i*24+5].mean() < 130) for i in range(8))
        if observed == SIGNATURE:
            return Image.fromarray(normal), turns * 90
    raise ValueError('전용 OMR의 기준점/양식표시를 찾지 못했습니다. 양식, 잘림, 스캔 상태를 확인하세요.')


def darkness(gray, xy, radius=8):
    x, y = xy
    patch = gray[y-radius:y+radius+1, x-radius:x+radius+1].astype(float)
    yy, xx = np.ogrid[-radius:radius+1, -radius:radius+1]
    values = patch[xx*xx + yy*yy <= radius*radius]
    # Local white reference compensates for moderate paper brightness changes.
    surround = gray[y-20:y+21, x-20:x+21]
    white = max(160, float(np.percentile(surround, 90)))
    return float(np.clip((white-values)/white, 0, 1).mean())


def read_group(gray, centers, labels):
    levels = [round(darkness(gray, p), 4) for p in centers]
    ordered = sorted(range(len(levels)), key=lambda i: levels[i], reverse=True)
    top, second = levels[ordered[0]], levels[ordered[1]]
    if top < .10:
        answer, flag = None, 'blank'
    elif second >= .28:
        answer, flag = None, 'multiple'
    elif top < .55 or second > .12 or top-second < .4:
        answer, flag = labels[ordered[0]], 'faint'
    else:
        answer, flag = labels[ordered[0]], 'clear'
    return {'answer': answer, 'flag': flag, 'levels': levels}


@dataclass
class ReadResult:
    normalized: bytes | None
    answers: list
    code: str | None
    rotation: int = 0
    error: str = ''


def recognize(img, count):
    if not 1 <= count <= 60:
        raise ValueError('문항 수는 1~60이어야 합니다.')
    try:
        normal, rotation = align(img)
    except ValueError as exc:
        return ReadResult(None, [{'answer': None, 'flag': 'failed', 'levels': []} for _ in range(count)], None, error=str(exc))
    gray = np.array(normal.convert('L'))
    answers = [read_group(gray, answer_centers(q), list(range(1, 6))) for q in range(count)]
    digits = [read_group(gray, id_centers(p), list(range(10))) for p in range(6)]
    code = ''.join(str(d['answer']) for d in digits) if all(d['flag']=='clear' for d in digits) else None
    return ReadResult(png_bytes(normal), answers, code, rotation)
