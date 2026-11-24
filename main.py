"""马来西亚 Shopee Affiliate → Telegram。Python 3.11+，从仓库根目录运行。"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

import requests

ENDPOINT = "https://open-api.affiliate.shopee.com.my/graphql"
MY = timezone(timedelta(hours=8))
WEEK = 7 * 86400
STATE = Path("posted_items.json")
# 包含短链和文案的临时包只在同一台 runner 的两个步骤之间传递。
PACKET = Path(os.environ.get("RUNNER_TEMP") or ".") / "shopee-my-packet.json"
CRONS = {"0 4 * * *": "1200", "0 12 * * *": "2000", "45 15 * * *": "2345"}
PRODUCTS = """
query Offers($page: Int!) {
  productOfferV2(page: $page, limit: 50, sortType: 5) {
    nodes { itemId productName productLink imageUrl sales ratingStar priceMin priceMax
            priceDiscountRate commissionRate sellerCommissionRate periodStartTime periodEndTime }
    pageInfo { hasNextPage }
  }
}"""
SHORT = """
mutation Link($url: String!, $tags: [String!]!) {
  generateShortLink(input: {originUrl: $url, subIds: $tags}) { shortLink }
}"""


def env(name, default=""):
    return os.environ.get(name, "").strip() or default


def required(name):
    value = env(name)
    if not value:
        raise ValueError(f"缺少环境变量 {name}")
    return value


def dump(path, obj):
    # 同目录替换，避免写到一半留下损坏的 JSON。
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def gql(query, variables, attempts=1):
    app, secret = required("SHOPEE_APP_ID"), required("SHOPEE_SECRET")
    # 只序列化一次。签名和 HTTP body 共用同一串 UTF-8 字节，包括空格和转义。
    body = json.dumps({"query": query, "variables": variables},
                      ensure_ascii=False, separators=(",", ":")).encode()
    for attempt in range(attempts):
        stamp = str(int(time.time()))
        sig = hashlib.sha256((app + stamp).encode() + body + secret.encode()).hexdigest()
        headers = {"Authorization": f"SHA256 Credential={app}, Timestamp={stamp}, Signature={sig}",
                   "Content-Type": "application/json"}
        try:
            r = requests.post(ENDPOINT, data=body, headers=headers, timeout=(5, 20),
                              allow_redirects=False)
        except requests.RequestException:
            if attempt + 1 == attempts:
                raise RuntimeError("Shopee 网络连接失败") from None
        else:
            if r.status_code == 200:
                result = r.json()
                if result.get("errors"):
                    # 只显示 API 错误，过滤密钥；不打印请求头、短链或完整响应。
                    msg = str(result["errors"][0].get("message", "GraphQL error"))
                    raise RuntimeError("Shopee: " + msg.replace(secret, "***").replace(app, "***")[:240])
                return result["data"]
            if r.status_code not in (429, 500, 502, 503, 504) or attempt + 1 == attempts:
                raise RuntimeError(f"Shopee HTTP {r.status_code}")
        time.sleep(2 ** attempt)


def number(value):
    # 无效数值保持为 -1，避免缺失的价格或佣金误入漏斗。
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else Decimal(-1)
    except InvalidOperation:
        return Decimal(-1)


def https(url):
    return isinstance(url, str) and url.startswith("https://") and bool(urlsplit(url).hostname)


def history(now):
    data = load(STATE)
    if not isinstance(data, dict):
        raise ValueError("posted_items.json 必须是 JSON 对象")
    for key, row in data.items():
        if not key.isdigit() or row["status"] not in ("pending", "sent") or type(row["ts"]) is not int:
            raise ValueError("防重记录损坏，请从 Git 历史恢复")
    # pending 额外保留十分钟，覆盖预留到实际发送之间的延迟。
    return {k: v for k, v in data.items()
            if now - v["ts"] < WEEK + (600 if v["status"] == "pending" else 0)}


def choose(state, now):
    sales_min = int(env("MIN_SALES", "500"))
    extra_min = number(env("MIN_SELLER_RATE", "0.05"))
    pages = int(env("MAX_PAGES", "3"))
    if sales_min < 1 or not 0 < extra_min <= 1 or not 1 <= pages <= 20:
        raise ValueError("检查 MIN_SALES、MIN_SELLER_RATE、MAX_PAGES")
    best, best_rank = None, None
    for page in range(1, pages + 1):
        offers = gql(PRODUCTS, {"page": page}, attempts=3)["productOfferV2"]
        for p in offers["nodes"]:
            item = str(p["itemId"])
            score, sold, extra, total = (number(p.get(k)) for k in
                                         ("ratingStar", "sales", "sellerCommissionRate", "commissionRate"))
            if not item.isdigit() or item in state or not (Decimal("4.8") <= score <= 5):
                continue
            if sold < sales_min or not (extra_min <= extra <= 1 and 0 < total <= 1):
                continue
            start, end = number(p.get("periodStartTime")), number(p.get("periodEndTime"))
            if start > now or 0 < end <= now:
                continue
            if not (p.get("productName") and https(p.get("productLink"))
                    and https(p.get("imageUrl")) and number(p.get("priceMin")) > 0):
                continue
            rank = (total, extra, sold, score, int(item))
            if best_rank is None or rank > best_rank:
                best, best_rank = p, rank
        if not offers["pageInfo"]["hasNextPage"]:
            break
    return best


# 正则识别商品场景。每个场景给出两种开头；模型仅能选择、组合经过审核的短句，
# 所以不会为商品杜撰折扣、医疗功效、库存或免运承诺。离线时直接组合第一组。
PATTERNS = [
    (r"bottle|tumbler|botol|水[杯瓶]", ("出门想自带饮料？", "通勤水杯怎么选？"),
     ("Nak bawa air dari rumah?", "Cari botol untuk perjalanan?")),
    (r"rack|storage|organis|organiz|rak\b|收纳", ("桌面总是不够放？", "想把杂物收好？"),
     ("Meja selalu penuh?", "Nak kemaskan barang di rumah?")),
    (r"charger|power.?bank|pengecas|充电", ("出门担心电量？", "在找充电配件？"),
     ("Selalu risau bateri lemah?", "Tengah cari aksesori pengecas?")),
]
GENERIC = (("想先比价再下单？", "正在挑同类商品？"),
           ("Nak banding harga dulu?", "Sedang cari pilihan dalam bajet?"))


def hook(title, bm):
    pair = next(((zh, ms) for regex, zh, ms in PATTERNS if re.search(regex, title, re.I)), GENERIC)
    intros = pair[int(bm)]
    endings = ("Semak pilihan ini.", "Bandingkan sebelum checkout.") if bm else (
        "看看这款 Shopee MY 选项。", "加入 shortlist，结账前比一比。")
    default = intros[0] + " " + endings[0]
    key = env("GEMINI_API_KEY")
    if not key:
        return default
    model = env("GEMINI_MODEL", "gemini-3.1-flash-lite")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        return default
    allowed = [a + " " + b for a in intros for b in endings]
    prompt = json.dumps({"task": "Return exactly one supplied caption best suited to the product.",
                         "product": title, "captions": allowed}, ensure_ascii=False)
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key}, timeout=(4, 12), allow_redirects=False,
            json={"contents": [{"parts": [{"text": prompt}]}]})
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        choice = next(part["text"].strip() for part in reversed(parts) if part.get("text"))
        if choice in allowed:
            return choice
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError, StopIteration):
        pass
    print("Gemini 未返回可用短句，本次使用本地文案。")
    return default


def caption(p, link):
    lang = env("COPY_LANG", "zh-en")
    if lang not in ("zh-en", "ms"):
        raise ValueError("COPY_LANG 可填 zh-en 或 ms")
    bm = lang == "ms"
    title = " ".join(p["productName"].split())[:150]
    low, high, pct = (number(p.get(k)) for k in ("priceMin", "priceMax", "priceDiscountRate"))
    lines = [hook(title, bm), title, f"★ {p['ratingStar']}  ·  {p['sales']} " + ("terjual" if bm else "已售")]
    lines.append(("Harga dari " if bm else "现价低至 ") + f"RM{low:.2f}")
    # 折扣率可能四舍五入。仅单一售价时反推，并在两个金额旁明确标注估算。
    if low == high and 0 < pct < 100:
        original = low / (1 - pct / 100)
        lines.append((f"Anggaran asal RM{original:.2f} · jimat kira-kira RM{original-low:.2f}"
                      if bm else f"估算原价 RM{original:.2f} · 约省 RM{original-low:.2f}"))
    lines += [("Semak baucar & kelayakan penghantaran percuma di checkout." if bm else
               "结账前查看 voucher 和免运资格，以所选规格实付价为准。"),
              ("Pautan affiliate · saya mungkin terima komisen." if bm else
               "Affiliate 推广链接 · 成交后我可能获得佣金。"), link]
    result = "\n".join(lines)
    if len(result.encode("utf-16-le")) // 2 > 1024:
        raise ValueError("Telegram 图片说明过长")
    return result


def prepare():
    required("TELEGRAM_BOT_TOKEN")
    required("TELEGRAM_CHAT_ID")
    PACKET.unlink(missing_ok=True)
    now = int(time.time())
    state = history(now)
    p = choose(state, now)
    if p is None:
        print("没有符合门槛且可推送的商品，本次发送 0 条。")
        return False
    local = datetime.fromtimestamp(now, MY)
    cron = env("TRIGGER_CRON")
    slot = CRONS[cron] if cron else "manual"
    if cron:
        # 跨午夜排队时，使用最近一个已经到达的计划时段日期。
        scheduled = local.replace(hour=int(slot[:2]), minute=int(slot[2:]), second=0, microsecond=0)
        if scheduled > local:
            scheduled -= timedelta(days=1)
    else:
        scheduled = local
    tags = [scheduled.strftime("%Y%m%d"), slot, "telegram"]
    link = gql(SHORT, {"url": p["productLink"], "tags": tags})["generateShortLink"]["shortLink"]
    if not https(link):
        raise ValueError("Shopee 未返回有效专属短链")
    item = str(p["itemId"])
    packet = {"item": item, "photo": p["imageUrl"], "caption": caption(p, link)}
    stamp = int(time.time())
    state[item] = {"ts": stamp, "status": "pending", "subIds": tags}
    dump(PACKET, packet)
    dump(STATE, state)
    print(f"已预留商品 {item}，SubIDs {' / '.join(tags)}")
    return True


def send():
    packet = load(PACKET)
    state = load(STATE)
    item = packet["item"]
    row = state[item]
    if row["status"] != "pending" or not 0 <= time.time() - row["ts"] < 300:
        raise RuntimeError("预留已过期或已发送，停止投递")
    # Telegram 没有客户端幂等键。超时或 5xx 时保留预留，不自动重试或改发文字。
    token = required("TELEGRAM_BOT_TOKEN")
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                          json={"chat_id": required("TELEGRAM_CHAT_ID"), "photo": packet["photo"],
                                "caption": packet["caption"]}, timeout=(5, 30), allow_redirects=False)
        result = r.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError("Telegram 送达结果未知，请查看目标频道；预留已保留。") from None
    if r.status_code == 200 and result.get("ok") and result.get("result", {}).get("message_id"):
        row.update(status="sent", ts=int(time.time()), message_id=result["result"]["message_id"])
        dump(STATE, state)
        print(f"已确认发送商品 {item}，message_id={row['message_id']}")
        return
    if r.status_code in (400, 401, 403, 404, 429) and result.get("ok") is False:
        # 明确拒收才释放；工作流即使这一步失败也会提交释放后的记录。
        del state[item]
        dump(STATE, state)
        reason = str(result.get("description", "")).replace(token, "***")
        raise RuntimeError(f"Telegram 拒收 {r.status_code}: {reason[:180]}")
    raise RuntimeError(f"Telegram 结果未知（HTTP {r.status_code}），保留预留。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "send", "run"], default="run", nargs="?")
    phase = parser.parse_args().phase
    if phase == "send":
        send()
        return
    ready = prepare()
    if output := env("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as f:
            print(f"ready={str(ready).lower()}", file=f)
    if phase == "run" and ready:
        send()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, TypeError, KeyError, IndexError) as exc:
        sys.exit(f"运行失败：{exc}")
