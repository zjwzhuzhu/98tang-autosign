"""
GoCaptcha 验证码缺口识别（纯 OpenCV 实现，可在 GitHub Actions 无头环境运行）

dd_sign 插件签到前使用 GoCaptcha（click/slide/drag/rotate 随机类型）。
对 slide / drag（SlideRegion）类型，前端会 POST
    misc.php?mod=captcha&action=check  body: "x,y"
其中 (x, y) 是拼图缺口在背景图中的位置。因此无需在浏览器里真实拖拽滑块，
只要从验证码接口返回的两张图（背景图 + 拼图块）算出缺口坐标，直接 POST 即可。
"""

import base64

import cv2
import numpy as np


def decode_image(b64data):
    """解析 base64 图片（兼容 data:image/xxx;base64, 前缀）"""
    if not b64data:
        return None
    if "," in b64data and b64data[:5].lower() != "data:" and "," not in b64data[:20]:
        pass
    if b64data.startswith("data:"):
        b64data = b64data.split(",", 1)[1]
    try:
        raw = base64.b64decode(b64data)
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    except Exception:
        return None


def _crop_alpha(img, thresh=8):
    """按 alpha 通道裁出拼图块的有效区域（避免透明边框干扰匹配）"""
    if img is None:
        return None
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3]
        ys, xs = np.where(alpha > thresh)
        if len(xs):
            img = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return img


def detect_gap(master_b64, thumb_b64):
    """
    定位拼图缺口在背景图中的可见块左上角 (x, y)，并返回 thumb 画布内可见块的
    alpha 偏移 (ox, oy)——服务端记录的答案是「画布位置」，画布位置 = 缺口位置 - 偏移。

    使用 Canny 边缘模板匹配 + 掩码 SQDIFF 兜底，二者一致(±3px)时取均值。
    返回 (x, y, ox, oy) 或 None。
    """
    bg = decode_image(master_b64)
    if bg is None:
        return None
    if bg.ndim == 3 and bg.shape[2] == 4:
        bg = cv2.cvtColor(bg, cv2.COLOR_BGRA2BGR)

    pc_raw = decode_image(thumb_b64)
    pc = _crop_alpha(pc_raw)
    if pc is None:
        return None
    if pc.ndim == 3:
        pc = cv2.cvtColor(
            pc, cv2.COLOR_BGRA2BGR if pc.shape[2] == 4 else cv2.COLOR_BGR2GRAY
        )

    # 可见块在画布内的偏移（生成器固定内边距，如 (7,2)）
    ox, oy = 0, 0
    if pc_raw is not None and pc_raw.ndim == 3 and pc_raw.shape[2] == 4:
        alpha = pc_raw[:, :, 3]
        ys_a, xs_a = np.where(alpha > 8)
        if len(xs_a):
            ox, oy = int(xs_a.min()), int(ys_a.min())

    bgg = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    pcg = pc if pc.ndim == 2 else cv2.cvtColor(pc, cv2.COLOR_BGR2GRAY)
    if bgg.shape[0] < pcg.shape[0] or bgg.shape[1] < pcg.shape[1]:
        return None

    # 1) Canny 边缘模板匹配
    best = None
    for lo, hi in ((100, 200), (50, 150)):
        be = cv2.Canny(bgg, lo, hi)
        pe = cv2.Canny(pcg, lo, hi)
        if be.shape[0] < pe.shape[0] or be.shape[1] < pe.shape[1]:
            continue
        r = cv2.matchTemplate(be, pe, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(r)
        if best is None or mv > best[2]:
            best = (int(ml[0]), int(ml[1]), float(mv))

    # 2) 掩码 SQDIFF 兜底
    sq = None
    pc4 = decode_image(thumb_b64)
    if pc4 is not None and pc4.ndim == 3 and pc4.shape[2] == 4:
        alpha = pc4[:, :, 3]
        ys, xs = np.where(alpha > 8)
        if len(xs):
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            pc_rgb = cv2.cvtColor(pc4, cv2.COLOR_BGRA2BGR)[y0:y1, x0:x1]
            mask = (alpha[y0:y1, x0:x1].astype(np.float32) / 255.0)
            pcg2 = cv2.cvtColor(pc_rgb, cv2.COLOR_BGR2GRAY)
            if bgg.shape[0] >= pcg2.shape[0] and bgg.shape[1] >= pcg2.shape[1]:
                try:
                    r = cv2.matchTemplate(bgg, pcg2, cv2.TM_SQDIFF_NORMED, mask=mask)
                    r = np.nan_to_num(r, nan=1e9, posinf=1e9, neginf=1e9)
                    _, _, ml2, _ = cv2.minMaxLoc(r)
                    sq = (int(ml2[0]), int(ml2[1]))
                except cv2.error:
                    sq = None

    # 3) 投票
    if best and sq and abs(best[0] - sq[0]) <= 3:
        return (int(round((best[0] + sq[0]) / 2)), best[1], ox, oy)
    if best:
        return (best[0], best[1], ox, oy)
    if sq:
        return (sq[0], sq[1], ox, oy)
    return None
