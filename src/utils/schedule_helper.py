"""
98tang 每日随机时间签到调度决策脚本

用于在 GitHub Actions schedule 触发时动态决定是否在当前时隙执行签到。
在 00:00 ~ 08:59 北京时间范围内，每天根据当前日期伪随机生成一个目标小时和分钟抖动。
"""

import datetime
import hashlib
import os
import sys
import time

BJT = datetime.timezone(datetime.timedelta(hours=8))


def main():
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    force_run = os.environ.get("FORCE_RUN", "false").lower() == "true"

    now_bjt = datetime.datetime.now(BJT)
    today_str = now_bjt.strftime("%Y-%m-%d")
    current_hour = now_bjt.hour
    current_minute = now_bjt.minute

    print(
        f"[Schedule Check] 当前北京时间: {now_bjt.strftime('%Y-%m-%d %H:%M:%S')} (触发事件: {event_name})"
    )

    # 1. 如果是手动触发、代码推送或强制模式，立即执行
    if event_name in ("workflow_dispatch", "push") or force_run:
        print(f"[Schedule Check] 触发事件为 {event_name}，立即执行签到。")
        set_output("should_run", "true")
        set_output("jitter_seconds", "0")
        return 0

    # 2. 如果当前已经过了 09:00（比如中午 12 点的兜底时隙），立即执行兜底
    if current_hour >= 9:
        print(f"[Schedule Check] 当前为后备兜底窗口 ({current_hour:02d}:xx >= 09:00)，允许执行。")
        set_output("should_run", "true")
        set_output("jitter_seconds", "0")
        return 0

    # 3. 计算今日随机目标小时 (0 ~ 8) 与分钟抖动 (0 ~ 34)
    salt = "98tang_random_sign_seed"
    h = int(hashlib.md5(f"{today_str}_{salt}".encode()).hexdigest(), 16)
    target_hour = h % 9  # 00:xx ~ 08:xx BJT
    jitter_minutes = (h >> 4) % 35  # 0 ~ 34 分钟的自然漂移
    target_time_display = f"{target_hour:02d}:{17 + jitter_minutes:02d}"

    print(f"[Schedule Check] 今日计算出的随机目标时间点约为: {target_time_display} BJT")

    # 4. 判断当前小时与目标小时的关系
    if current_hour < target_hour:
        print(
            f"[Schedule Check] 当前小时 ({current_hour:02d}) < 目标小时 ({target_hour:02d})，未到签到窗口，跳过本次调度。"
        )
        set_output("should_run", "false")
        set_output("jitter_seconds", "0")
        return 0

    if current_hour == target_hour:
        jitter_sec = jitter_minutes * 60
        print(
            f"[Schedule Check] 命中今日目标时段 ({target_hour:02d}点)！加入随机平滑抖动 {jitter_minutes} 分钟 ({jitter_sec}秒)..."
        )
        set_output("should_run", "true")
        set_output("jitter_seconds", str(jitter_sec))
        return 0

    # current_hour > target_hour：说明此前目标小时可能被 GitHub 延迟丢单或失败
    print(
        f"[Schedule Check] 当前小时 ({current_hour:02d}) > 目标小时 ({target_hour:02d})，作为自愈重试通道执行！"
    )
    set_output("should_run", "true")
    set_output("jitter_seconds", "0")
    return 0


def set_output(name, value):
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output and os.path.exists(github_output):
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    print(f"Output: {name}={value}")


if __name__ == "__main__":
    sys.exit(main())
