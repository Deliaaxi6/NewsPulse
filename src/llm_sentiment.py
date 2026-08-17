"""LLM 新闻情绪分类（Phase 3）：DeepSeek API 全量二次分类（覆盖关键词规则）。

- 配置：DEEPSEEK_API_KEY 环境变量（未配置 → 跳过，降级关键词规则）；模型 deepseek-v4-flash
  非思考模式（官方价：输入 ¥1/百万 tokens、输出 ¥2/百万 tokens，2026-08-17 起峰谷定价）
- 幂等计费：按内容 hash 缓存 data/llm_cache_{date}.json，同日重跑不重复请求
- 降级：单批失败 → 该批保留关键词规则结果；连续 MAX_FAIL_BATCHES 批失败 → 熔断本次运行
- 输出：{"label": "bull|bear|neutral", "confidence": 0~1}，strict JSON
"""
import hashlib
import json

import requests

from config import (DATA_DIR, DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_API)
import alert

CACHE_PREFIX = "llm_cache"
BATCH = 15
MAX_FAIL_BATCHES = 3
PROMPT = (
    "你是A股新闻情绪分析师。对每条新闻给出标签：bull(利好)/bear(利空)/neutral(中性)。\n"
    "严格输出 JSON 对象 {\"results\": [{\"label\": \"bull\", \"confidence\": 0.8}, ...]}，"
    "与输入新闻一一对应，不要输出任何其他内容。")


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _cache_path(date_str: str):
    return DATA_DIR / f"{CACHE_PREFIX}_{date_str}.json"


def _load_cache(date_str: str) -> dict:
    p = _cache_path(date_str)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_cache(date_str: str, cache: dict):
    try:
        _cache_path(date_str).write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[warn] LLM 缓存写入失败: {e}")


def _call_api(batch_texts: list) -> list | None:
    """单批调用 DeepSeek chat/completions，返回与输入等长的 label 列表；失败返回 None。"""
    url = f"{DEEPSEEK_API}/chat/completions"
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": json.dumps(batch_texts, ensure_ascii=False)},
        ],
        "temperature": 0,
        # 实测调参：v4-flash 默认思考模式，reasoning.enabled=false 不生效；
        # 需 max_tokens 4096 且 reasoning_effort=low（比默认省 ~35% tokens），
        # 否则思考耗尽 token 时 content 为空串导致 JSON 解析失败。
        # 配合 response_format=json_object 保证严格 JSON 输出。
        "max_tokens": 4096,
        "reasoning_effort": "low",
        "response_format": {"type": "json_object"},
    }
    r = requests.post(url, headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                      json=payload, timeout=60)
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    items = data if isinstance(data, list) else _unwrap_obj(data)
    labels = [x["label"] for x in items]
    if len(labels) != len(batch_texts):
        raise ValueError(f"label 数量不匹配: {len(labels)} vs {len(batch_texts)}")
    return labels


def _unwrap_obj(data: dict) -> list:
    """response_format=json_object 时 LLM 可能用对象包装数组，兼容常见 key。"""
    for key in ("results", "data", "news", "items"):
        v = data.get(key)
        if isinstance(v, list):
            return v
    raise ValueError(f"LLM 返回对象无法解析: {str(data)[:120]}")


def classify_batch(rows: list, date_str: str | None = None) -> dict:
    """rows: [{"text": ...}]（与 DataFrame 行序一致）；返回 {行下标: label}。
    未配置 key / 全部失败 → {}（调用方保留关键词规则结果）。"""
    if not DEEPSEEK_API_KEY:
        print("[info] DeepSeek 未配置（缺 NEWSPULSE_DS_KEY），跳过 LLM 分类，用关键词规则")
        return {}
    cache = _load_cache(date_str or "")
    out = {}
    pending = []          # [(text, idx)]
    for idx, row in enumerate(rows):
        text = str(row.get("text", ""))
        h = _content_hash(text)
        if h in cache:
            out[idx] = cache[h]
        else:
            pending.append((text, idx))
    if not pending:
        print(f"[ok] LLM 分类全部命中缓存（{len(out)} 条），未调用 API")
        return out
    fail_batches = 0
    done = 0
    alerted_fail = False
    for start in range(0, len(pending), BATCH):
        chunk = pending[start:start + BATCH]
        try:
            labels = _call_api([t for t, _ in chunk])
            fail_batches = 0
            for (text, idx), label in zip(chunk, labels):
                if label in ("bull", "bear", "neutral"):
                    out[idx] = label
                    cache[_content_hash(text)] = label
            done += len(chunk)
        except Exception as e:
            fail_batches += 1
            print(f"[warn] LLM 分类批失败({fail_batches}/{MAX_FAIL_BATCHES}): {e}")
            if not alerted_fail:
                alerted_fail = True
                alert.notify("LLM 分类降级",
                             f"第{start // BATCH + 1}批（{len(chunk)}条）分类失败: {e}，"
                             "该批降级关键词规则")
            if fail_batches >= MAX_FAIL_BATCHES:
                print("[warn] LLM 连续失败达上限，本次熔断，剩余用关键词规则")
                alert.notify("LLM 分类熔断",
                             f"连续 {MAX_FAIL_BATCHES} 批失败，剩余 "
                             f"{len(pending) - start - len(chunk)} 条降级关键词规则")
                break
    _save_cache(date_str or "", cache)
    print(f"[ok] LLM 分类 {done}/{len(pending)} 条新增，"
          f"缓存命中 {len(out) - done} 条（共 {len(out)} 条）")
    return out