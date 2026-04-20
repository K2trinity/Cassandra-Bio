"""
dev_test_helpers.py — 仅供开发调试使用。

独立出 app.py 的原因：SocketIO 事件必须在服务端进程内发射才能到达浏览器客户端，
所以无法完全脱离服务器进程；但所有业务逻辑（PNG 生成、事件序列）放在这里，
app.py 只保留一个 5 行的薄路由负责调用。

单独运行方式（需服务器已启动）：
    python test_image_preview.py
"""

from __future__ import annotations
import struct
import threading
import zlib
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Tuple

# ---------------------------------------------------------------------------
# PNG 生成：带格子纹路 + 顶部色条 + 白色十字标记
# 不依赖 Pillow / PIL，纯 stdlib 实现合法 PNG 文件
# ---------------------------------------------------------------------------

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    c = tag + data
    return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)


def make_test_png(width: int, height: int, rgb: Tuple[int, int, int], label: str = "") -> bytes:
    """
    生成一张带视觉特征的 PNG 测试图片：
    - 浅色棋盘格背景（模拟图像纹理）
    - 顶部色条（区分不同图片）
    - 中心白色十字标记
    大小约 800-2000 bytes，无任何外部依赖。
    """
    r, g, b = rgb

    def pixel(x: int, y: int) -> Tuple[int, int, int]:
        # 顶部 20px 色条
        if y < 20:
            return r, g, b
        # 棋盘格（16×16 方格，前景色 + 浅白色）
        cell = (x // 16 + y // 16) % 2
        if cell == 0:
            return min(r + 80, 255), min(g + 80, 255), min(b + 80, 255)
        else:
            return max(r - 40, 0), max(g - 40, 0), max(b - 40, 0)

    # 中心十字（5px 宽白色）
    cx, cy = width // 2, height // 2
    cross_pixels: set = set()
    for i in range(-width // 4, width // 4):
        cross_pixels.add((cx + i, cy))
    for i in range(-height // 4, height // 4):
        cross_pixels.add((cx, cy + i))

    rows = bytearray()
    for y in range(height):
        rows.append(0x00)  # filter None
        for x in range(width):
            if (x, y) in cross_pixels:
                rows += bytes([255, 255, 255])
            else:
                rows += bytes(pixel(x, y))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(rows), 6)

    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# 测试图片列表
# ---------------------------------------------------------------------------

TEST_FIGURES: List[Tuple[str, Tuple[int, int, int], str]] = [
    ("figure_001_p1.png", (59,  130, 246), "Figure 1 — Western Blot"),
    ("figure_002_p2.png", (16,  185, 129), "Figure 2 — Gel Electrophoresis"),
    ("figure_003_p3.png", (245, 158,  11), "Figure 3 — Microscopy"),
    ("figure_004_p4.png", (239,  68,  68), "Figure 4 — Flow Cytometry"),
    ("figure_005_p5.png", (139,  92, 246), "Figure 5 — Immunofluorescence"),
]


def generate_test_pngs(output_dir: str = "downloads/temp") -> List[str]:
    """生成测试 PNG 文件，返回文件路径列表。"""
    temp_dir = Path(output_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for fname, rgb, label in TEST_FIGURES:
        fpath = temp_dir / fname
        fpath.write_bytes(make_test_png(260, 180, rgb, label))
        paths.append(str(fpath))
    return paths


# ---------------------------------------------------------------------------
# 事件发射序列（由 app.py 路由注入 emit_fn）
# ---------------------------------------------------------------------------

def run_scan_test_sequence(emit_fn: Callable, active_analysis: dict) -> None:
    """
    模拟 ForensicEngine 逐图扫描事件流。

    Parameters
    ----------
    emit_fn:
        app.py 的 _emit_event(event_type, payload) 函数引用
    active_analysis:
        app.py 的全局 active_analysis dict 引用
    """
    import time

    total = len(TEST_FIGURES)
    _was_running = active_analysis.get("running", False)
    active_analysis["running"] = True

    try:
        emit_fn("log", {
            "level": "info",
            "message": f"🧪 [TEST] Forensic vision preview — simulating {total} figures...",
            "image_path": None,
            "timestamp": datetime.now().isoformat(),
        })
        time.sleep(0.3)

        for idx, (fname, rgb, label) in enumerate(TEST_FIGURES, start=1):
            img_url = f"/static/temp/{fname}"
            emit_fn("log", {
                "level": "scanning",
                "message": f"  Analyzing figure {idx}/{total}: {fname}  ({label})",
                "image_path": img_url,
                "timestamp": datetime.now().isoformat(),
            })
            time.sleep(0.15)
            time.sleep(1.4)  # 模拟 Vision API 延迟

            if idx == 2:
                emit_fn("log", {
                    "level": "warning",
                    "message": "    ⚠️  SUSPICIOUS (tampering risk: 0.78) — Potential clone artifacts",
                    "image_path": None,
                    "timestamp": datetime.now().isoformat(),
                })
            else:
                emit_fn("log", {
                    "level": "success",
                    "message": "    ✅ CLEAN (tampering risk: 0.02) — No anomalies detected",
                    "image_path": None,
                    "timestamp": datetime.now().isoformat(),
                })
            time.sleep(0.3)

        emit_fn("log", {
            "level": "success",
            "message": f"✅ [TEST] Audit complete: {total} figures analyzed.",
            "image_path": None,
            "timestamp": datetime.now().isoformat(),
        })
    finally:
        if not _was_running:
            active_analysis["running"] = _was_running


def start_scan_test_thread(emit_fn: Callable, active_analysis: dict) -> threading.Thread:
    """在后台线程中运行扫描测试序列，立即返回。"""
    t = threading.Thread(
        target=run_scan_test_sequence,
        args=(emit_fn, active_analysis),
        daemon=True,
        name="dev-scan-test",
    )
    t.start()
    return t
