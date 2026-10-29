#!/usr/bin/env python3
"""用 Cloudflare 决策模型（System One API）按评分卡给图片出判决。

用法:
    python score_clef.py <图片> [<图片> ...] [选项]

候选可以是图片，也可以是文字（.txt/.md 文件，--split 时按空行切成多段）。
文字放进 state，不传 images。同一次运行不混用图片和文字。

决策模型不做自由生成。输入 = state（要判决的内容）+ questions（类型化问题），
输出 = 每个问题各选项的概率。三类问题各有分工：
    noul   门槛：返回"是"的概率，用来卡硬性合格线（有无水印、是否切题）。
    score  评分：返回概率加权的等级下标，本脚本归一到 0-10 后加权汇总。
    choice 归类/择优：返回选中项、逐项概率与 confidence。

三条调用路径，因为一次请求只产出一份答案：
    逐图判决 —— 每张图单独请求，拿到该图自己的分数（默认，张数不限，逐张串行）。
    一次择优 —— --compare 把最多 4 张图放进一个请求，只问 mode=compare 的 choice 题。
    海选择优 —— --pick 先逐图打分排名，再取前几名放一个请求决赛，选出唯一冠军。

分数归一化、权重汇总、门槛制裁、评级带全部由脚本确定性地算，模型只交概率。

后端配置不进仓库。查找顺序: --config > CLEF_CONFIG > ~/.clef/config.json
                          > <skill>/config.local.json > 环境变量
环境变量: CLEF_BASE_URL / CLEF_API_KEY / CLEF_MODEL

评分卡格式见 references/scorecard-format.md，接口实测约束见 references/api.md。

退出码: 0=全部成功  1=有图片判决失败  2=用法或配置错误
"""
import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

# Windows 控制台默认 GBK，中文输出会乱码；统一按 UTF-8 写。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")
# 网关在 Cloudflare 后面，默认 UA(Python-urllib) 会被当机器人拦：403 + "error code: 1010"。
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
FALLBACK_UA = "curl/8.6.0"

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
DEFAULT_SCORECARD = os.path.join(SKILL_DIR, "assets", "scorecards", "generic_quality.json")
PICK_SCORECARD = os.path.join(SKILL_DIR, "assets", "scorecards", "eye_catching.json")

DEFAULT_BASE_URL = "https://emrank.tech"
DEFAULT_MODEL = "cloudflare/clef-flash"
PATH_SUFFIX = "/v1/systemone"

# 官方硬限制：单请求最多 4 张图，单张 4 MiB / 16 百万像素，解码合计 8 MiB，请求体 13 MiB。
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 16_000_000
TEXT_EXT = {".txt", ".md"}
# 文字候选没有图片张数限制，决赛人数放宽；太多会让 state 过长、模型难以比较
MAX_TEXT_FINALISTS = 10
# 决赛 confidence 低于此值视为没有判断力；实测几轮无效决赛都在 0.01-0.05
MIN_FINAL_CONFIDENCE = 0.2
TYPE_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
QID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class ConfigError(Exception):
    pass


def ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def load_config(explicit):
    cfg = {"base_url": DEFAULT_BASE_URL, "model": DEFAULT_MODEL, "__source": "defaults"}
    candidates = [explicit, os.environ.get("CLEF_CONFIG"),
                  os.path.expanduser("~/.clef/config.json"),
                  os.path.join(SKILL_DIR, "config.local.json")]
    for path in filter(None, candidates):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                cfg.update({k: v for k, v in json.load(f).items() if v})
            cfg["__source"] = os.path.normpath(path)
            break
    for key, env in (("base_url", "CLEF_BASE_URL"), ("api_key", "CLEF_API_KEY"), ("model", "CLEF_MODEL")):
        if os.environ.get(env):
            cfg[key] = os.environ[env]
            cfg["__source"] = "env"
    if not cfg.get("api_key"):
        raise ConfigError("缺少 API key：设环境变量 CLEF_API_KEY，或写 " +
                          os.path.normpath(os.path.expanduser("~/.clef/config.json")) +
                          ' 形如 {"base_url": "...", "api_key": "...", "model": "cloudflare/clef-flash"}')
    return cfg


def http_run(cfg, payload, timeout=120):
    url = cfg["base_url"].rstrip("/") + PATH_SUFFIX
    data = json.dumps(payload).encode()
    last = None
    for attempt, ua in ((1, BROWSER_UA), (2, FALLBACK_UA), (3, BROWSER_UA)):
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": "Bearer " + cfg["api_key"],
            "Content-Type": "application/json",
            "User-Agent": ua,
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:400]
            last = f"HTTP {e.code}: {body}"
            if e.code == 403 and "1010" in body:
                last += " [Cloudflare 按 UA 拦截，已换 UA 重试]"
                time.sleep(1.0)
                continue
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2.0 * attempt)
                continue
            raise RuntimeError(last)
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络错误: {e.reason}")
    raise RuntimeError(last)

# ---- 评分卡：加载与校验 ----

def load_scorecard(path):
    """校验评分卡结构，把接口硬限制前移到加载阶段，避免拿 4xx 才知道写错了。"""
    if not os.path.isfile(path):
        raise ConfigError(f"评分卡不存在: {path}")
    with open(path, encoding="utf-8") as f:
        card = json.load(f)
    questions = card.get("questions")
    if not isinstance(questions, dict) or not 1 <= len(questions) <= 64:
        raise ConfigError(f"评分卡 {path}: questions 需要是 1-64 项的对象")
    for qid, q in questions.items():
        if not QID_RE.match(str(qid)):
            raise ConfigError(f"评分卡 {path}: 问题 id {qid!r} 非法（字母数字 . _ -，<=100 字符）")
        qtype = q.get("type")
        if qtype not in ("noul", "choice", "score"):
            raise ConfigError(f"评分卡 {path}: {qid} 的 type={qtype!r} 非法（noul|choice|score）")
        if not (q.get("instructions") or "").strip():
            raise ConfigError(f"评分卡 {path}: {qid} 缺 instructions")
        if q.get("mode") == "compare":
            if qtype != "choice":
                raise ConfigError(f"评分卡 {path}: {qid} 标了 mode=compare 但 type 不是 choice")
            if not isinstance(q.get("criteria"), dict) or len(q.get("criteria")) < 1:
                raise ConfigError(f"评分卡 {path}: compare 题 {qid} 的 criteria 需要是选项字典")
            continue
        if qtype == "score":
            levels = q.get("criteria")
            if not isinstance(levels, list) or not 2 <= len(levels) <= 10:
                raise ConfigError(f"评分卡 {path}: {qid} 的 criteria 需要是 2-10 项数组（最低档在前）")
        elif qtype == "choice":
            if not isinstance(q.get("criteria"), dict) or len(q["criteria"]) < 2:
                raise ConfigError(f"评分卡 {path}: {qid} 的 criteria 需要是至少 2 项的字典")
    for qid in card.get("weights", {}):
        if qid not in questions:
            raise ConfigError(f"评分卡 {path}: weights 引用了不存在的问题 {qid}")
        if questions[qid]["type"] != "score":
            raise ConfigError(f"评分卡 {path}: weights 里的 {qid} 不是 score 题，无法参与加权")
    return card


def build_questions(card, mode):
    """转成 API questions。mode=score 跳过 compare 题，mode=compare 只留 compare 题。"""
    out = {}
    for qid, q in card["questions"].items():
        is_compare = q.get("mode") == "compare"
        if mode == "compare":
            if not is_compare:
                continue
        elif is_compare:
            continue
        entry = {"type": q["type"], "instructions": q["instructions"]}
        if q["type"] in ("choice", "score") and q.get("criteria") is not None:
            entry["criteria"] = q["criteria"]
        elif q["type"] == "noul" and q.get("criteria"):
            entry["criteria"] = q["criteria"]
        out[qid] = entry
    if not out:
        raise ConfigError("这次请求没有任何可问的问题（compare 模式需要至少一个 mode=compare 的 choice 题）")
    return out


# ---- 图片读取 ----

def read_image(path):
    """读成官方要求的 data URL，并前置挡住格式/尺寸违规。"""
    if not os.path.isfile(path):
        raise ConfigError(f"图片不存在: {path}")
    ext = os.path.splitext(path)[1].lower()
    media_type = TYPE_BY_EXT.get(ext)
    if media_type is None:
        raise ConfigError(f"不支持的格式 {ext or '(无扩展名)'}：决策模型只收 "
                          f"{', '.join(sorted(TYPE_BY_EXT))}；GIF/BMP/TIFF 请先转 PNG")
    if os.path.getsize(path) > MAX_IMAGE_BYTES:
        raise ConfigError(f"文件超过单张 {MAX_IMAGE_BYTES // 1024 // 1024} MiB 上限: {path}")
    pixels = image_pixels(path)
    if pixels and pixels > MAX_PIXELS:
        raise ConfigError(f"约 {pixels / 1e6:.1f} 百万像素，超过 16 百万像素上限，先缩小: {path}")
    with open(path, "rb") as f:
        return "data:" + media_type + ";base64," + base64.b64encode(f.read()).decode()


def image_pixels(path):
    """能读到尺寸就校验；读不到（没装 Pillow）就跳过，不做强依赖。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            return im.size[0] * im.size[1]
    except Exception:
        return None

# ---- 答案解释 ----

def normalize_score(answer):
    """score 的 score 是概率加权的等级下标（0 起），按等级数归一到 0-10。"""
    legend = answer.get("legend") or {}
    levels = len(legend)
    if levels < 2:
        raise ValueError("score 答案缺 legend，无法确定等级数")
    raw = float(answer["score"])
    if not 0 <= raw <= levels - 1:
        raise ValueError(f"score={raw} 超出等级范围 0-{levels - 1}")
    return round(raw / (levels - 1) * 10.0, 2), raw, levels


def interpret(card, answers):
    """把原始答案拆成门槛、维度、加权总分。缺题或类型不符都算失败，不静默补值。"""
    gates, dims = [], {}
    weight_sum = weighted = 0.0
    for qid, q in card["questions"].items():
        if q.get("mode") == "compare":
            continue
        ans = answers.get(qid)
        if not isinstance(ans, dict):
            raise ValueError(f"响应缺问题 {qid} 的答案")
        if ans.get("type") != q["type"]:
            raise ValueError(f"问题 {qid} 返回类型 {ans.get('type')!r}，请求的是 {q['type']!r}")
        conf = round(float(ans.get("confidence", 0.0)), 4)
        if q["type"] == "noul":
            p_yes = float(ans["noul"])
            threshold = float(q.get("pass_if_yes_at_least", 0.5))
            gates.append({
                "id": qid,
                "question": q["instructions"],
                "p_yes": round(p_yes, 4),
                "threshold": threshold,
                "passed": p_yes >= threshold,
            })
            continue
        if q["type"] == "score":
            norm, raw, levels = normalize_score(ans)
            entry = {"kind": "score", "score_0_10": norm, "raw_level": round(raw, 3),
                     "levels": levels, "confidence": conf,
                     "probabilities": ans.get("probabilities")}
            w = float(card.get("weights", {}).get(qid, 1.0))
            weight_sum += w
            weighted += w * norm
        else:
            entry = {"kind": "choice", "choice": ans.get("choice"), "confidence": conf,
                     "probabilities": ans.get("probabilities")}
        entry["question"] = q["instructions"]
        dims[qid] = entry
    return gates, dims, (round(weighted / weight_sum, 2) if weight_sum else None)


def interpret_compare(card, answers):
    """比较模式：只解读 mode=compare 的 choice 题。"""
    out = {}
    for qid, q in card["questions"].items():
        if q.get("mode") != "compare":
            continue
        ans = answers.get(qid)
        if not isinstance(ans, dict) or ans.get("type") != "choice":
            raise ValueError(f"响应缺比较题 {qid} 的答案")
        out[qid] = {"question": q["instructions"], "choice": ans.get("choice"),
                    "confidence": round(float(ans.get("confidence", 0.0)), 4),
                    "probabilities": ans.get("probabilities")}
    if not out:
        raise ValueError("响应里没有任何比较题的答案")
    return out


def grade_of(score, card):
    if score is None:
        return None
    for band in card.get("grade_bands", []):
        if score >= float(band["min"]):
            return band["grade"]
    return None


def apply_gate_policy(card, gates, score):
    """gate_policy=report 只报告；=cap 则门槛不过时把总分压到 cap_score。"""
    blocked = [g["id"] for g in gates if not g["passed"]]
    if not blocked or score is None:
        return score, False
    if card.get("gate_policy", "report") != "cap":
        return score, False
    cap = float(card.get("cap_score", 4.0))
    return min(score, cap), score > cap


# ---- 执行 ----

def judge_one(cfg, card, cand, args):
    """单项判决：一个候选一次请求，拿到只属于它的分数。"""
    prompt_state = card.get("purpose", "对这个候选做出类型化判决")
    if args.context:
        prompt_state += f"\n补充背景：{args.context}"
    payload = {"model": cfg["model"], "questions": build_questions(card, "score")}
    if cand["kind"] == "image":
        prompt_state += f"\n待判决文件：{os.path.basename(cand['path'])}"
        payload["images"] = [read_image(cand["path"])]
    else:
        prompt_state += f"\n待评价文字：\n{cand['text']}"
    payload["state"] = prompt_state
    if args.dry_run:
        return {"dry_run_payload": redact(payload)}, None, None
    last = None
    for attempt in range(args.retries + 1):
        try:
            result = http_run(cfg, payload, timeout=args.timeout)
            gates, dims, score = interpret(card, result.get("answers") or {})
            final_score, capped = apply_gate_policy(card, gates, score)
            verdict = {
                "file": cand["item"],
                "gates": gates,
                "dimensions": dims,
                "weighted_score": final_score,
                "raw_weighted_score": score,
                "capped_by_gate": capped,
                "gate_passed": all(g["passed"] for g in gates),
                "grade": grade_of(final_score, card),
            }
            if cand["kind"] == "text":
                verdict["text"] = cand["text"]
            return verdict, result.get("usage"), None
        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            last = str(e)
            if attempt < args.retries:
                time.sleep(2.0 * (attempt + 1))
    return None, None, last


def judge_compare(cfg, card, cands, args):
    """择优：多个候选放一个请求，问"哪一个最好"，返回选项概率。图片最多 4 张。"""
    is_image = cands[0]["kind"] == "image"
    ids = [f"{'image' if is_image else 'text'}{i+1}" for i in range(len(cands))]
    state = card.get("purpose", "比较这些候选并选出最好的一个")
    if args.context:
        state += f"\n补充背景：{args.context}"
    if is_image:
        state += "\n图片按请求顺序编号：\n" + "\n".join(
            f"{ids[i]} = {os.path.basename(c['path'])}" for i, c in enumerate(cands))
    else:
        state += "\n候选文字：\n" + "\n\n".join(
            f"【{ids[i]}】\n{c['text']}" for i, c in enumerate(cands))
    questions = build_questions(card, "compare")
    # compare 题需要在选项里列出目标图片 id
    for qid, entry in questions.items():
        crit = card["questions"][qid].get("criteria") or {}
        template = crit.get("<option>") or crit.get("default") or "Candidate {id}."
        entry["criteria"] = {i: template.replace("{id}", i) for i in ids}
    payload = {"model": cfg["model"], "state": state, "questions": questions}
    if is_image:
        payload["images"] = [read_image(c["path"]) for c in cands]
    if args.dry_run:
        return {"dry_run_payload": redact(payload)}, None, None
    last = None
    for attempt in range(args.retries + 1):
        try:
            result = http_run(cfg, payload, timeout=args.timeout)
            comparison = interpret_compare(card, result.get("answers") or {})
            winner = None
            for entry in comparison.values():
                if entry["choice"] in ids:
                    winner = {"id": entry["choice"], "index": ids.index(entry["choice"]),
                              "question": entry["question"],
                              "confidence": entry["confidence"]}
                    break
            return {
                "files": [{"id": ids[i], "path": c["item"]} for i, c in enumerate(cands)],
                "comparison": comparison,
                "winner": winner,
            }, result.get("usage"), None
        except (ValueError, KeyError, TypeError, RuntimeError) as e:
            last = str(e)
            if attempt < args.retries:
                time.sleep(2.0 * (attempt + 1))
    return None, None, last


def expand_inputs(items, split):
    """展开成候选列表。目录取其中（不递归）的图片和文字文件，按文件名排序。
    文字文件整篇算一个候选；split=True 时按空行切段，每段一个候选，item 记为 "路径#段号"。"""
    files = []
    for item in items:
        if os.path.isdir(item):
            files.extend(os.path.join(item, n) for n in sorted(os.listdir(item))
                         if os.path.splitext(n)[1].lower() in TYPE_BY_EXT.keys() | TEXT_EXT)
        else:
            files.append(item)
    cands = []
    for path in map(os.path.abspath, files):
        if os.path.splitext(path)[1].lower() not in TEXT_EXT:
            cands.append({"kind": "image", "item": path, "path": path})
            continue
        if not os.path.isfile(path):
            raise ConfigError(f"文件不存在: {path}")
        with open(path, encoding="utf-8-sig") as f:
            content = f.read().replace("\r\n", "\n").strip()
        parts = [x.strip() for x in re.split(r"\n\s*\n", content)] if split else [content]
        for n, part in enumerate((x for x in parts if x), 1):
            item = f"{path}#{n}" if split else path
            cands.append({"kind": "text", "item": item, "path": path, "text": part})
    if len({c["kind"] for c in cands}) > 1:
        raise ConfigError("同一次运行不能混用图片和文字候选")
    return cands


def redact(payload):
    """--dry-run 时把 base64 换成占位符，避免把几 MB 图片糊到终端。"""
    out = dict(payload)
    out["images"] = [f"<data url, {len(u)} chars>" for u in payload.get("images", [])]
    return out


def main():
    p = argparse.ArgumentParser(
        prog="score_clef.py",
        description="用 Cloudflare clef-flash 决策模型按评分卡给图片出判决（输出 JSON）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="评分卡格式见 references/scorecard-format.md；\n"
               "接口实测约束见 references/api.md。",
    )
    p.add_argument("images", nargs="+",
                   help="图片（PNG/JPEG/WebP）、文字文件（.txt/.md）或目录（不递归）；同次不混用")
    p.add_argument("--scorecard", help="评分卡 JSON 路径；默认通用画质，--pick 时默认吸睛度")
    p.add_argument("--config", help="后端配置 JSON（base_url / api_key / model）")
    p.add_argument("--compare", action="store_true",
                   help="择优模式：多图放一个请求，问哪张最好（需评分卡含 mode=compare 的题）")
    p.add_argument("--pick", action="store_true",
                   help="海选模式：逐图打分排名，再取前几名决赛，选出最好的一张（张数不限）")
    p.add_argument("--finalists", type=int, default=MAX_IMAGES,
                   help=f"--pick 决赛人数，默认 {MAX_IMAGES}；图片最多 {MAX_IMAGES}，文字最多 {MAX_TEXT_FINALISTS}")
    p.add_argument("--split", action="store_true",
                   help="文字文件按空行切成多段，每段作为一个候选")
    p.add_argument("--context", help="补充背景，会拼进 state")
    p.add_argument("--output", help="结果写到该 JSON 文件；默认打印到 stdout")
    p.add_argument("--retries", type=int, default=1, help="失败重试次数，默认 1")
    p.add_argument("--timeout", type=int, default=120, help="单次请求超时秒数，默认 120")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印将发送的请求（图片已脱敏），不调用模型")
    args = p.parse_args()

    if args.compare and args.pick:
        print("配置错误: --compare 与 --pick 只能选一个", file=sys.stderr)
        return 2
    try:
        cands = expand_inputs(args.images, args.split)
    except (ConfigError, OSError, UnicodeDecodeError) as e:
        print(f"配置错误: {e}", file=sys.stderr)
        return 2
    if not cands:
        print("配置错误: 没有找到任何候选", file=sys.stderr)
        return 2
    is_text = cands[0]["kind"] == "text"
    max_group = MAX_TEXT_FINALISTS if is_text else MAX_IMAGES
    if not 2 <= args.finalists <= max_group:
        print(f"配置错误: --finalists 需要在 2-{max_group} 之间", file=sys.stderr)
        return 2
    if is_text and not args.scorecard:
        print("配置错误: 文字候选没有默认评分卡，请按需求写一张并用 --scorecard 传入", file=sys.stderr)
        return 2
    args.scorecard = args.scorecard or (PICK_SCORECARD if args.pick else DEFAULT_SCORECARD)
    if args.compare and not 2 <= len(cands) <= max_group:
        print(f"配置错误: --compare 需要 2-{max_group} 个候选，当前 {len(cands)} 个；更多请用 --pick", file=sys.stderr)
        return 2

    try:
        cfg = load_config(args.config)
        card = load_scorecard(args.scorecard)
    except (ConfigError, json.JSONDecodeError) as e:
        print(f"配置错误: {e}", file=sys.stderr)
        return 2

    usage_total = {"input_tokens": 0, "output_tokens": 0}
    report = {
        "scorecard": {"path": args.scorecard, "name": card.get("name", ""),
                      "purpose": card.get("purpose", ""),
                      "gate_policy": card.get("gate_policy", "report")},
        "backend": {"endpoint": cfg["base_url"].rstrip("/") + PATH_SUFFIX,
                    "model": cfg["model"], "config_source": cfg["__source"]},
        "mode": "compare" if args.compare else ("pick" if args.pick else "per_item"),
        "candidate_kind": cands[0]["kind"],
    }

    def add_usage(usage):
        for k, v in (usage or {}).items():
            if isinstance(v, int):
                usage_total[k] = usage_total.get(k, 0) + v

    if args.compare:
        try:
            verdict, usage, err = judge_compare(cfg, card, cands, args)
        except ConfigError as e:
            print(f"配置错误: {e}", file=sys.stderr)
            return 2
        report["verdict"] = verdict
        add_usage(usage)
        if err:
            report["error"] = err
    else:
        report["verdicts"], failures = [], []
        for cand in cands:
            try:
                verdict, usage, err = judge_one(cfg, card, cand, args)
            except ConfigError as e:
                print(f"配置错误: {e}", file=sys.stderr)
                return 2
            if err:
                failures.append({"file": cand["item"], "error": err})
                continue
            add_usage(usage)
            report["verdicts"].append(verdict)
            if len(cands) > 1:
                print(f"[{len(report['verdicts']) + len(failures)}/{len(cands)}] "
                      f"{os.path.basename(cand['item'])}", file=sys.stderr)
        if failures:
            report["failed"] = failures

    if args.pick and not args.dry_run:
        ranked = sorted((v for v in report["verdicts"] if v.get("weighted_score") is not None),
                        key=lambda v: v["weighted_score"], reverse=True)
        pick = {"ranking": [{"rank": i + 1, "file": v["file"], "score": v["weighted_score"],
                             "grade": v.get("grade")} for i, v in enumerate(ranked)]}
        by_item = {c["item"]: c for c in cands}
        finalists = [v["file"] for v in ranked[:args.finalists]]
        pick["finalists"] = finalists
        if len(finalists) == 1:
            pick["winner"], pick["decided_by"] = finalists[0], "only_candidate"
        elif finalists:
            try:
                final, usage, err = judge_compare(cfg, card, [by_item[x] for x in finalists], args)
            except ConfigError as e:
                print(f"配置错误: {e}", file=sys.stderr)
                return 2
            add_usage(usage)
            if final and final.get("winner"):
                pick["final"] = final
                if final["winner"]["confidence"] >= MIN_FINAL_CONFIDENCE:
                    pick["winner"], pick["decided_by"] = finalists[final["winner"]["index"]], "final_compare"
                else:
                    # 决赛概率接近均匀分布时等于随机，不拿它定冠军
                    pick["winner"], pick["decided_by"] = finalists[0], "per_item_score_low_final_confidence"
            else:
                # 决赛失败时退回逐项分第一名，并如实标出来源
                pick["winner"], pick["decided_by"] = finalists[0], "per_item_score"
                pick["final_error"] = err or "决赛未返回有效 winner"
        report["pick"] = pick

    report["usage"] = usage_total

    scored = [v for v in report.get("verdicts", []) if v.get("weighted_score") is not None]
    if scored:
        report["summary"] = {
            "count": len(scored),
            "best": max(scored, key=lambda v: v["weighted_score"])["file"],
            "avg_weighted_score": round(sum(v["weighted_score"] for v in scored) / len(scored), 2),
            "gate_blocked": [v["file"] for v in scored if not v.get("gate_passed")],
        }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        print(f"已写入 {args.output}", file=sys.stderr)
    else:
        print(text)

    if args.dry_run:
        return 0
    if report.get("error") or report.get("failed") or report.get("pick", {}).get("final_error"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())