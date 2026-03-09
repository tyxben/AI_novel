"""Prompt 生成器 - 将小说文本转换为图片/视频 Prompt"""

import logging
import re

from src.promptgen.character_tracker import CharacterTracker
from src.promptgen.style_presets import get_preset

log = logging.getLogger("novel")

# LLM 系统提示词
_SYSTEM_PROMPT = """\
你是一个专业的 AI 绘画 Prompt 工程师。你的任务是将中文小说片段转换为 Stable Diffusion 图片生成 Prompt。

要求:
1. 分析文本中的场景、角色、动作、情绪
2. 生成英文 Stable Diffusion prompt
3. 包含: 场景描述、角色外观、动作姿态、光影氛围、画面构图
4. 使用标准 SD 关键词格式（逗号分隔的短语）
5. 突出画面感，忽略对话内容本身
6. 如果有角色，描述其外观特征（发型、服装、表情等）

输出格式: 仅输出英文 prompt 文本，不要包含任何解释或前缀。
"""

# 视频生成 LLM 系统提示词
_VIDEO_SYSTEM_PROMPT = """\
你是一个专业的 AI 视频 Prompt 工程师。你的任务是将中文小说片段转换为 AI 视频生成 Prompt。

要求:
1. 分析文本中的场景、角色、动作、情绪
2. 生成英文视频生成 prompt（自然语言完整句子，非关键词堆叠）
3. 必须包含以下层次:
   - 主体: 角色外观、服装、表情
   - 动作: 具体动作过程，添加速度修饰（slowly, gently, dramatically）
   - 场景: 环境、天气、时间
   - 光影: 光源类型、色温、氛围
   - 运镜: 选择合适的相机运动（dolly in, pan, orbit, tracking 等）
   - 画质: 4K, cinematic quality, natural colors
4. 运镜选择原则:
   - 紧张场景: slow dolly in + 手持感
   - 孤独场景: crane up 远离
   - 壮阔场景: drone/aerial shot
   - 日常对话: static shot
   - 动作场景: tracking/follow shot
   - 揭示场景: pan-to-reveal 或 pull back
   - 浪漫/温馨: slow orbit
5. 动作必须柔和自然，优先使用 slow、gentle、smooth 等修饰词
6. 末尾添加约束: "Stable character appearance, natural smooth movements, cinematic quality, 4K"
7. 如果有角色，保持其外观描述一致
8. 注意视频只有5-10秒，不要描述过多动作，聚焦最核心的一个画面转变

输出格式: 仅输出英文 prompt 文本，不要包含任何解释或前缀。Prompt 应为 2-4 句完整的英文句子。
"""

# ---- 视频运镜自动匹配规则 (按优先级排列，第一个匹配即返回) ----
_CAMERA_MOVEMENT_RULES: list[tuple[str, str]] = [
    # 紧张/悬疑 -> 缓慢推进
    (r"紧张|心跳|不对劲|危险|杀气|恐怖|诡异", "The camera slowly dollies in"),
    # 孤独/悲伤 -> 升降远离
    (r"孤独|一个人|独自|离去|远去|消失", "The camera slowly cranes upward, pulling away"),
    # 壮阔场景 -> 航拍
    (r"山顶|战场|全城|远方|天地|苍茫", "Aerial drone shot sweeping over"),
    # 角色登场 -> 从下往上
    (r"出现|走来|现身|登场|站在.*面前", "The camera tilts up from ground level"),
    # 追逐/动作 -> 跟拍
    (r"追|跑|逃|冲|飞|闪|躲", "Tracking shot following"),
    # 环顾/展示 -> 环绕
    (r"环顾|四周|周围|打量|审视", "The camera slowly orbits around"),
    # 揭示/发现 -> 拉镜
    (r"发现|原来|看到|映入|展现|豁然", "The camera pulls back to reveal"),
    # 回忆/梦境 -> 缓慢zoom
    (r"回忆|想起|记得|梦|往事|从前", "Slow zoom in with soft focus"),
    # 对话/日常 -> 静镜
    (r"说道|问道|笑道|答道|聊|谈", "Static medium shot"),
]

# 默认运镜（当没有规则匹配时）
_DEFAULT_CAMERA = "Gentle dolly in"

# ---- 现代都市场景规则 ----
_MODERN_RULES: list[tuple[str, str]] = [
    # 人物 - 现代装扮
    (r"外卖|快递|骑手", "a delivery person in uniform, holding a takeout bag"),
    (r"口罩", "wearing a face mask"),
    (r"手机|刷视频|相册|照片|拍照", "holding a smartphone"),
    (r"耳机", "wearing earphones"),
    (r"眼镜", "wearing glasses"),
    (r"西装|领带|衬衫", "wearing a business suit"),
    (r"校服|学生", "wearing a school uniform"),
    (r"睡衣|睡眠|失眠|床上|躺在床", "in pajamas"),
    (r"工服|工作服|制服", "wearing a work uniform"),
    # 人物动作 - 现代
    (r"刷牙|洗脸|照镜子|镜子", "looking into a bathroom mirror"),
    (r"做饭|厨房|炒菜|煮|烧水", "in a modern kitchen, cooking"),
    (r"打字|电脑|键盘|屏幕", "sitting at a computer desk"),
    (r"喝咖啡|咖啡", "holding a coffee cup"),
    (r"吃饭|餐桌|碗|筷子|盘子", "at a dining table with food"),
    (r"敲门|开门|关门|锁上门", "standing at a door"),
    (r"按.*按钮|按钮", "pressing a button"),
    (r"跑出|摔门|冲出", "rushing out of a room"),
    (r"喘气|心跳|害怕|吓", "with a frightened expression"),
    (r"笑了|微笑|在笑|笑着", "smiling"),
    (r"哭|流泪|眼泪|破防", "with tears in eyes, emotional"),
    # 场景 - 现代
    (r"电梯", "inside an elevator, metallic walls, floor numbers display"),
    (r"浴室|卫生间|洗手间", "a modern bathroom, white tiles"),
    (r"卧室|房间|床|枕头|被子", "a modern bedroom, dim lighting"),
    (r"客厅|沙发|电视", "a modern living room"),
    (r"厨房|冰箱|灶台", "a modern kitchen"),
    (r"走廊|过道|楼道", "a hallway, fluorescent lighting"),
    (r"阳台|晾衣|浇花", "an apartment balcony with plants"),
    (r"公寓|合租|租屋", "inside a modern apartment"),
    (r"办公室|加班|工位", "a modern office, late at night, desk lamp"),
    (r"超市|便利店", "inside a convenience store, bright lights"),
    (r"地铁|公交|车厢", "inside a subway train"),
    (r"街道|马路|人行道|十字路口", "a modern city street"),
    (r"小区|楼下|单元门", "outside an apartment building"),
    (r"学校|教室|操场", "a school campus"),
    (r"医院|病房|病号服|手术室", "a hospital room, white walls"),
    (r"窗外|窗前|窗台", "looking out a window at the city"),
    # 物品 - 现代
    (r"猫|橘猫|喵", "a cute orange tabby cat"),
    (r"狗|柴犬|汪", "a cute dog"),
    (r"外卖袋|打包", "a takeout food bag"),
    (r"纸巾", "a pack of tissues"),
    (r"钥匙", "holding keys"),
    (r"雨伞|打伞", "holding an umbrella"),
    # 时间氛围 - 现代
    (r"凌晨|深夜|半夜|夜里", "late at night, dark atmosphere, dim indoor lighting"),
    (r"清晨|早上|早晨|闹钟", "early morning, soft morning light"),
    (r"黄昏|傍晚|下班", "evening, warm sunset light through window"),
    (r"周末|休息日", "relaxed weekend atmosphere"),
    # 情绪氛围
    (r"温馨|温暖|幸福|开心", "warm and cozy atmosphere, soft lighting"),
    (r"孤独|一个人|独自", "lonely atmosphere, solitary figure"),
    (r"紧张|心跳加速|不对劲", "tense atmosphere, unsettling mood"),
    (r"恐怖|诡异|毛骨悚然", "horror atmosphere, eerie lighting"),
    (r"搞笑|哈哈|莫名其妙", "comedic scene, humorous mood"),
]

# ---- 古风/仙侠场景规则 ----
_CLASSICAL_RULES: list[tuple[str, str]] = [
    # 人物
    (r"[她他].*?走|行走|疾行|加快.*脚步|脚步", "a person walking"),
    (r"[她他].*?站|驻足|停下|伫立|站住", "a person standing still"),
    (r"[她他].*?坐|端坐|盘坐", "a person sitting"),
    (r"[她他].*?跑|奔跑|疾奔|飞奔", "a person running"),
    (r"剑|刀|兵器|武器|剑柄|拔剑|挥剑", "a swordsman, hand on sword hilt"),
    (r"黑衣人|蒙面人|黑袍", "a mysterious figure in black robes"),
    (r"白衣|白袍|素衣", "a figure in flowing white robes"),
    (r"斗篷|披风|长衫|长袍", "a cloaked figure, flowing cloak"),
    (r"斗笠|面纱|面具", "a figure with a bamboo hat hiding face"),
    (r"少女|女子|姑娘|小姐|美人", "a beautiful young woman"),
    (r"少年|少侠|公子|青年", "a young man, handsome"),
    (r"老者|老人|长者|老翁", "an elderly man, wise appearance"),
    (r"将军|武将|甲胄", "a general in armor"),
    (r"书生|文人|儒生", "a scholar in traditional robes"),
    # 动作
    (r"转身|回头|回首", "turning around, looking back"),
    (r"对峙|拦住|拦路|拦在", "two figures facing each other, confrontation"),
    (r"苦笑|微笑|冷笑", "with a melancholy expression"),
    (r"低喝|怒喝|大喊", "dramatic tension, someone shouting"),
    (r"把酒|饮酒|喝酒|酒杯", "drinking wine"),
    # 场景
    (r"小巷|巷子|胡同|街巷", "narrow ancient alley, stone path"),
    (r"酒楼|酒馆|客栈|茶馆", "a traditional Chinese tavern, warm lights"),
    (r"宫殿|皇宫|大殿", "a grand imperial palace"),
    (r"山顶|山巅|峰顶", "a mountaintop"),
    (r"悬崖|峭壁|绝壁", "a dramatic cliff edge"),
    (r"竹林|竹海", "a bamboo forest"),
    (r"桃花|樱花|花海", "a sea of blossoming flowers"),
    (r"江湖|码头|渡口", "a riverside dock"),
    (r"战场|沙场|两军", "a battlefield"),
    (r"书房|案几|书桌", "a traditional study room"),
    (r"青石板|石板路", "cobblestone path"),
    # 自然/天气
    (r"月光|月色|明月|弯月|圆月", "moonlight, luminous moon in sky"),
    (r"星空|繁星|星辰", "starry night sky"),
    (r"日落|夕阳|余晖", "sunset, golden hour"),
    (r"大雨|暴雨|雨中|细雨", "rain falling"),
    (r"大雪|飞雪|雪中|风雪", "snow falling, winter scene"),
    (r"浓雾|大雾|薄雾|迷雾", "misty, foggy atmosphere"),
    (r"灯火|烛光|火光|火把", "warm lantern light, candlelight"),
    # 氛围
    (r"冷冽|寒风|凛冽|刺骨", "cold atmosphere, biting wind"),
    (r"寂静|安静|无声|静谧", "quiet, serene atmosphere"),
    (r"紧张|危险|杀气|杀机", "tense atmosphere, sense of danger"),
    (r"温馨|温暖|和煦", "warm and cozy atmosphere"),
    (r"丝竹|琴声|笛声|箫声", "faint music in the air"),
]

# 现代关键词（用于自动判断时代）
_MODERN_KEYWORDS = (
    r"手机|电脑|电梯|地铁|公交|外卖|快递|公寓|合租|办公室|加班|"
    r"闹钟|微信|视频|APP|网络|WiFi|空调|冰箱|洗衣机|电视|"
    r"出租车|汽车|高铁|飞机|超市|便利店|咖啡|奶茶|"
    r"校服|T恤|牛仔裤|运动鞋|口罩|耳机|眼镜|"
    r"室友|同事|老板|客户|甲方|KPI|"
    r"抖音|朋友圈|点赞|评论|转发|备注"
)

# 古风关键词
_CLASSICAL_KEYWORDS = (
    r"剑|刀|武功|内力|真气|修仙|仙|魔|妖|灵|丹|阵法|"
    r"江湖|武林|门派|掌门|弟子|侠|义|"
    r"大侠|少侠|公子|姑娘|小姐|夫人|"
    r"皇上|陛下|臣|太子|王爷|将军|丞相|"
    r"长袍|汉服|布衣|锦衣|甲胄|斗篷|"
    r"客栈|酒楼|茶馆|青楼|书院|"
    r"马车|轿子|骏马|战马"
)


class PromptGenerator:
    """Stable Diffusion 图片 Prompt 生成器。

    支持两种工作模式:
      1. LLM 模式 (OPENAI_API_KEY 已设置): 使用 GPT 理解场景后生成高质量 prompt
      2. 本地模式 (无 API Key): 提取关键词 + 风格预设，拼接为 prompt

    自动检测文本时代背景（现代 vs 古风），选择对应的场景规则。
    通过 CharacterTracker 维护角色外观一致性。
    """

    def __init__(self, config: dict) -> None:
        self._style_name: str = config.get("style", "chinese_ink")
        self._preset = get_preset(self._style_name)

        llm_cfg = config.get("llm", {})
        self._model: str = llm_cfg.get("model", "gpt-4o-mini")
        self._temperature: float = llm_cfg.get("temperature", 0.7)

        self._use_character_tracking: bool = config.get("character_tracking", True)
        self._tracker = CharacterTracker() if self._use_character_tracking else None

        # 检测是否可使用 LLM: 任意已知 API Key 或配置了 provider
        self._llm_config = llm_cfg
        self._use_llm: bool = self._detect_llm_available(llm_cfg)
        self._llm_client_cached = None

        # 缓存全文的时代判断结果
        self._era_cache: str | None = None

        if self._use_llm:
            log.info("Prompt 生成: LLM 模式 (model=%s)", self._model)
        else:
            log.info("Prompt 生成: 本地关键词模式 (style=%s)", self._style_name)

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def set_full_text(self, full_text: str) -> None:
        """用全文来判断时代背景，缓存结果供所有片段使用。"""
        self._era_cache = self._detect_era(full_text)
        log.info("检测到文本时代: %s", self._era_cache)

    def generate(self, text: str, segment_index: int) -> str:
        """将小说文本片段转换为 SD 图片 prompt。"""
        if not text or not text.strip():
            return self._preset.get("prefix", "")

        # 提取角色信息
        character_prompt = ""
        if self._tracker:
            characters = self._tracker.extract_characters(text)
            character_prompt = self._tracker.get_character_prompt(characters)

        # 根据模式生成 prompt
        if self._use_llm:
            prompt = self._generate_with_llm(text, character_prompt)
        else:
            prompt = self._generate_local(text, character_prompt)

        # 更新角色追踪器
        if self._tracker:
            self._tracker.update(text, prompt)

        log.debug("段 %d prompt: %s", segment_index, prompt[:80])
        return prompt

    @property
    def character_tracker(self) -> CharacterTracker | None:
        """获取角色追踪器实例（用于外部序列化/恢复）。"""
        return self._tracker

    def generate_video_prompt(self, segment_text: str, segment_index: int) -> str:
        """将小说文本片段转换为视频生成 AI 的 prompt。

        视频 prompt 与图片 prompt 的主要区别:
        - 使用自然语言完整句子（而非逗号分隔的关键词）
        - 包含运镜描述（camera movement）
        - 包含角色动作过程（而非静态姿态）
        - 包含场景过渡和氛围描写

        Args:
            segment_text: 中文小说文本片段。
            segment_index: 片段在全文中的序号（从 0 开始）。

        Returns:
            英文视频生成 prompt 字符串。
        """
        if not segment_text or not segment_text.strip():
            return ""

        # 提取角色信息
        character_prompt = ""
        if self._tracker:
            characters = self._tracker.extract_characters(segment_text)
            character_prompt = self._tracker.get_character_prompt(characters)

        # 根据模式生成 prompt
        if self._use_llm:
            prompt = self._generate_video_with_llm(segment_text, character_prompt)
        else:
            prompt = self._generate_video_local(segment_text, character_prompt)

        # 更新角色追踪器
        if self._tracker:
            self._tracker.update(segment_text, prompt)

        log.debug("段 %d video prompt: %s", segment_index, prompt[:80])
        return prompt

    # ------------------------------------------------------------------
    # video prompt - LLM mode
    # ------------------------------------------------------------------

    def _generate_video_with_llm(self, text: str, character_prompt: str) -> str:
        """使用 LLM 生成视频 prompt。"""
        try:
            user_msg = f"小说文本:\n{text}"
            if character_prompt:
                user_msg += f"\n\n已知角色描述（请保持一致）:\n{character_prompt}"
            user_msg += f"\n\n画面风格: {self._style_name}"

            client = self._get_llm_client()
            response = client.chat(
                messages=[
                    {"role": "system", "content": _VIDEO_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=self._temperature,
            )

            raw_prompt = response.content.strip()
            if not raw_prompt:
                log.warning("LLM 返回空视频 prompt，回退到本地模式")
                return self._generate_video_local(text, character_prompt)

            # 附加视频风格关键词
            prompt = self._apply_video_style(raw_prompt)
            return prompt

        except Exception as e:
            log.warning("LLM 视频 prompt 生成失败 (%s)，回退到本地模式", e)
            return self._generate_video_local(text, character_prompt)

    # ------------------------------------------------------------------
    # video prompt - local fallback mode
    # ------------------------------------------------------------------

    def _generate_video_local(self, text: str, character_prompt: str) -> str:
        """使用规则匹配生成视频 prompt（无 API 依赖）。

        在图片 prompt 的场景元素基础上，将其改写为自然语言句子，
        并追加运镜描述和视频画质约束。
        """
        era = self._get_era(text)
        scene_parts = self._extract_scene(text, era)

        parts: list[str] = []

        # 1. 角色 + 场景描述（组装为自然语言句子）
        if character_prompt:
            parts.append(character_prompt)
        if scene_parts:
            parts.append(", ".join(scene_parts))

        # 组装主体描述句
        if parts:
            subject_sentence = ". ".join(p.rstrip(".") for p in parts if p) + "."
        else:
            subject_sentence = "A cinematic scene."

        # 2. 运镜描述
        camera = self._select_camera_movement(text)

        # 3. 视频风格和约束
        video_style = self._preset.get("video_style", "cinematic quality, 4K")
        video_constraints = self._preset.get(
            "video_constraints",
            "stable character appearance, natural smooth movements, no distortion",
        )

        # 拼装完整视频 prompt
        prompt = f"{subject_sentence} {camera}. {video_style}, {video_constraints}."
        return prompt

    @staticmethod
    def _select_camera_movement(text: str) -> str:
        """根据文本情绪/场景自动选择运镜描述。"""
        for pattern, camera_desc in _CAMERA_MOVEMENT_RULES:
            if re.search(pattern, text):
                return camera_desc
        return _DEFAULT_CAMERA

    def _apply_video_style(self, raw_prompt: str) -> str:
        """将视频风格预设关键词附加到 prompt 上。"""
        prompt = raw_prompt.rstrip(". ")

        video_style = self._preset.get("video_style", "")
        video_constraints = self._preset.get("video_constraints", "")

        suffix_parts: list[str] = []
        if video_style:
            suffix_parts.append(video_style)
        if video_constraints:
            suffix_parts.append(video_constraints)

        if suffix_parts:
            prompt += ". " + ", ".join(suffix_parts) + "."

        return prompt

    # ------------------------------------------------------------------
    # era detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_era(text: str) -> str:
        """自动判断文本是现代还是古风。"""
        modern_count = len(re.findall(_MODERN_KEYWORDS, text))
        classical_count = len(re.findall(_CLASSICAL_KEYWORDS, text))
        if modern_count > classical_count:
            return "modern"
        if classical_count > modern_count:
            return "classical"
        # 默认：如果有"他/她"但没有古风特征词，倾向现代
        if re.search(r"手机|电梯|公寓|合租|外卖|办公", text):
            return "modern"
        return "classical"

    def _get_era(self, text: str) -> str:
        """获取时代，优先用缓存的全文判断结果。"""
        if self._era_cache:
            return self._era_cache
        return self._detect_era(text)

    # ------------------------------------------------------------------
    # LLM mode
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_llm_available(llm_cfg: dict) -> bool:
        """检测是否有可用的 LLM provider。"""
        from src.llm import is_llm_available

        return is_llm_available(llm_cfg)

    def _get_llm_client(self):
        """创建或返回缓存的 LLM 客户端实例。"""
        if self._llm_client_cached is None:
            from src.llm import create_llm_client

            self._llm_client_cached = create_llm_client(self._llm_config)
        return self._llm_client_cached

    def _generate_with_llm(self, text: str, character_prompt: str) -> str:
        """使用 LLM 生成高质量 prompt。"""
        try:
            user_msg = f"小说文本:\n{text}"
            if character_prompt:
                user_msg += f"\n\n已知角色描述（请保持一致）:\n{character_prompt}"
            user_msg += f"\n\n画面风格: {self._style_name}"

            client = self._get_llm_client()
            response = client.chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=self._temperature,
            )

            raw_prompt = response.content.strip()
            if not raw_prompt:
                log.warning("LLM 返回空 prompt，回退到本地模式")
                return self._generate_local(text, character_prompt)

            prompt = self._apply_style(raw_prompt)
            return prompt

        except Exception as e:
            log.warning("LLM prompt 生成失败 (%s)，回退到本地模式", e)
            return self._generate_local(text, character_prompt)

    # ------------------------------------------------------------------
    # local fallback mode
    # ------------------------------------------------------------------

    def _generate_local(self, text: str, character_prompt: str) -> str:
        """使用场景规则匹配生成 prompt（无 API 依赖）。"""
        era = self._get_era(text)
        scene_parts = self._extract_scene(text, era)

        parts: list[str] = []

        # 1. 风格前缀
        prefix = self._preset.get("prefix", "")
        if prefix:
            parts.append(prefix)

        # 2. 场景描述
        if scene_parts:
            parts.append(", ".join(scene_parts))

        # 3. 角色追踪描述
        if character_prompt:
            parts.append(character_prompt)

        # 4. 画质提升词
        parts.append("highly detailed, cinematic composition, dramatic lighting")

        # 5. 风格正向关键词
        positive = self._preset.get("positive", "")
        if positive:
            parts.append(positive)

        prompt = ", ".join(parts)
        return prompt

    def _extract_scene(self, text: str, era: str) -> list[str]:
        """从中文文本中提取场景描述，根据时代选择规则集。"""
        found: list[str] = []
        seen: set[str] = set()

        gender = self._detect_gender(text)

        # 选择对应时代的规则
        rules = _MODERN_RULES if era == "modern" else _CLASSICAL_RULES

        for pattern, description in rules:
            if re.search(pattern, text) and description not in seen:
                desc = self._apply_gender(description, gender, era)
                found.append(desc)
                seen.add(description)

        # 如果没匹配到人物，补一个默认人物
        has_person = any(
            kw in desc for desc in found
            for kw in ("person", "figure", "man", "woman", "boy", "girl",
                       "swordsman", "scholar", "general", "elderly",
                       "delivery", "student")
        )
        if not has_person and re.search(r"[他她]|人|者", text):
            if era == "modern":
                if gender == "female":
                    found.insert(0, "a young woman in modern casual clothes, black hair")
                else:
                    found.insert(0, "a young man in modern casual clothes, black hair")
            else:
                if gender == "female":
                    found.insert(0, "a beautiful young woman in traditional Chinese hanfu")
                else:
                    found.insert(0, "a handsome young man in traditional Chinese robes")

        return found[:10]

    @staticmethod
    def _detect_gender(text: str) -> str:
        """从文本中推断主要人物的性别。"""
        female_cues = len(re.findall(r"她|少女|女子|姑娘|小姐|美人|夫人|娘|妹|女孩", text))
        male_cues = len(re.findall(r"他|少年|少侠|公子|大侠|将军|书生|兄|爷|男", text))
        if female_cues > male_cues:
            return "female"
        return "male"

    @staticmethod
    def _apply_gender(description: str, gender: str, era: str) -> str:
        """将描述中的通用人称替换为具体性别。"""
        if era == "modern":
            if gender == "female":
                description = description.replace("a person walking", "a young woman walking")
                description = description.replace("a person standing still", "a young woman standing")
                description = description.replace("a person sitting", "a young woman sitting")
                description = description.replace("a person running", "a young woman running")
                description = description.replace("a delivery person", "a young woman delivery worker")
            else:
                description = description.replace("a person walking", "a young man walking")
                description = description.replace("a person standing still", "a young man standing")
                description = description.replace("a person sitting", "a young man sitting")
                description = description.replace("a person running", "a young man running")
        else:
            if gender == "female":
                description = description.replace("a person walking", "a beautiful woman walking gracefully")
                description = description.replace("a person standing still", "a beautiful woman standing elegantly")
                description = description.replace("a person sitting", "a beautiful woman sitting gracefully")
                description = description.replace("a person running", "a woman running")
                description = description.replace("a swordsman", "a beautiful swordswoman")
                description = description.replace("a young man, handsome", "a beautiful young woman")
                description = description.replace("a cloaked figure, flowing cloak", "a beautiful woman in flowing cloak")
            else:
                description = description.replace("a person walking", "a handsome man walking")
                description = description.replace("a person standing still", "a man standing")
                description = description.replace("a person sitting", "a man sitting")
                description = description.replace("a person running", "a man running")
                description = description.replace("a cloaked figure, flowing cloak", "a man in flowing cloak, broad shoulders")
        return description

    # ------------------------------------------------------------------
    # style helpers
    # ------------------------------------------------------------------

    def _apply_style(self, raw_prompt: str) -> str:
        """将风格预设关键词附加到 prompt 上。"""
        parts = [raw_prompt.rstrip(", ")]

        positive = self._preset.get("positive", "")
        if positive:
            parts.append(positive)

        return ", ".join(parts)
