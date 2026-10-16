"""
98tang 每日随机时间签到调度助手

在各个预设的时间窗口触发时：
1. 计算今日基于日期的伪随机平滑抖动时间（1 ~ 15 分钟），使每天、每次运行的具体打卡分钟数完全离散；
2. 只要有调度窗口触发就执行签到（后续窗口若检测到“今日已签到”会在数秒内秒退，不浪费验证码配额）；
3. 避免“主动跳过当前可用调度、盲等后续时隙却被 GitHub 调度器丢单”的风险。
"""

import datetime
import hashlib
import os
import sys

BJT = datetime.timezone(datetime.timedelta(hours=8))


def main():
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    force_run = os.environ.get("FORCE_RUN", "false").lower() == "true"

    now_bjt = datetime.datetime.now(BJT)
    today_str = now_bjt.strftime("%Y-%m-%d")

    print(
        f"[Schedule Check] 当前北京时间: {now_bjt.strftime('%Y-%m-%d %H:%M:%S')} (触发事件: {event_name})"
    )

    # 1. 手动触发、代码推送或强制模式：不抖动，直接运行
    if event_name in ("workflow_dispatch", "push") or force_run:
        print(f"[Schedule Check] 触发事件为 {event_name}，立即执行签到。")
        set_output("should_run", "true")
        set_output("jitter_seconds", "0")
        return 0

    # 2. 定时事件 (schedule)：
    # 计算今日动态随机平滑抖动：60秒 ~ 540秒 (1 ~ 9分钟)
    # 结合 GitHub 自身 runner 调度 5~60分钟的自然排队延迟，
    # 实际签到时间在 00:xx ~ 08:xx 窗口内完全离散分布。
    salt = "98tang_random_sign_seed"
    h = int(hashlib.md5(f"{today_str}_{salt}".encode()).hexdigest(), 16)
    jitter_sec = 60 + (h % 480)  # 60 ~ 539 秒 (1~9分钟)
    jitter_min = round(jitter_sec / 60, 1)

    print(
        f"[Schedule Check] 命中调度窗口，今日计算出的随机平滑抖动为 {jitter_min} 分钟 ({jitter_sec} 秒)。"
    )
    set_output("should_run", "true")
    set_output("jitter_seconds", str(jitter_sec))
    return 0


def set_output(name, value):
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output and os.path.exists(github_output):
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    print(f"Output: {name}={value}")


if __name__ == "__main__":
    sys.exit(main())

