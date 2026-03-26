"""Seed data for Prompt Registry.

Migrates hardcoded prompts from writer.py and style_presets.py into the registry,
and adds new craft technique blocks.
"""

from __future__ import annotations

from src.prompt_registry.registry import PromptRegistry


def seed_default_prompts(registry: PromptRegistry) -> None:
    """Populate the registry with default prompt blocks and templates.

    Sources:
    - src/novel/agents/writer.py: _ANTI_AI_FLAVOR, _ANTI_REPETITION, _NARRATIVE_LOGIC, _CHARACTER_NAME_LOCK
    - src/novel/templates/style_presets.py: all style presets (system_prompt + few_shot_examples)
    - New: craft technique blocks for different scene types
    """
    # ------------------------------------------------------------------
    # 1. Anti-pattern blocks (from writer.py)
    # ------------------------------------------------------------------
    _seed_anti_pattern_blocks(registry)

    # ------------------------------------------------------------------
    # 2. Style blocks (from style_presets.py)
    # ------------------------------------------------------------------
    _seed_style_blocks(registry)

    # ------------------------------------------------------------------
    # 3. Craft technique blocks (new)
    # ------------------------------------------------------------------
    _seed_craft_blocks(registry)

    # ------------------------------------------------------------------
    # 4. Feedback injection block (special placeholder)
    # ------------------------------------------------------------------
    _seed_feedback_block(registry)

    # ------------------------------------------------------------------
    # 5. Templates
    # ------------------------------------------------------------------
    _seed_templates(registry)


# =====================================================================
# Anti-pattern blocks (migrated from writer.py constants)
# =====================================================================

_ANTI_AI_FLAVOR = (
    "【重要】以下短语和写法是典型 AI 生成痕迹，必须完全避免：\n"
    "- 禁止使用：内心翻涌、莫名的力量、不由得、深深的、满满的、"
    "说实话、老实说、竟然（过度使用）、一股莫名的、仿佛、宛如（过度使用）\n"
    "- 禁止空洞抒情和无意义排比\n"
    "- 禁止所有角色说话语气雷同\n"
    "- 用具体动作和细节代替抽象形容\n"
    "- 对话要符合角色性格和身份，不同角色说话方式必须有区别\n"
)

_ANTI_REPETITION = (
    "【反重复规则 — 严格遵守】\n"
    "1. 禁止重复前文已经出现过的场景、事件或描写。如果前文已经写过导弹攻击，不要再写一次类似场景\n"
    "2. 禁止在不同章节中重复使用同一个比喻或意象。一个比喻全书只能用一次\n"
    "3. 如果前文回顾中已有某个信息（角色说过的话、发生过的事），本场景中必须推进到新的内容，不能重述\n"
    "4. 每个场景必须包含至少一个前文中没有出现过的新信息、新发现或新转折\n"
    "5. 不同角色说话必须有明显区别：\n"
    "   - 指挥官：简短命令式，不解释\n"
    "   - 科学家：用数据和术语，但夹带个人情绪\n"
    "   - 工程师：关注实际操作，用具体数字\n"
    "   - 普通船员：口语化，会害怕、会抱怨\n"
    "6. 禁止不同角色说出措辞相似的台词。每个角色有自己的语言习惯和口头禅\n"
)

_NARRATIVE_LOGIC = (
    "【叙事逻辑规则 — 必须遵守】\n"
    "1. 每个提出的方案/计划必须有明确结局（成功、失败、或被放弃），不能悬而未决就开始新方案\n"
    "2. 出场的角色必须有交代：如果角色去执行任务，后续必须写到他的结果（成功/失败/牺牲）\n"
    "3. 角色的死亡/受伤只能发生一次，且必须前后一致。已死的角色不能再出现\n"
    "4. 数字和距离等具体细节必须与前文保持一致（如果前文说距离0.3光年，后文不能变成柯伊伯带）\n"
    "5. 关键转折不能依赖巧合（如'突然引擎自启'），必须有前文铺垫的合理解释\n"
    "6. 同一个事件只能出现一次。如果前文已经写过新闻发布会，不要再写第二次\n"
)

_CHARACTER_NAME_LOCK = (
    "【角色名称锁定 — 绝对禁止违反】\n"
    "1. 每个角色只能使用【角色档案】中定义的名字，禁止自行给角色起新名字、加姓氏或改名\n"
    "2. 禁止使用占位符称呼：禁止写「角色A」「女学生B」「老人C」「男子D」「路人甲」等编号式称呼\n"
    "3. 如果需要引入新的路人/NPC，可以用职业/特征称呼（如「收银员」「保安」），但同一个NPC前后称呼必须一致\n"
    "4. 角色名字一旦出现在前文中，后续必须使用完全相同的名字，不能缩写或扩展（如「小玲」不能变成「李小玲」）\n"
)


def _seed_anti_pattern_blocks(registry: PromptRegistry) -> None:
    registry.create_block(
        base_id="writer_anti_ai_flavor",
        block_type="anti_pattern",
        content=_ANTI_AI_FLAVOR,
        agent="writer",
    )
    registry.create_block(
        base_id="writer_anti_repetition",
        block_type="anti_pattern",
        content=_ANTI_REPETITION,
        agent="writer",
    )
    registry.create_block(
        base_id="writer_narrative_logic",
        block_type="anti_pattern",
        content=_NARRATIVE_LOGIC,
        agent="writer",
    )
    registry.create_block(
        base_id="writer_character_name_lock",
        block_type="anti_pattern",
        content=_CHARACTER_NAME_LOCK,
        agent="writer",
    )


# =====================================================================
# Style blocks (migrated from style_presets.py)
# =====================================================================

# Style key -> (genre tag, system_prompt, few_shot_examples)
_STYLE_DATA: dict[str, tuple[str, str, list[str]]] = {
    "wuxia.classical": (
        "wuxia",
        (
            "你是一位深谙古典武侠笔法的作家。"
            "文风沉稳大气，善用半文半白的语言，"
            "描写武功招式时注重意境而非数值，"
            "刻画人物以行动和对话展现性格，少用心理独白。"
            "叙事节奏如行云流水，张弛有度。"
            "参考金庸、古龙、梁羽生的行文风格。"
        ),
        [
            (
                "他缓缓拔剑，剑身映出庭前积雪的冷光。"
                "对面那人冷笑一声，袍袖一振，三枚铁蒺藜已无声飞出。"
                "他侧身让过，脚下不退反进，剑尖直点对方咽喉。"
                "两人身形交错，檐上积雪簌簌而落。"
            ),
            (
                "酒入愁肠，他望着窗外的秋雨，"
                "忽然觉得这江湖走了二十年，"
                "竟不知该向何处去。"
            ),
        ],
    ),
    "wuxia.modern": (
        "wuxia",
        (
            "你是一位新派武侠作家，语言流畅现代但不失江湖气韵。"
            "动作场面快节奏、画面感强，善用短句制造紧张感。"
            "人物对话鲜活，带有黑色幽默。"
            "兼具武侠的侠义精神和现代叙事技巧。"
            "参考温瑞安、沧月的行文风格。"
        ),
        [
            (
                "刀光一闪。\n"
                "他还没看清对手出刀的轨迹，胸口已经多了一道血痕。\n"
                "\"你太慢了。\"对面的女人收刀入鞘，语气像在点评一道不够火候的菜。"
            ),
        ],
    ),
    "webnovel.shuangwen": (
        "webnovel",
        (
            "你是一位经验丰富的网文爽文写手。"
            "节奏极快，每章必有爽点，绝不拖泥带水。"
            "善用打脸、装逼、逆袭等经典桥段制造爽感。"
            "对话占比高，段落短促，句式简洁有力。"
            "配角常用来衬托主角的强大与魅力。"
            "每章结尾设置钩子，让读者欲罢不能。"
        ),
        [
            (
                "\"废物？\"\n"
                "林凡嘴角微扬，随手一挥。\n"
                "轰！\n"
                "一股恐怖的气浪横扫全场，那几个嘲笑他的弟子直接被震飞出去，"
                "撞在墙壁上，口吐鲜血。\n"
                "全场寂静。\n"
                "所有人都傻了。"
            ),
        ],
    ),
    "webnovel.xuanhuan": (
        "webnovel",
        (
            "你是一位擅长玄幻题材的网文作家。"
            "世界观恢弘大气，功法体系严谨有层次感。"
            "战斗场面大开大合，注重视觉冲击力。"
            "人物修炼突破时要有仪式感和史诗感。"
            "用具体的环境反应（天地异象、空间震颤）表现实力。"
            "对话简洁有力，避免冗长说教。"
        ),
        [
            (
                "丹田之中，金色的真元如同沸腾的岩浆般翻涌。"
                "第七条经脉在剧烈的疼痛中被强行贯通，"
                "一股磅礴的气息从他体内爆发而出。\n"
                "方圆百里，飞鸟惊散，走兽伏地。"
                "天际一道紫色雷霆无声劈下，正中他所在的山巅。\n"
                "烟尘散尽，他睁开双眼——瞳孔中有金光流转。"
            ),
        ],
    ),
    "webnovel.romance": (
        "webnovel",
        (
            "你是一位擅长言情小说的作家。"
            "善于细腻刻画人物情感变化，注重心理描写。"
            "对话生动自然，富有生活气息和小暧昧。"
            "善用环境烘托情绪，节奏舒缓中带小波澜。"
            "男女主互动要有化学反应，甜而不腻。"
            "场景描写要有代入感，让读者感同身受。"
        ),
        [
            (
                "他递过来的伞有些旧了，伞柄上缠着一圈创可贴。\n"
                "\"不用——\"\n"
                "\"别淋了，感冒不好受。\"他说完就走进了雨里，"
                "校服很快被淋湿，贴在瘦削的后背上。\n"
                "她站在原地，握着那把伞，忽然觉得手心有点烫。"
            ),
        ],
    ),
    "literary.realism": (
        "literary",
        (
            "你是一位严肃文学作家，追求现实主义创作手法。"
            "语言精准克制，不滥用修辞，每个词都要有分量。"
            "善于通过日常细节折射人性和社会。"
            "叙事视角灵活，善用白描手法。"
            "人物塑造追求真实复杂，没有绝对的好人坏人。"
            "参考余华、莫言、路遥的行文风格。"
        ),
        [
            (
                "父亲把最后一口馒头塞进嘴里，用手背擦了擦嘴，"
                "站起身来往外走。走到门口又停下，"
                "从裤兜里摸出两张皱巴巴的十块钱，放在桌上。"
                "他没说话，门在身后关上了。\n"
                "桌上的钱被穿堂风吹得微微颤动。"
            ),
        ],
    ),
    "literary.lyrical": (
        "literary",
        (
            "你是一位诗意盎然的文学作家，擅长抒情散文化叙事。"
            "语言优美而不浮华，善用意象和隐喻。"
            "注重声韵节奏，句式错落有致。"
            "以情感和意境驱动叙事，而非情节。"
            "参考沈从文、汪曾祺、迟子建的行文风格。"
        ),
        [
            (
                "黄昏从河面上漫过来，把岸边的芦苇染成了金红色。"
                "她坐在渡口的石阶上，脚泡在凉沁沁的水里，"
                "看对岸的炊烟一缕一缕地升起来，"
                "像是有人在天空上写字，写了又被风擦去。"
            ),
        ],
    ),
    "scifi.hardscifi": (
        "scifi",
        (
            "你的写作风格参考刘慈欣、阿西莫夫。"
            "用冷静克制的笔触描写宏大场景。"
            "科学概念融入剧情，不做无意义的技术说明。"
            "人物情感要克制但真实，通过行动而非内心独白展现。"
            "对话简洁有力，避免废话。"
            "场景描写注重视觉冲击力和空间感。"
            "保持紧张感，每个段落都要推进情节。"
        ),
        [
            (
                "警报声撕裂了指挥舱的寂静。全息屏上，"
                "那个不明物体的轨迹曲线正以不可能的角度弯折——"
                "没有任何已知天体的引力场能解释这种运动。\n"
                "\"轨道异常，偏差率超过百分之三百。\"导航员的声音很稳，"
                "但他握住扶手的指关节已经发白。\n"
                "舰长盯着屏幕上不断刷新的数据，做了一个决定。"
                "这个决定将在此后的二十七年里反复被人类审判。"
            ),
        ],
    ),
    "light_novel.campus": (
        "light_novel",
        (
            "你是一位日系轻小说风格的作家，擅长校园题材。"
            "以第一人称叙事为主，语气轻松吐槽感强。"
            "对话占比极高，对话节奏明快，善用吐槽和冷笑话。"
            "内心独白频繁且有趣，善于自我解嘲。"
            "角色个性鲜明，有固定口癖和行为模式。"
            "参考渡航的行文风格。"
        ),
        [
            (
                "\"所以说，为什么我要在周末来学校啊。\"\n"
                "我靠在走廊的窗边，对着空无一人的操场发出了灵魂拷问。\n"
                "当然，没有人回答我。"
                "毕竟正常人周末都不会来学校。"
                "而我来了。"
                "这说明什么？\n"
                "说明我不正常。\n"
                "不对，说明社团的学姐不正常。"
            ),
        ],
    ),
    "light_novel.fantasy": (
        "light_novel",
        (
            "你是一位日系异世界轻小说风格的作家。"
            "叙事轻快有趣，善于在严肃场面中穿插幽默。"
            "战斗场面兼具画面感和轻松感，不过分血腥。"
            "角色互动有番剧感，善用经典桥段但不落俗套。"
            "世界观设定融合游戏元素（等级、技能、状态栏）。"
            "第一人称或有限第三人称视角。"
        ),
        [
            (
                "【叮！恭喜获得技能「鉴定」LV.1】\n"
                "我盯着眼前突然弹出的半透明面板，陷入了沉思。\n"
                "三秒前我还在便利店买关东煮，"
                "三秒后我就站在了一片看起来很中世纪的草原上。\n"
                "\"勇者大人，您终于来了！\"一个穿着白袍的老头热泪盈眶地看着我。\n"
                "不好意思，我想先把关东煮吃完可以吗。"
            ),
        ],
    ),
}


def _seed_style_blocks(registry: PromptRegistry) -> None:
    """Create style system_instruction and few_shot_example blocks."""
    for style_key, (genre, system_prompt, examples) in _STYLE_DATA.items():
        # Convert dotted style key to underscore block base_id
        base_id = "style_" + style_key.replace(".", "_")
        registry.create_block(
            base_id=base_id,
            block_type="system_instruction",
            content=system_prompt,
            agent="writer",
            genre=genre,
        )

        # Few-shot examples block
        if examples:
            examples_content = "\n\n---\n\n".join(examples)
            registry.create_block(
                base_id=base_id + "_examples",
                block_type="few_shot_example",
                content=examples_content,
                agent="writer",
                genre=genre,
            )


# =====================================================================
# Craft technique blocks (new content)
# =====================================================================

_CRAFT_BLOCKS: dict[str, tuple[str | None, str]] = {
    "craft_battle": (
        "battle",
        (
            "【战斗场景写作技法】\n"
            "1. 多视角切换：不要只写主角视角，穿插旁观者、对手、环境的反应\n"
            "2. 用环境反应表现力量：地面龟裂、空气扭曲、飞鸟惊散，而非直接说「很强」\n"
            "3. 倒计时紧迫感：设定时间限制（毒发、援军到达、结界崩溃），让每一招都有重量\n"
            "4. 短句制造节奏：关键打击用短句甚至单字句。长句用于喘息和观察的间隙\n"
            "5. 痛感真实化：描写具体的身体反应（耳鸣、视线模糊、手指发麻），而非抽象的「一阵剧痛」\n"
            "6. 战斗必须推进剧情：每场战斗要揭示新信息、改变关系或推动角色成长"
        ),
    ),
    "craft_dialogue": (
        "dialogue",
        (
            "【对话场景写作技法】\n"
            "1. 每人说话不超过3句就切动作/心理/环境描写，避免大段对白\n"
            "2. 用动作替代说话标签：「他放下茶杯」比「他说」更有画面感\n"
            "3. 潜台词比明说更有力：角色不会直接说出真实想法，用暗示和试探\n"
            "4. 对话节奏要有变化：紧张时短促交锋，缓和时可以有停顿和沉默\n"
            "5. 每个角色有独特的说话方式：用词习惯、句式长短、口头禅\n"
            "6. 对话要有信息增量：每轮对话必须推进信息或关系，禁止废话填充"
        ),
    ),
    "craft_emotional": (
        "emotional",
        (
            "【情感场景写作技法】\n"
            "1. 用物件传递情绪：一把旧伞、一封没寄出的信、桌上凉掉的茶，比直接写「他很伤心」更有力\n"
            "2. 留白暗示：最浓烈的情感往往不说出来。用省略号、转移话题、突然离开来表达\n"
            "3. 环境映射心理：雨天不一定是悲伤，阳光不一定是快乐，用反差制造张力\n"
            "4. 身体语言优先：攥紧的拳头、不自觉后退一步、目光闪躲，比内心独白更真实\n"
            "5. 克制胜过泛滥：一滴眼泪比痛哭流涕更打动人。情感越强烈，文字越要克制\n"
            "6. 回忆要有触发物：不要突然插入回忆，用一个声音、味道或场景自然触发"
        ),
    ),
    "craft_strategy": (
        "strategy",
        (
            "【策略/谋略场景写作技法】\n"
            "1. 信息不对称：读者知道的和角色知道的不同，制造悬念和反转\n"
            "2. 推理链条：展示角色的思考过程，但留一步不说，让读者自己推理\n"
            "3. 赌注升级：每次决策都要有明确代价，选择A就失去B\n"
            "4. 时间压力：限定决策窗口，不给角色从容思考的机会\n"
            "5. 多方博弈：不要只有两方对抗，第三方的介入让局面更复杂\n"
            "6. 计中计结构：表面计划是烟幕弹，真正目的在最后揭示"
        ),
    ),
    "craft_general": (
        None,  # No specific scene_type
        (
            "【通用写作技法】\n"
            "1. Show, don't tell：用具体场景展示，不要直接告诉读者结论\n"
            "2. 具体细节 > 抽象形容：「他的指甲缝里全是机油」比「他是个勤劳的工人」好一百倍\n"
            "3. 短句 = 紧张，长句 = 舒缓：根据场景情绪调节句式长度\n"
            "4. 每个段落一个焦点：不要在一段里同时写动作、心理和环境\n"
            "5. 结尾要有钩子：每个场景结束时留一个未解决的问题或新的悬念\n"
            "6. 删掉「然后」「接着」「随后」：用动作本身的因果关系推进，不需要时间连接词"
        ),
    ),
}


def _seed_craft_blocks(registry: PromptRegistry) -> None:
    for base_id, (scene_type, content) in _CRAFT_BLOCKS.items():
        registry.create_block(
            base_id=base_id,
            block_type="craft_technique",
            content=content,
            agent="writer",
            scene_type=scene_type,
        )


# =====================================================================
# Feedback injection block
# =====================================================================

_FEEDBACK_INJECTION_CONTENT = (
    "【上一章反馈 — 请在本章中改进】\n"
    "优点（继续保持）：\n{strengths}\n\n"
    "缺点（本章必须改进）：\n{weaknesses}"
)


def _seed_feedback_block(registry: PromptRegistry) -> None:
    registry.create_block(
        base_id="feedback_injection",
        block_type="feedback_injection",
        content=_FEEDBACK_INJECTION_CONTENT,
        agent="writer",
    )


# =====================================================================
# Templates
# =====================================================================

# Common anti-pattern + feedback refs used by all writer templates
_COMMON_TAIL = [
    "writer_anti_ai_flavor",
    "writer_anti_repetition",
    "writer_narrative_logic",
    "writer_character_name_lock",
    "feedback_injection",
]


def _seed_templates(registry: PromptRegistry) -> None:
    # Default writer template (uses {genre} dynamic ref for style)
    registry.create_template(
        template_id="writer_default",
        agent_name="writer",
        block_refs=["style_{genre}", "craft_general"] + _COMMON_TAIL,
        scenario="default",
        genre=None,
    )

    # Scene-specific templates
    for scene_type in ("battle", "dialogue", "emotional", "strategy"):
        registry.create_template(
            template_id=f"writer_{scene_type}",
            agent_name="writer",
            block_refs=[
                "style_{genre}",
                f"craft_{scene_type}",
                "craft_general",
            ] + _COMMON_TAIL,
            scenario=scene_type,
            genre=None,
        )
