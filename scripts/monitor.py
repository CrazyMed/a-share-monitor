import json
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

import akshare as ak

def is_trading_time_cn(now_cn: datetime) -> bool:
    # 周一=0 ... 周日=6
    if now_cn.weekday() >= 5:
        return False
    
    t = now_cn.time()
    morning_start = time(9, 30)
    morning_end = time(11, 30)
    afternoon_start = time(13, 0)
    afternoon_end = time(15, 0)
    
    return (morning_start <= t <= morning_end) or (afternoon_start <= t <= afternoon_end)

def load_config(path="config/config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_float(v, default=None):
    try:
        if v is None:
            return default
        if isinstance(v, str):
            v = v.replace("%", "").strip()
        return float(v)
    except Exception:
        return default

def main():
    cfg = load_config()
    tz = cfg.get("timezone", "Asia/Shanghai")
    now_cn = datetime.now(ZoneInfo(tz))
    
    # 非交易时段：写状态文件后退出
    if cfg.get("run_only_trading_hours", True) and (not is_trading_time_cn(now_cn)):
        os.makedirs("report", exist_ok=True)
        out = {
            "timestamp": now_cn.isoformat(),
            "status": "skipped_non_trading_hours",
            "items": []
        }
        with open("report/latest.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return
    
    # 拉取东方财富 A 股现货表
    df = ak.stock_zh_a_spot_em()
    
    rules = cfg.get("rules", {})
    vr_watch = float(rules.get("volume_ratio_watch", 1.5))
    vr_buy = float(rules.get("volume_ratio_buy", 2.0))
    ch_watch = float(rules.get("change_pct_watch", 2.0))
    ch_sell = float(rules.get("change_pct_sell", -3.0))
    
    results = []
    
    for s in cfg.get("symbols", []):
        name = s.get("name", "")
        code = str(s.get("code", "")).strip()
        market = (s.get("market", "") or "").upper()
        
        item = {
            "name": name,
            "code": code,
            "market": market,
            "status": "ok",
            "price": None,
            "change_pct": None,
            "volume": None,
            "volume_ratio": None,
            "signal": "HOLD",
            "reasons": []
        }
        
        try:
            if "代码" not in df.columns:
                item["status"] = "error"
                item["reasons"].append("行情表缺少"代码"列")
                results.append(item)
                continue
            
            rows = df[df["代码"].astype(str) == code]
            if rows.empty:
                item["status"] = "not_found"
                item["reasons"].append("未在行情表中找到该代码")
                results.append(item)
                continue
            
            row = rows.iloc[0]
            
            price = safe_float(row.get("最新价"))
            change_pct = safe_float(row.get("涨跌幅"))
            volume = safe_float(row.get("成交量"))
            volume_ratio = safe_float(row.get("量比"))
            
            item["price"] = price
            item["change_pct"] = change_pct
            item["volume"] = volume
            item["volume_ratio"] = volume_ratio
            
            # 硬规则输出信号
            # 1) 大跌预警
            if change_pct is not None and change_pct <= ch_sell:
                item["signal"] = "SELL"
                item["reasons"].append(f"涨跌幅≤{ch_sell}%")
            
            # 2) 放量 + 非负涨跌幅：买入
            if volume_ratio is not None and change_pct is not None:
                if volume_ratio >= vr_buy and change_pct >= 0:
                    item["signal"] = "BUY"
                    item["reasons"].append(f"量比≥{vr_buy} 且涨跌幅≥0")
                elif volume_ratio >= vr_watch or change_pct >= ch_watch:
                    if item["signal"] == "HOLD":
                        item["signal"] = "WATCH"
                    item["reasons"].append("触发关注条件（放量或上涨）")
            
            if not item["reasons"]:
                item["reasons"].append("未触发任何规则")
            
            results.append(item)
        
        except Exception as e:
            item["status"] = "error"
            item["reasons"].append(f"运行异常：{type(e).__name__}")
            results.append(item)
    
    os.makedirs("report", exist_ok=True)
    out = {
        "timestamp": now_cn.isoformat(),
        "status": "ran",
        "items": results
    }
    with open("report/latest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()