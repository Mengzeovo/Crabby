"""关键词匹配算法 — 根据用户消息匹配相关 Skill。

MVP 阶段使用简单的关键词重叠度算法：
1. 从 Skill 的 description 提取关键词（分词 + 去停用词）
2. 检查 user_message 中包含多少关键词
3. 返回 0.0~1.0 的匹配分数

后续可扩展为：
- 语义嵌入匹配（通过 MemPalace 的 embedding 能力）
- LLM Side Query 匹配（用小模型判断是否相关）
"""

from __future__ import annotations

import re

# 中文停用词（高频无意义词）
_CN_STOP_WORDS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 "
    "自己 这 这个 这些 那 那个 那些 它 他 她 们 与 及 或 而 但 如果 当 让 把 被 从 "
    "可以 能 需要 应该 可能 必须 用 通过 进行 使用 时 时候".split()
)

# 英文停用词
_EN_STOP_WORDS = frozenset(
    "the a an is are was were be been being have has had do does did will would "
    "shall should may might can could must need to of in on at by for with from "
    "and or but not this that these those it its he she they them their his her "
    "my your our who what which when where how if as so than too very".split()
)

_STOP_WORDS = _CN_STOP_WORDS | _EN_STOP_WORDS

# 分词正则：匹配中文字符或英文单词
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_-]+")


def tokenize(text: str) -> list[str]:
    """将文本分词并去除停用词。

    对中文使用单字切分（bigram 效果更好但 MVP 先用单字），
    对英文使用空格分词。

    Returns:
        去重后的小写 token 列表。
    """
    tokens: set[str] = set()
    for match in _TOKEN_RE.finditer(text):
        word = match.group().lower()
        if word in _STOP_WORDS or len(word) < 2:
            continue

        # 中文：按字符级别处理（保留 2 字及以上的连续中文）
        if re.match(r"[\u4e00-\u9fff]", word):
            # 如果中文片段 ≥ 2 字，加入整体作为一个 token
            if len(word) >= 2:
                tokens.add(word)
            # 同时加入所有 bigram 以提高召回率
            for i in range(len(word) - 1):
                bigram = word[i : i + 2]
                if bigram not in _STOP_WORDS:
                    tokens.add(bigram)
        else:
            tokens.add(word)

    return list(tokens)


def keyword_match_score(skill_description: str, user_message: str) -> float:
    """计算 Skill description 与用户消息之间的关键词匹配分数。

    算法：
    1. 分别对 description 和 user_message 分词
    2. 计算交集大小 / description 关键词总数
    3. 返回 0.0~1.0 的分数

    Args:
        skill_description: Skill 的 description 文本。
        user_message     : 用户发送的消息。

    Returns:
        匹配分数（0.0 = 完全不匹配，1.0 = 完全匹配）。
    """
    desc_tokens = set(tokenize(skill_description))
    msg_tokens = set(tokenize(user_message))

    if not desc_tokens:
        return 0.0

    overlap = desc_tokens & msg_tokens
    return len(overlap) / len(desc_tokens)
