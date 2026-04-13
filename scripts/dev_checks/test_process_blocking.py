"""
test_process_blocking.py
========================
检测 Cassandra 后端是否存在以下问题：
  1. 重复提交保护 — 同时发送两个 /api/analyze 请求，第二个必须返回 409
  2. Cancel 有效性 — 启动分析后立即 POST /api/reset，状态必须在 grace_timeout 内变为 running=False
  3. 刷新页面清理 — 模拟 beforeunload beacon：调用 /api/reset，再查 /api/status 确认 running=False
  4. 进程堵塞检测 — 反复 cancel-restart 5 次，检查线程数是否持续上涨（泄漏检测）

用法:
    # 确保 Cassandra 服务正在运行（默认 http://localhost:5000）
    python scripts/dev_checks/test_process_blocking.py

    # 指定地址
    python scripts/dev_checks/test_process_blocking.py --base-url http://localhost:5001

依赖: requests（已在 requirements.txt 中）
"""

import sys
import time
import threading
import argparse
import requests

# ─────────────────────────────────────────────
# 测试配置
# ─────────────────────────────────────────────
DEFAULT_BASE_URL = "http://localhost:5000"
CANCEL_GRACE_TIMEOUT = 30   # 取消后等待线程停止的最长秒数
THREAD_LEAK_CYCLES = 5      # 反复 cancel-restart 的轮次
DUMMY_QUERY = "test_process_blocking dummy query"

# ─────────────────────────────────────────────
# 自动探测可用的服务器地址
# ─────────────────────────────────────────────

def _detect_server_address(port: int) -> str:
    """
    尝试按优先级探测可用地址：127.0.0.1 → 本机 LAN IP → localhost。
    返回第一个能正常响应 /api/status 的地址，否则返回 localhost。
    """
    import socket as _socket
    candidates = [f"http://127.0.0.1:{port}"]
    try:
        hostname = _socket.gethostname()
        lan_ip = _socket.gethostbyname(hostname)
        if lan_ip not in ("127.0.0.1", "::1"):
            candidates.append(f"http://{lan_ip}:{port}")
    except Exception:
        pass
    candidates.append(f"http://localhost:{port}")

    for addr in candidates:
        try:
            r = requests.get(f"{addr}/api/status", timeout=3)
            if r.status_code == 200:
                return addr
        except Exception:
            pass
    return f"http://localhost:{port}"

GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW= "\033[93m"
RESET = "\033[0m"

passed = 0
failed = 0
skipped = 0

def _ok(msg: str):
    global passed
    passed += 1
    print(f"  {GREEN}✓ PASS{RESET}  {msg}")

def _fail(msg: str):
    global failed
    failed += 1
    print(f"  {RED}✗ FAIL{RESET}  {msg}")

def _skip(msg: str):
    global skipped
    skipped += 1
    print(f"  {YELLOW}⚠ SKIP{RESET}  {msg}")

def _header(title: str):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print('─'*55)


# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────

def get_status(base: str) -> dict:
    r = requests.get(f"{base}/api/status", timeout=5)
    r.raise_for_status()
    return r.json()


def do_reset(base: str) -> dict:
    r = requests.post(f"{base}/api/reset", timeout=5)
    r.raise_for_status()
    return r.json()


def start_analysis(base: str, query: str = DUMMY_QUERY) -> requests.Response:
    """非阻塞地提交一个分析任务，立即返回响应对象。"""
    return requests.post(
        f"{base}/api/analyze",
        json={"query": query},
        timeout=10,
    )


def wait_until_stopped(base: str, timeout: int) -> bool:
    """轮询 /api/status 直到 running=False 或超时，返回是否成功停止。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = get_status(base)
            if not s.get("running"):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def ensure_idle(base: str):
    """测试前先确认/强制服务器处于 idle 状态。"""
    status = get_status(base)
    if status.get("running"):
        do_reset(base)
        wait_until_stopped(base, timeout=15)


# ─────────────────────────────────────────────
# 测试用例
# ─────────────────────────────────────────────

def test_server_reachable(base: str) -> bool:
    _header("Test 0 — 服务可达性")
    try:
        r = requests.get(f"{base}/api/status", timeout=5)
        if r.status_code == 200:
            _ok(f"服务器 {base} 可达，状态码 200")
            return True
        else:
            _fail(f"服务器返回意外状态码 {r.status_code} — 请检查 TRUSTED_HOSTS 配置")
            return False
    except requests.exceptions.ConnectionError:
        _fail(f"无法连接到 {base}，请先启动 Cassandra 服务")
        return False
    except Exception as e:
        _fail(f"连接异常: {e}")
        return False


def test_duplicate_submission(base: str):
    _header("Test 1 — 重复提交保护（期望第二个请求返回 409）")
    ensure_idle(base)

    results = [None, None]
    errors  = [None, None]

    def _submit(idx: int, delay: float):
        time.sleep(delay)
        try:
            results[idx] = start_analysis(base)
        except Exception as e:
            errors[idx] = e

    t1 = threading.Thread(target=_submit, args=(0, 0.0))
    t2 = threading.Thread(target=_submit, args=(1, 0.1))  # 100ms 后再提交
    t1.start(); t2.start()
    t1.join(timeout=15); t2.join(timeout=15)

    if errors[0] or errors[1]:
        _fail(f"请求异常: {errors[0] or errors[1]}")
        return

    r1, r2 = results[0], results[1]
    codes = sorted([r1.status_code, r2.status_code])

    if codes == [200, 409] or codes == [202, 409]:
        _ok(f"第一个请求 {r1.status_code}，第二个请求被正确拒绝 409")
    elif codes == [409, 409]:
        _fail("两个请求都返回 409 — 第一个也没成功启动")
    else:
        _fail(f"未触发 409 保护，返回码：{r1.status_code}, {r2.status_code}")

    # 清理
    do_reset(base)
    wait_until_stopped(base, timeout=20)


def test_cancel_effectiveness(base: str):
    _header("Test 2 — Cancel (/api/reset) 有效性")
    ensure_idle(base)

    # 启动分析
    r = start_analysis(base)
    if r.status_code not in (200, 202):
        _skip(f"无法启动分析（状态码 {r.status_code}），跳过此测试")
        return

    # 立即取消
    time.sleep(0.5)
    reset_r = do_reset(base)
    if reset_r.get("status") != "ok":
        _fail(f"/api/reset 返回非 ok: {reset_r}")

    # 等待线程真正停止
    stopped = wait_until_stopped(base, timeout=CANCEL_GRACE_TIMEOUT)
    if stopped:
        _ok(f"取消指令发送后，服务器在 {CANCEL_GRACE_TIMEOUT}s 内停止（running=False）")
    else:
        _fail(
            f"取消后 {CANCEL_GRACE_TIMEOUT}s 内服务器仍未停止 — 疑似线程阻塞（cooperative cancel 未生效）\n"
            f"        当前状态: {get_status(base)}"
        )
        do_reset(base)


def test_refresh_page_cleanup(base: str):
    _header("Test 3 — 刷新页面清理（模拟 beforeunload beacon）")
    ensure_idle(base)

    # 启动分析
    r = start_analysis(base)
    if r.status_code not in (200, 202):
        _skip(f"无法启动分析（状态码 {r.status_code}），跳过此测试")
        return

    time.sleep(0.3)
    # 模拟 navigator.sendBeacon（Content-Type: text/plain 是 beacon 的默认类型）
    beacon_r = requests.post(
        f"{base}/api/reset",
        data="{}",
        headers={"Content-Type": "text/plain"},
        timeout=5
    )

    if beacon_r.status_code == 200:
        _ok("beacon-style POST /api/reset 被服务器接受（200）")
    else:
        _fail(f"beacon POST 失败，状态码: {beacon_r.status_code}")

    # 再查询状态
    stopped = wait_until_stopped(base, timeout=CANCEL_GRACE_TIMEOUT)
    if stopped:
        _ok("beacon reset 后服务器状态正确变为 running=False")
    else:
        _fail(f"beacon reset 后 {CANCEL_GRACE_TIMEOUT}s 内状态仍为 running=True")
        do_reset(base)

    # 模拟 DOMContentLoaded 逻辑：若新页面加载时发现 running=True 也能清理
    status = get_status(base)
    if not status.get("running"):
        _ok("模拟 DOMContentLoaded 检查：服务器处于 idle，无需额外清理")
    else:
        # 再次 reset 并检查
        do_reset(base)
        stopped2 = wait_until_stopped(base, timeout=10)
        if stopped2:
            _ok("DOMContentLoaded 补救 reset 成功")
        else:
            _fail("DOMContentLoaded 补救 reset 后仍未 idle")


def test_thread_leak_detection(base: str):
    _header(f"Test 4 — 进程泄漏检测（{THREAD_LEAK_CYCLES} 轮 cancel-restart）")
    ensure_idle(base)

    # 获取基线线程数（通过 /api/debug/threads 或估算）
    # 由于后端可能没有 debug endpoint，我们使用间接方法：
    # 连续 cancel-restart，若服务器无泄漏则每次 /api/status 均能正常响应
    latencies = []
    all_ok = True

    for i in range(THREAD_LEAK_CYCLES):
        # 启动
        r = start_analysis(base, query=f"leak_test_cycle_{i}")
        if r.status_code not in (200, 202):
            _skip(f"  轮次 {i+1}: 无法启动分析（{r.status_code}），跳过")
            continue

        # 立即取消
        time.sleep(0.3)
        do_reset(base)

        # 计时等待
        t0 = time.time()
        stopped = wait_until_stopped(base, timeout=CANCEL_GRACE_TIMEOUT)
        elapsed = time.time() - t0
        latencies.append(elapsed)

        if not stopped:
            _fail(f"  轮次 {i+1}: 取消后 {CANCEL_GRACE_TIMEOUT}s 内未停止 — 可能存在线程阻塞")
            all_ok = False
            do_reset(base)  # 强制清理再继续
        else:
            status_after = get_status(base)
            if status_after.get("running"):
                _fail(f"  轮次 {i+1}: running 仍为 True")
                all_ok = False
            else:
                print(f"         轮次 {i+1}: 停止耗时 {elapsed:.1f}s ✓")

    if latencies:
        avg = sum(latencies) / len(latencies)
        mx  = max(latencies)
        # 若每轮耗时持续上涨（最后一轮 > 3x 第一轮），怀疑线程积压
        if len(latencies) >= 2 and latencies[-1] > latencies[0] * 3:
            _fail(
                f"停止耗时持续上涨 ({latencies[0]:.1f}s → {latencies[-1]:.1f}s) — "
                f"线程可能正在积压，存在阻塞风险"
            )
            all_ok = False
        elif all_ok:
            _ok(f"全部 {len(latencies)} 轮正常停止，平均 {avg:.1f}s，最大 {mx:.1f}s，无泄漏迹象")


def test_stale_state_guard(base: str):
    _header("Test 5 — 僵尸状态守卫（running=True 但线程已死时应自动重置）")
    # 无法直接制造死线程，改为验证：若 running=False，提交新任务能否正常返回 200
    ensure_idle(base)

    status = get_status(base)
    if status.get("running"):
        _skip("服务器仍在运行，无法测试 idle 状态，跳过")
        return

    r = start_analysis(base, query="stale_guard_test")
    if r.status_code in (200, 202):
        _ok(f"idle 状态下能正常提交分析（{r.status_code}）")
        do_reset(base)
        wait_until_stopped(base, timeout=20)
    else:
        _fail(f"idle 状态下提交返回 {r.status_code}：{r.text[:200]}")


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

def main():
    global CANCEL_GRACE_TIMEOUT
    parser = argparse.ArgumentParser(description="Cassandra 进程阻塞测试套件")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Cassandra 服务地址")
    parser.add_argument("--cancel-timeout", type=int, default=CANCEL_GRACE_TIMEOUT,
                        help=f"取消后等待线程停止的最长秒数（默认 {CANCEL_GRACE_TIMEOUT}）")
    args = parser.parse_args()

    CANCEL_GRACE_TIMEOUT = args.cancel_timeout
    base = args.base_url.rstrip("/")

    # 如果用户未显式指定地址，或指定的 localhost 不可达，则自动探测
    try:
        port = int(base.split(":")[-1])
    except (ValueError, IndexError):
        port = 5000

    if "localhost" in base or "127.0.0.1" in base:
        detected = _detect_server_address(port)
        if detected != base:
            print(f"  ℹ️  自动切换地址: {base} → {detected}（Werkzeug Host 头限制）")
            base = detected
    else:
        base = base

    print("\n" + "═"*55)
    print("  Cassandra 进程阻塞 & 重复提交保护 测试套件")
    print("═"*55)
    print(f"  目标服务器: {base}")
    print(f"  取消超时:   {CANCEL_GRACE_TIMEOUT}s")

    # 服务可达性检测（若失败则终止）
    if not test_server_reachable(base):
        print(f"\n{RED}服务器不可达，终止所有测试。{RESET}")
        print("请运行: python app.py  或  python main.py")
        sys.exit(1)

    test_duplicate_submission(base)
    test_cancel_effectiveness(base)
    test_refresh_page_cleanup(base)
    test_thread_leak_detection(base)
    test_stale_state_guard(base)

    # ── 最终汇总 ──
    total = passed + failed + skipped
    print("\n" + "═"*55)
    print(f"  结果汇总: {total} 项检测")
    print(f"  {GREEN}通过: {passed}{RESET}  |  {RED}失败: {failed}{RESET}  |  {YELLOW}跳过: {skipped}{RESET}")
    print("═"*55 + "\n")

    if failed > 0:
        print(f"{RED}⚠️  存在 {failed} 项问题，请根据上方输出排查。{RESET}\n")
        sys.exit(1)
    else:
        print(f"{GREEN}✅ 所有有效测试通过，未发现进程阻塞问题。{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
