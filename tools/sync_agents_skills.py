#!/usr/bin/env python3
"""Regenerate the .agents/ mirror from the .claude/ source of truth.

.claude/skills/ + CLAUDE.md 是唯一 source of truth；
.agents/skills/ + AGENTS.md 由本腳本生成，**禁止手工編輯**。
（手工雙修的後果：2026-07-01 修復前 briefing 鏡像落後 420 行，
且舊鏡像曾被 "Claude"→"Codex" 全文置換，產生「Codex 不看 Codex 的結論」壞損。）

轉換規則（刻意最小化）：
- 內文字串 "CLAUDE.md" → "AGENTS.md"（讓鏡像的內部引用自洽）
- 其餘一字不動 — 特別是**不做 "Claude"→"Codex" 置換**
- frontmatter `model:` 保持與 .claude 相同（其他 harness 自行映射或忽略）

用法：
  python3 tools/sync_agents_skills.py          # 重生成鏡像
  python3 tools/sync_agents_skills.py --check  # 只比對不寫入；有 drift 則 exit 1
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_SKILLS = ROOT / ".claude" / "skills"
DST_SKILLS = ROOT / ".agents" / "skills"


def transform(content: str) -> str:
    return content.replace("CLAUDE.md", "AGENTS.md")


def build_targets() -> list[tuple[Path, Path]]:
    pairs = [(ROOT / "CLAUDE.md", ROOT / "AGENTS.md")]
    for skill_md in sorted(SRC_SKILLS.glob("*/SKILL.md")):
        pairs.append((skill_md, DST_SKILLS / skill_md.parent.name / "SKILL.md"))
    return pairs


def main() -> int:
    check_only = "--check" in sys.argv
    drift, synced = [], []

    for src, dst in build_targets():
        expected = transform(src.read_text(encoding="utf-8"))
        current = dst.read_text(encoding="utf-8") if dst.exists() else None
        if current == expected:
            continue
        if check_only:
            drift.append(dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(expected, encoding="utf-8")
            synced.append(dst)

    # 移除 .claude 已不存在的孤兒 skill 鏡像
    src_names = {p.parent.name for p in SRC_SKILLS.glob("*/SKILL.md")}
    for orphan in sorted(DST_SKILLS.iterdir()) if DST_SKILLS.exists() else []:
        if orphan.is_dir() and orphan.name not in src_names:
            if check_only:
                drift.append(orphan)
            else:
                shutil.rmtree(orphan)
                synced.append(orphan)

    if check_only:
        if drift:
            print("❌ .agents 鏡像 drift（執行 python3 tools/sync_agents_skills.py 重生成）：")
            for p in drift:
                print(f"  - {p.relative_to(ROOT)}")
            return 1
        print("✅ .agents 鏡像與 .claude 同步")
        return 0

    if synced:
        print("已重生成：")
        for p in synced:
            print(f"  - {p.relative_to(ROOT)}")
    else:
        print("✅ 鏡像已是最新，無需寫入")
    return 0


if __name__ == "__main__":
    sys.exit(main())
