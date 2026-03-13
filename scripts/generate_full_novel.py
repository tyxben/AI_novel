"""Generate full 25-chapter novel with DeepSeek."""
import logging
import time
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)

from src.novel.pipeline import NovelPipeline
from src.novel.config import NovelConfig
from src.novel.storage.file_manager import FileManager

NOVEL_ID = "novel_49732f92"
PROJECT_PATH = f"workspace/novels/{NOVEL_ID}"

pipe = NovelPipeline(config=NovelConfig(), workspace="workspace")
fm = FileManager("workspace")

# Check what's already done
existing = fm.list_chapters(NOVEL_ID)
start = max(existing) + 1 if existing else 1

if start > 25:
    print("All 25 chapters already generated!")
    sys.exit(0)

print(f"=== Generating chapters {start}-25 ===")
t0 = time.time()

result = pipe.generate_chapters(
    PROJECT_PATH,
    start_chapter=start,
    end_chapter=25,
    silent=True,
)

elapsed = time.time() - t0
print(f"\n{'='*50}")
print(f"Generated: {result['total_generated']} chapters")
print(f"Time: {elapsed/60:.1f} minutes")
print(f"Errors: {len(result.get('errors', []))}")

# Summary
total_words = 0
for ch in range(1, 26):
    text = fm.load_chapter_text(NOVEL_ID, ch)
    if text:
        wc = len(text)
        total_words += wc
        print(f"  Ch{ch:2d}: {wc:,} 字")
    else:
        print(f"  Ch{ch:2d}: -- 未生成 --")

print(f"\n总计: {total_words:,} 字")
print(f"目标: 100,000 字")
print(f"完成率: {total_words/100000*100:.1f}%")

# Export
output = pipe.export_novel(PROJECT_PATH)
print(f"\n导出完成: {output}")
