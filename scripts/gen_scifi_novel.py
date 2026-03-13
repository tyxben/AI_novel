#!/usr/bin/env python3
"""生成科幻小说：人类星际旅行遭遇高维生物，成功逃脱。"""

import sys
import os
import logging
import time

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 加载 .env 文件（手动解析，不依赖 python-dotenv）
_env_path = os.path.join(ROOT, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value

from src.novel.pipeline import NovelPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

def main():
    start = time.time()

    pipe = NovelPipeline(workspace="workspace")

    # 1. 创建项目（大纲 + 世界观 + 角色）
    print("=" * 60)
    print("第一阶段：创建项目（大纲 + 世界观 + 角色）")
    print("=" * 60)

    result = pipe.create_novel(
        genre="科幻",
        theme="人类首次星际远征，在深空遭遇高维生物的降维打击，经历绝望与牺牲后找到逃脱方法，幸存者带着警示返回地球",
        target_words=30000,
        style="webnovel.shuangwen",
        custom_ideas=(
            "硬科幻风格，注重科学设定的合理性。"
            "高维生物不是传统意义的外星人，而是存在于更高维度的存在，人类无法直接感知。"
            "核心冲突：维度差的碾压感 + 人类的渺小与不屈。"
            "结局：不是战胜高维生物，而是利用物理规律找到逃脱缝隙，带着敬畏活下来。"
        ),
    )

    novel_id = result["novel_id"]
    project_path = f"workspace/novels/{novel_id}"
    print(f"\n项目创建完成: {novel_id}")
    print(f"项目路径: {project_path}")

    # 2. 生成全部章节
    print("\n" + "=" * 60)
    print("第二阶段：生成全部章节")
    print("=" * 60)

    gen_result = pipe.generate_chapters(
        project_path=project_path,
        start_chapter=1,
        silent=True,  # 不暂停，一口气生成
    )

    elapsed = time.time() - start
    print("\n" + "=" * 60)
    print(f"生成完成！耗时 {elapsed / 60:.1f} 分钟")
    print(f"项目路径: {project_path}")
    print("=" * 60)

    # 3. 统计
    chapters_dir = os.path.join(project_path, "chapters")
    total_chars = 0
    for f in sorted(os.listdir(chapters_dir)):
        if f.endswith(".txt"):
            path = os.path.join(chapters_dir, f)
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
                chars = len(text)
                total_chars += chars
                print(f"  {f}: {chars} 字")

    print(f"\n总字数: {total_chars} 字")


if __name__ == "__main__":
    main()
