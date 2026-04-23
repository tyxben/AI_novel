"""阶段 1: 用 NovelToolFacade.regenerate_section 给 vol2 出新大纲草案。

hints 关键：
- 承接 ch25 末尾局势：黑风煞主力逼近矿场外围、青蛇帮许先生侧翼观望、矿脉阴脉+银纹灵石+玉简异常、废道封死、内应已锁定一小撮人
- 去掉"炼气三层修士+灵根"设定 —— 林辰是无灵根穿越者，只靠系统+银纹灵石+阴脉 做替代修炼路径
- 保留：紫雾污染、阴脉、银纹灵石与玉简共鸣、高维入侵/坐标锚定（但淡化"虚空主宰"式神性反派，换成"外部势力盯上阴脉"的人性化对手）
- vol2 核心：从矿场之战 → 扩张到第一座据点城镇 → 与青蛇帮/铁剑门的三方博弈 → 揭开阴脉真相为 vol3 铺路
"""
import os
import sys
from pathlib import Path

_ROOT = Path("/Users/ty/self/AI_novel")
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_env_path = _ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            _v = _v.strip().strip("'\"")
            if _k and _k not in os.environ:
                os.environ[_k] = _v

from src.novel.services.tool_facade import NovelToolFacade

hints = """【vol2 重写硬约束】

# 设定红线（必守）
- 林辰始终"无灵根"，不得引入"炼气X层"这类传统修仙等级。所有力量增长必须来自：系统任务奖励 / 地盘扩张给的属性加成 / 银纹灵石与玉简的异源共鸣 / 兵煞锻体（第16章已铺垫）
- 可以有修仙界的设定（散修、宗门、灵石、法器），但林辰这一方是"替代路径"：制度+兵法+系统，对标传统修士的硬实力
- 不得让配角突然说"我是炼气三层修士"来对话 —— 要对抗修士就用环境、阵法、配角苏晚照/李四的符箓/毒物等

# 承接 vol1 末尾（ch18-25 已发生）
- ch20 已反杀周彪，黑风寨彻底断根；黑风煞本人仍在西岭外观望（vol1 大纲写的"黑风煞"实际对应文本里的是"黑风寨副寨主"，vol2 要把"黑风煞"作为退到西岭外的残部头目重新塑造）
- ch22-23 已披露青蛇帮"许先生"试探 + 阴脉节点存在 + 银纹灵石与系统产生共鸣
- ch24-25 已封死废道，矿工中锁定一小撮可疑内应，黑风煞+青蛇帮+铁剑门三方向矿场聚拢

# vol2 骨架（ch26-60，共 35 章）
1. ch26-32（**这段要重写**）
   - 聚焦：矿场之战实战化，三方势力（黑风煞残部 / 青蛇帮许先生 / 铁剑门暗探）围绕阴脉博弈
   - 林辰通过系统+银纹灵石+制度化轮转，以弱胜强，初步打出辰风村的"阵地防御 + 游击反击"范式
   - 引入阴脉真相的第一层：不是"虚空主宰"那种外神，而是一个被旧宗门封印的古战场，阴脉是镇压器，黑色晶石是"破封钥匙"（外部势力要破封拿里面的东西）
   - 内应揭露：不是普通矿工，是青蛇帮通过贿赂某个老矿工监察官安插的
   - 不要写"炼气"、"灵根"、"渡劫"、"金丹"、"元婴"这类词
   - 每章 2500-3200 字，带明确的钩子（end_hook）和章节类型（setup/buildup/climax）
   - ch32 作为这一小段的子高潮：阴脉封印被外敌试图破开，林辰用系统+银纹灵石反制，镇压暂时稳住，但玉简代价上升

2. ch33-45 迁都与扩张
   - 辰风村 → 建"辰风镇"（第一座真正的城），完成向"有县制/税收/兵营"的过渡
   - 分封制进化：李四管矿、钱七管商路、苏晚照管情报、新增一位文官管户籍（新角色由 ProjectArchitect 按需生成）
   - 与铁剑门结盟 vs 与青蛇帮对抗，林辰必须选边
   - 高潮：青蛇帮"许先生"第一次露面

3. ch46-55 阴脉第二层真相
   - 阴脉下的古战场浮现更多遗迹/典籍/旧战场记忆
   - 林辰借古战场灵能修复玉简裂纹、解锁系统新权限
   - 黑风煞被收编成为外围眼线（vol1 大纲 ch25 转折点在这里正式落地）
   - 引入更大的宗门反派：某大宗门派弟子来"调查阴脉" → 为 vol3 做对手铺垫

4. ch56-60 收卷
   - 辰风镇一战击退大宗门先遣队（靠地形 + 阵地 + 系统 + 阴脉遗能 组合）
   - 林辰完成"从草莽首领到真正领主"的第二次蜕变 —— 从占矿脉到守城
   - 末尾钩子：古战场深处一块残碑浮现，上面刻着一个名字，系统突然报"契约锚点已识别主线对手"

# 其它
- chapter_type_dist 分配合理（35 章 大约 setup 4 / buildup 18 / climax 6 / resolution 5 / interlude 2）
- foreshadowing_plan：
  - 必须到期兑现：vol1 埋下的"黑风煞报复"、"许先生身份"、"阴脉真相"、"内应身份"
  - 新埋：大宗门对手身份、古战场碑文、辰风镇城防体系
- 语言风格保持 ch1-25 的粗砺硬朗，不要堆砌科幻 buzzword（"高维入侵通道"、"坐标锚定"这类词少用，每章最多一次，且要配合系统界面小字出现，不写成常态叙述）
"""

facade = NovelToolFacade(workspace="workspace")
print("[facade] calling regenerate_section(section='volume_outline', volume_number=2)")
print(f"[facade] hints length: {len(hints)} chars")
print()

env = facade.regenerate_section(
    project_path="workspace/novels/novel_12e1c974",
    section="volume_outline",
    hints=hints,
    volume_number=2,
)

print(f"proposal_id: {env.proposal_id}")
print(f"proposal_type: {env.proposal_type}")
print(f"warnings: {env.warnings}")
print(f"errors: {env.errors}")
print()

if env.errors:
    raise SystemExit("propose errors, aborting")

data = env.data or {}
print(f"title: {data.get('title')}")
print(f"volume_goal: {data.get('volume_goal','')[:200]}")
print(f"chapter_numbers: {data.get('chapter_numbers')[:10]}..{data.get('chapter_numbers')[-5:] if data.get('chapter_numbers') else []}")
print(f"chapter_type_dist: {data.get('chapter_type_dist')}")
print(f"chapter_outlines count: {len(data.get('chapter_outlines') or [])}")

fs_plan = data.get("foreshadowing_plan") or {}
print(f"foreshadowing_plan: to_plant={len(fs_plan.get('to_plant') or [])}, "
      f"to_collect_from_previous={len(fs_plan.get('to_collect_from_previous') or [])}")

# 保存草案到文件以便用户审阅
import json
from pathlib import Path
out = Path("workspace/quality_reports/audit/novel_12e1c974_vol2_proposal.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({
    "proposal_id": env.proposal_id,
    "proposal_type": env.proposal_type,
    "data": data,
    "warnings": env.warnings,
    "errors": env.errors,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nproposal saved: {out}")

# 汇总章节大纲给用户看
print("\n=== 新大纲章节列表 (ch26-60) ===")
for co in (data.get("chapter_outlines") or [])[:40]:
    n = co.get("chapter_number", "?")
    t = co.get("title", "")[:18]
    goal = (co.get("goal") or co.get("main_conflict") or "")[:100]
    ctype = co.get("chapter_type", "")
    print(f"  ch{n:>3} [{ctype:>10}] {t!r:>22} | {goal}")
