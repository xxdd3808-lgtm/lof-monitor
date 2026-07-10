#!/usr/bin/env python3
"""华宝油气 LOF (162411) 折溢价监控 + 通知推送

触发条件：
1. 折价超过阈值（默认 5%）-> 折价套利机会提醒
2. 溢价超过阈值（默认 8%）-> 溢价风险提醒（已持有者可考虑卖出）
3. 申购状态变化（暂停->开放）-> 溢价套利窗口打开
4. 赎回状态变化（开放->暂停）-> 折价套利窗口关闭

去重：每个信号每天最多推送 1 次（state.json 记录）
"""

import json
import os
from datetime import datetime

import akshare as ak
import requests

# ---------- 配置 ----------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
STATE_FILE = os.path.join(SCRIPT_DIR, "state.json")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")

TODAY = datetime.now().strftime("%Y-%m-%d")


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_market_data(code="162411"):
    """获取场内价、净值、折溢价、申购赎回状态"""
    result = {
        "price": None, "nav": None, "nav_date": None,
        "premium": None, "buy_status": "未知", "redeem_status": "未知",
        "error": None,
    }

    # 净值
    try:
        nav_df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        latest = nav_df.iloc[-1]
        result["nav"] = float(latest["单位净值"])
        result["nav_date"] = str(latest["净值日期"])[:10]
    except Exception as e:
        result["error"] = f"净值获取失败: {e}"
        return result

    # 场内价（用 akshare LOF 实时，避免 yfinance 在 GitHub Actions 不稳）
    try:
        spot = ak.fund_lof_spot_em()
        match = spot[spot["代码"].astype(str).str.strip() == code]
        if not match.empty:
            result["price"] = float(match.iloc[0]["最新价"])
    except Exception as e:
        # fallback: 东财行情接口
        try:
            url = f"http://push2.eastmoney.com/api/qt/stock/get"
            params = {"secid": f"0.{code}", "fields": "f43"}
            r = requests.get(url, params=params, timeout=10)
            d = r.json().get("data", {})
            if d and d.get("f43"):
                result["price"] = float(d["f43"]) / 1000  # 东财价格需 /1000
        except Exception:
            pass

    # 申购赎回状态
    try:
        url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNNBasicInformation"
        params = {"FundCode": code, "deviceid": "Wap", "plat": "Wap",
                  "product": "EFund", "version": "2.0.0"}
        r = requests.get(url, params=params, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        info = r.json().get("Expansion", {})
        bgro = info.get("FundBGRO", "")
        rgro = info.get("FundRGRO", "")
        if bgro:
            result["buy_status"] = "开放申购" if "正常" in str(bgro) else str(bgro)
        if rgro:
            result["redeem_status"] = "开放赎回" if "正常" in str(rgro) else str(rgro)
    except Exception:
        pass

    # 折溢价（用 settled 口径：场内价 / 最新净值 - 1）
    if result["price"] and result["nav"] and result["nav"] > 0:
        result["premium"] = result["price"] / result["nav"] - 1

    return result


def send_pushplus(title, content):
    """PushPlus 微信推送（HTTPS + 1 次重试）"""
    if not PUSHPLUS_TOKEN:
        print("[WARN] PUSHPLUS_TOKEN 未设置，跳过推送")
        print(f"--- {title} ---\n{content}\n---")
        return False

    url = "https://www.pushplus.plus/send"
    payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "txt"}

    for attempt in range(2):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            data = resp.json()
            ok = data.get("code") == 200
            print(f"[PUSH] {title} -> {'OK' if ok else data}")
            if ok or data.get("code") in (903, 904):  # 903/904 = token 失效，不重试
                return ok
        except Exception as e:
            print(f"[WARN] 推送第 {attempt + 1} 次失败: {e}")
            if attempt == 0:
                import time
                time.sleep(2)
    return False


def already_notified(state, signal_key):
    """检查今天是否已推送过该信号"""
    entry = state.get(signal_key, {})
    return entry.get("date") == TODAY


def mark_notified(state, signal_key, extra=None):
    state[signal_key] = {"date": TODAY, **(extra or {})}


def main():
    config = load_json(CONFIG_FILE, {"monitors": []})
    state = load_json(STATE_FILE, {})
    monitors = config.get("monitors", [])

    if not monitors:
        print("config.json 中无监控条目")
        return

    alerts = []

    for m in monitors:
        code = m["code"]
        name = m["name"]
        discount_threshold = m.get("discount_threshold", 0.05)  # 折价提醒阈值
        premium_threshold = m.get("premium_threshold", 0.08)    # 溢价提醒阈值

        print(f"[CHECK] {name}({code}) ...")
        data = get_market_data(code)

        if data["error"]:
            print(f"  数据异常: {data['error']}")
            alerts.append(f"⚠️ {name}({code}) 数据异常: {data['error']}")
            continue

        if data["premium"] is None:
            print(f"  折溢价计算失败（price={data['price']}, nav={data['nav']}）")
            continue

        premium = data["premium"]
        premium_str = f"{premium*100:+.2f}%"
        print(f"  折溢价: {premium_str} | 申购: {data['buy_status']} | 赎回: {data['redeem_status']}")

        # 信号1: 折价超阈值
        if premium <= -discount_threshold:
            key = f"{code}_discount"
            if not already_notified(state, key):
                breakeven_us = (1 - (1 + 0.015) * (1 + premium)) / 0.94
                alerts.append(
                    f"🟢 {name}({code}) 折价 {premium_str}\n"
                    f"  场内价: ¥{data['price']:.4f} | 净值({data['nav_date']}): ¥{data['nav']:.4f}\n"
                    f"  赎回: {data['redeem_status']} | T+0赎回盈亏平衡美股跌幅: {breakeven_us*100:.2f}%\n"
                    f"  → 买入+赎回套利窗口（注意美股当晚波动风险）"
                )
                mark_notified(state, key, {"premium": premium_str})

        # 信号2: 溢价超阈值（已持有者卖出信号）
        if premium >= premium_threshold:
            key = f"{code}_premium"
            if not already_notified(state, key):
                alerts.append(
                    f"🔴 {name}({code}) 溢价 {premium_str}\n"
                    f"  场内价: ¥{data['price']:.4f} | 净值({data['nav_date']}): ¥{data['nav']:.4f}\n"
                    f"  申购: {data['buy_status']}\n"
                    f"  → 已持有者可考虑场内卖出（申购套利通道基本堵死）"
                )
                mark_notified(state, key, {"premium": premium_str})

        # 信号3: 申购状态变化（暂停->开放）
        buy_key = f"{code}_buy_status"
        prev_buy = state.get(buy_key, {}).get("status", "")
        curr_buy = data["buy_status"]
        if prev_buy and prev_buy != curr_buy and "开放" in curr_buy:
            if not already_notified(state, f"{code}_buy_open"):
                alerts.append(
                    f"📢 {name}({code}) 申购已恢复！\n"
                    f"  {prev_buy} → {curr_buy}\n"
                    f"  → 溢价套利窗口打开（如当前有溢价）"
                )
                mark_notified(state, f"{code}_buy_open", {"from": prev_buy, "to": curr_buy})
        if curr_buy != "未知":
            state[buy_key] = {"status": curr_buy, "date": TODAY}

        # 信号4: 赎回状态变化（开放->暂停）
        redeem_key = f"{code}_redeem_status"
        prev_redeem = state.get(redeem_key, {}).get("status", "")
        curr_redeem = data["redeem_status"]
        if prev_redeem and prev_redeem != curr_redeem and "暂停" in curr_redeem:
            if not already_notified(state, f"{code}_redeem_close"):
                alerts.append(
                    f"⚠️ {name}({code}) 赎回已暂停！\n"
                    f"  {prev_redeem} → {curr_redeem}\n"
                    f"  → 折价套利窗口关闭（买入后无法赎回）"
                )
                mark_notified(state, f"{code}_redeem_close", {"from": prev_redeem, "to": curr_redeem})
        if curr_redeem != "未知":
            state[redeem_key] = {"status": curr_redeem, "date": TODAY}

    # 推送
    if alerts:
        title = f"🔔 LOF 折溢价提醒（{len(alerts)} 条）"
        body = "\n\n".join(alerts)
        body += f"\n\n---\n检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        print(f"\n[NOTIFY] 推送 {len(alerts)} 条提醒...")
        send_pushplus(title, body)
    else:
        print(f"\n[INFO] 无触发信号，不推送")

    save_json(STATE_FILE, state)
    print("[DONE] state.json 已保存")


if __name__ == "__main__":
    main()
