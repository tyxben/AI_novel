"""AI 小说转视频 - Gradio Web UI"""

import json
import hashlib
import os
from pathlib import Path

# Try loading .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import gradio as gr

# ---------------------------------------------------------------------------
# Settings persistence
# ---------------------------------------------------------------------------
SETTINGS_DIR = Path.home() / ".novel-video"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_settings(settings: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _save_key(key_name: str, value: str) -> None:
    settings = load_settings()
    settings[key_name] = value.strip() if value else ""
    save_settings(settings)


# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------
STYLE_CHOICES = ["动漫风", "写实", "水彩", "水墨", "赛博朋克"]
STYLE_MAP = {
    "动漫风": "anime",
    "写实": "realistic",
    "水彩": "watercolor",
    "水墨": "chinese_ink",
    "赛博朋克": "cyberpunk",
}

VOICE_CHOICES = ["云希-男", "晓晓-女", "云健-男播音"]
VOICE_MAP = {
    "云希-男": "zh-CN-YunxiNeural",
    "晓晓-女": "zh-CN-XiaoxiaoNeural",
    "云健-男播音": "zh-CN-YunjianNeural",
}

RATE_CHOICES = ["慢速", "正常", "快速"]
RATE_MAP = {"慢速": "-20%", "正常": "+0%", "快速": "+20%"}

BACKEND_CHOICES = ["SiliconFlow", "阿里云通义"]
BACKEND_MAP = {
    "SiliconFlow": "siliconflow",
    "阿里云通义": "dashscope",
}

LLM_CHOICES = ["自动检测", "Gemini", "DeepSeek", "OpenAI", "Ollama本地"]
LLM_MAP = {
    "自动检测": "auto",
    "Gemini": "gemini",
    "DeepSeek": "deepseek",
    "OpenAI": "openai",
    "Ollama本地": "ollama",
}

QUALITY_CHOICES = ["标准", "高清", "极致"]
QUALITY_MAP = {"标准": 23, "高清": 18, "极致": 12}

CODEC_CHOICES = ["H.265（推荐）", "H.264（兼容）"]
CODEC_MAP = {"H.265（推荐）": "libx265", "H.264（兼容）": "libx264"}

VIDEO_MODE_CHOICES = ["静态图+特效（免费）", "AI视频片段（付费）"]
VIDEO_MODE_MAP = {
    "静态图+特效（免费）": None,
    "AI视频片段（付费）": True,
}

VIDEOGEN_CHOICES = ["可灵 Kling", "即梦 Seedance", "MiniMax 海螺", "OpenAI Sora"]
VIDEOGEN_MAP = {
    "可灵 Kling": "kling",
    "即梦 Seedance": "seedance",
    "MiniMax 海螺": "minimax",
    "OpenAI Sora": "sora",
}

RESOLUTION_CHOICES = ["竖屏9:16", "横屏16:9", "方形1:1"]
RESOLUTION_MAP = {
    "竖屏9:16": [1080, 1920],
    "横屏16:9": [1920, 1080],
    "方形1:1": [1080, 1080],
}

GENRE_CHOICES = [
    "都市情感", "悬疑推理", "古风仙侠", "科幻未来",
    "校园青春", "民间故事", "恐怖灵异", "搞笑沙雕",
]
GENRE_MAP = {
    "都市情感": "都市情感", "悬疑推理": "悬疑推理",
    "古风仙侠": "古风仙侠", "科幻未来": "科幻未来",
    "校园青春": "校园青春", "民间故事": "民间故事",
    "恐怖灵异": "恐怖灵异", "搞笑沙雕": "搞笑幽默",
}

LENGTH_CHOICES = ["30秒 (~120字)", "60秒 (~250字)", "3分钟 (~700字)"]
LENGTH_MAP = {"30秒 (~120字)": 120, "60秒 (~250字)": 250, "3分钟 (~700字)": 700}


# ---------------------------------------------------------------------------
# CSS theme
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
/* Overall */
.gradio-container {
    max-width: 1200px !important;
    margin: 0 auto !important;
}

/* Header */
.hero-section {
    text-align: center;
    padding: 28px 20px 18px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 16px;
    margin-bottom: 20px;
    box-shadow: 0 4px 20px rgba(102, 126, 234, 0.3);
}
.hero-section h1 {
    color: white !important;
    font-size: 2em !important;
    margin: 0 0 4px 0 !important;
    letter-spacing: 2px;
}
.hero-section p {
    color: rgba(255,255,255,0.85) !important;
    font-size: 1.05em !important;
    margin: 0 !important;
}

/* Cards */
.input-card, .output-card {
    border: 1px solid #e2e8f0 !important;
    border-radius: 12px !important;
    padding: 20px !important;
    background: white !important;
    box-shadow: 0 1px 8px rgba(0,0,0,0.04) !important;
}

/* Generate button glow */
.generate-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    border: none !important;
    font-size: 1.1em !important;
    padding: 12px !important;
    border-radius: 10px !important;
    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4) !important;
    transition: all 0.3s !important;
}
.generate-btn:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5) !important;
}

/* Story button */
.story-btn {
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%) !important;
    border: none !important;
    color: white !important;
    border-radius: 10px !important;
    box-shadow: 0 3px 12px rgba(245, 87, 108, 0.3) !important;
}

/* Section titles */
.section-title {
    font-size: 0.9em !important;
    color: #64748b !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
    margin: 16px 0 8px !important;
    padding-bottom: 6px !important;
    border-bottom: 2px solid #e2e8f0 !important;
}

/* Settings accordion */
.settings-panel {
    border-radius: 12px !important;
    margin-top: 16px !important;
}

/* Status badge area */
.status-area {
    border-radius: 8px !important;
    background: #f8fafc !important;
}

/* Tab styling */
.tabs .tab-nav button {
    font-weight: 600 !important;
}
"""


# ---------------------------------------------------------------------------
# AI Story generation
# ---------------------------------------------------------------------------
_STORY_SYSTEM_PROMPT = """你是一个专业的短视频故事写手，专门为抖音/小红书创作30-60秒的短故事。

核心要求：
- 第一句话就要制造悬念或冲突，让人停不下来（"黄金3秒"法则）
- 故事极度紧凑，没有废话，每一句都在推进剧情
- 场景描写简洁但有画面感（每段都会配一张AI生成的插图）
- 结尾必须有反转、意外或让人回味的余韵
- 适合用旁白+配图的形式呈现，不要大段对话
- 直接输出故事正文，不要标题、不要作者、不要额外说明
- 严格控制字数，不要超出要求"""


def _get_llm_client(llm_backend: str, key_gemini: str, key_deepseek: str, key_openai: str):
    """设置环境变量并创建 LLM client。"""
    env_map = {
        "GEMINI_API_KEY": key_gemini,
        "DEEPSEEK_API_KEY": key_deepseek,
        "OPENAI_API_KEY": key_openai,
    }
    for k, v in env_map.items():
        if v and v.strip():
            os.environ[k] = v.strip()

    from src.llm.llm_client import create_llm_client

    llm_provider = LLM_MAP.get(llm_backend, "auto")
    try:
        return create_llm_client({"provider": llm_provider})
    except RuntimeError as e:
        raise gr.Error(f"无法连接 LLM: {e}\n请在「配置 AI 服务」中设置 API Key。")


def generate_story(
    topic: str,
    genre: str,
    length: str,
    system_prompt: str,
    llm_backend: str,
    key_gemini: str,
    key_deepseek: str,
    key_openai: str,
):
    """用 AI 生成小说故事。"""
    if not topic or not topic.strip():
        raise gr.Error("请输入故事主题或想法")

    client = _get_llm_client(llm_backend, key_gemini, key_deepseek, key_openai)
    target_len = LENGTH_MAP.get(length, 600)
    genre_name = GENRE_MAP.get(genre, "都市情感")

    sys_prompt = system_prompt.strip() if system_prompt and system_prompt.strip() else _STORY_SYSTEM_PROMPT

    user_prompt = (
        f"请写一个{genre_name}类型的短视频故事，严格控制在{target_len}字左右。\n"
        f"主题/灵感: {topic.strip()}\n\n"
        f"这个故事会被做成抖音/小红书的短视频（配图+旁白），"
        f"所以每2-3句话就是一个画面，请让每个场景都有强画面感。"
    )

    try:
        resp = client.chat(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.85,
        )
    except Exception as e:
        raise gr.Error(f"故事生成失败: {e}")

    story = resp.content.strip()
    gr.Info(f"故事生成完成！（{len(story)} 字）")
    return story


def refine_story(
    current_text: str,
    feedback: str,
    system_prompt: str,
    llm_backend: str,
    key_gemini: str,
    key_deepseek: str,
    key_openai: str,
):
    """基于用户反馈优化已有故事。"""
    if not current_text or not current_text.strip():
        raise gr.Error("没有可优化的故事，请先生成或粘贴故事文本")
    if not feedback or not feedback.strip():
        raise gr.Error("请输入你的优化意见，例如「结尾不够惊艳」「节奏太慢」「加点悬疑感」")

    client = _get_llm_client(llm_backend, key_gemini, key_deepseek, key_openai)
    sys_prompt = system_prompt.strip() if system_prompt and system_prompt.strip() else _STORY_SYSTEM_PROMPT

    user_prompt = (
        f"下面是一个已有的短视频故事：\n\n"
        f"---\n{current_text.strip()}\n---\n\n"
        f"请根据以下反馈优化这个故事：\n{feedback.strip()}\n\n"
        f"要求：\n"
        f"- 保持故事的核心主题和人物不变\n"
        f"- 按照反馈意见针对性修改\n"
        f"- 保持字数大致不变（当前 {len(current_text.strip())} 字）\n"
        f"- 直接输出优化后的完整故事，不要解释修改了什么"
    )

    try:
        resp = client.chat(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )
    except Exception as e:
        raise gr.Error(f"优化失败: {e}")

    story = resp.content.strip()
    gr.Info(f"故事已优化！（{len(story)} 字）")
    return story


# ---------------------------------------------------------------------------
# API key connection test
# ---------------------------------------------------------------------------
def _test_api_key(name: str, url: str, key: str, auth_style: str = "bearer") -> None:
    if not key or not key.strip():
        raise gr.Error(f"请先输入 {name} API Key")
    try:
        import urllib.request
        if auth_style == "query":
            req = urllib.request.Request(url + key.strip())
        else:
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {key.strip()}"}
            )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                gr.Info(f"{name} 连接成功")
                return
            raise gr.Error(f"{name} 返回状态码: {resp.status}")
    except gr.Error:
        raise
    except Exception as e:
        raise gr.Error(f"{name} 连接失败: {e}")


def _test_siliconflow(key):
    _test_api_key("SiliconFlow", "https://api.siliconflow.cn/v1/models", key)

def _test_gemini(key):
    _test_api_key("Gemini", "https://generativelanguage.googleapis.com/v1beta/models?key=", key, "query")

def _test_deepseek(key):
    _test_api_key("DeepSeek", "https://api.deepseek.com/v1/models", key)

def _test_openai(key):
    _test_api_key("OpenAI", "https://api.openai.com/v1/models", key)

def _test_dashscope(key):
    _test_api_key("DashScope", "https://dashscope.aliyuncs.com/api/v1/models", key)


# ---------------------------------------------------------------------------
# Main video generation
# ---------------------------------------------------------------------------
def generate(
    text, file, style, voice, rate,
    image_backend, llm_backend, quality, resolution, codec,
    video_mode, videogen_backend,
    key_siliconflow, key_gemini, key_deepseek, key_openai, key_dashscope,
    key_kling, key_jimeng, key_minimax,
    progress=gr.Progress(),
):
    # 1. Resolve input text
    if file is not None:
        novel_text = Path(file).read_text(encoding="utf-8")
    elif text and text.strip():
        novel_text = text.strip()
    else:
        raise gr.Error("请先输入或生成故事文本")

    if len(novel_text) < 10:
        raise gr.Error("文本内容太短，请输入至少 10 个字符")

    # 2. Write to input file
    input_dir = Path("input")
    input_dir.mkdir(exist_ok=True)
    text_hash = hashlib.md5(novel_text.encode()).hexdigest()[:8]
    input_file = input_dir / f"web_{text_hash}.txt"
    input_file.write_text(novel_text, encoding="utf-8")

    # 3. Set API keys
    env_map = {
        "SILICONFLOW_API_KEY": key_siliconflow,
        "GEMINI_API_KEY": key_gemini,
        "DEEPSEEK_API_KEY": key_deepseek,
        "OPENAI_API_KEY": key_openai,
        "DASHSCOPE_API_KEY": key_dashscope,
        "KLING_API_KEY": key_kling,
        "JIMENG_API_KEY": key_jimeng,
        "MINIMAX_API_KEY": key_minimax,
    }
    for k, v in env_map.items():
        if v and v.strip():
            os.environ[k] = v.strip()

    # 4. Build config overrides
    voice_id = VOICE_MAP.get(voice, "zh-CN-YunxiNeural")
    config = {
        "promptgen": {"style": STYLE_MAP.get(style, "anime")},
        "tts": {"voice": voice_id, "rate": RATE_MAP.get(rate, "+0%")},
        "imagegen": {"backend": BACKEND_MAP.get(image_backend, "siliconflow")},
        "llm": {"provider": LLM_MAP.get(llm_backend, "auto")},
        "video": {
            "codec": CODEC_MAP.get(codec, "libx265"),
            "crf": QUALITY_MAP.get(quality, 18),
            "resolution": RESOLUTION_MAP.get(resolution, [1080, 1920]),
        },
    }

    # 4b. Add videogen config if AI video mode is selected
    if VIDEO_MODE_MAP.get(video_mode):
        vg_backend = VIDEOGEN_MAP.get(videogen_backend, "kling")
        config["videogen"] = {
            "backend": vg_backend,
            "duration": 5,
            "aspect_ratio": "9:16",
            "use_image_as_first_frame": True,
        }

    # 5. Run pipeline
    from src.pipeline import Pipeline

    progress(0, desc="正在初始化...")

    def progress_cb(stage, total, desc):
        progress(stage / total if total > 0 else 0, desc=f"阶段 {stage}/{total}: {desc}")

    try:
        pipe = Pipeline(input_file=input_file, config=config, resume=False)
        output = pipe.run(progress_callback=progress_cb)
    except Exception as e:
        raise gr.Error(f"生成失败: {e}")

    output_path = str(output)
    return (
        f"生成完成!\n输出文件: {output_path}",
        output_path,
        output_path,
    )


# ---------------------------------------------------------------------------
# Quick config helpers
# ---------------------------------------------------------------------------
# Maps quick-radio labels → advanced dropdown labels (must match LLM_CHOICES exactly)
_QUICK_LLM_TO_DROPDOWN = {
    "Gemini（免费推荐）": "Gemini",
    "DeepSeek": "DeepSeek",
    "OpenAI": "OpenAI",
    "Ollama（本地免费）": "Ollama本地",
}
# Maps quick-radio labels → advanced dropdown labels (must match BACKEND_CHOICES exactly)
_QUICK_IMG_TO_DROPDOWN = {
    "SiliconFlow": "SiliconFlow",
    "阿里云通义": "阿里云通义",
}
# Maps quick-radio labels → pipeline config values
_QUICK_LLM_TO_PROVIDER = {
    "Gemini（免费推荐）": "gemini",
    "DeepSeek": "deepseek",
    "OpenAI": "openai",
    "Ollama（本地免费）": "ollama",
}
_QUICK_IMG_TO_BACKEND = {
    "SiliconFlow": "siliconflow",
    "阿里云通义": "dashscope",
}


def _detect_quick_llm(settings: dict) -> str:
    """根据已保存的 Key 推断默认 LLM 选择。"""
    if settings.get("key_gemini"):
        return "Gemini（免费推荐）"
    if settings.get("key_deepseek"):
        return "DeepSeek"
    if settings.get("key_openai"):
        return "OpenAI"
    return "Gemini（免费推荐）"


def _detect_quick_img(settings: dict) -> str:
    """根据已保存的 Key 推断默认图片服务选择。"""
    if settings.get("key_siliconflow"):
        return "SiliconFlow"
    if settings.get("key_dashscope"):
        return "阿里云通义"
    return "SiliconFlow"


# ---------------------------------------------------------------------------
# Build Gradio UI
# ---------------------------------------------------------------------------
def create_ui() -> gr.Blocks:
    settings = load_settings()

    with gr.Blocks(title="AI 小说转视频") as app:

        # ====== Hero header ======
        gr.HTML("""
        <div class="hero-section">
            <h1>AI 短视频故事</h1>
            <p>一句灵感 → AI 写故事 → 自动配图配音 → 生成抖音/小红书短视频</p>
        </div>
        """)

        with gr.Row(equal_height=False):
            # ============== Left column: Input ==============
            with gr.Column(scale=5, elem_classes="input-card"):
                with gr.Tabs() as input_tabs:
                    # --- Tab 1: AI 写故事 ---
                    with gr.Tab("AI 写故事", id="tab_ai"):
                        topic_input = gr.Textbox(
                            label="你的灵感 / 故事主题",
                            placeholder="例: 深夜加班的程序员在电梯里遇到了三年前去世的同事...",
                            lines=2,
                        )
                        with gr.Row():
                            genre_dropdown = gr.Dropdown(
                                label="类型",
                                choices=GENRE_CHOICES,
                                value="都市情感",
                                scale=1,
                            )
                            length_dropdown = gr.Dropdown(
                                label="视频时长",
                                choices=LENGTH_CHOICES,
                                value="60秒 (~250字)",
                                scale=1,
                            )
                        # 快捷服务配置
                        _has_any_key = any(settings.get(k) for k in ["key_gemini", "key_deepseek", "key_openai", "key_siliconflow"])
                        _default_llm = _detect_quick_llm(settings)
                        _default_img = _detect_quick_img(settings)
                        with gr.Accordion("配置 AI 服务（首次需设置）", open=not _has_any_key):
                            # -- LLM 选择 --
                            gr.Markdown("**写故事用的 AI（LLM）**")
                            quick_llm = gr.Radio(
                                label="选择 LLM 服务",
                                choices=["Gemini（免费推荐）", "DeepSeek", "OpenAI", "Ollama（本地免费）"],
                                value=_default_llm,
                            )
                            # Single key field that changes label/value based on selection
                            _llm_key_map = {
                                "Gemini（免费推荐）": ("key_gemini", "Gemini API Key", "去 aistudio.google.com/apikey 免费申请"),
                                "DeepSeek": ("key_deepseek", "DeepSeek API Key", "sk-..."),
                                "OpenAI": ("key_openai", "OpenAI API Key", "sk-..."),
                            }
                            _init_llm_key = _llm_key_map.get(_default_llm, ("", "", ""))
                            _is_ollama = _default_llm == "Ollama（本地免费）"
                            quick_llm_key = gr.Textbox(
                                label=_init_llm_key[1] if not _is_ollama else "API Key",
                                type="password",
                                value=settings.get(_init_llm_key[0], "") if not _is_ollama else "",
                                placeholder=_init_llm_key[2] if not _is_ollama else "",
                                visible=not _is_ollama,
                            )
                            quick_llm_hint = gr.Markdown(
                                "Ollama 运行在本地，无需 Key。请确保已启动 ollama serve。",
                                visible=_is_ollama,
                            )

                            gr.Markdown("---")

                            # -- 图片生成选择 --
                            gr.Markdown("**生成图片用的服务**")
                            quick_img = gr.Radio(
                                label="选择图片服务",
                                choices=["SiliconFlow", "阿里云通义"],
                                value=_default_img,
                            )
                            _img_key_map = {
                                "SiliconFlow": ("key_siliconflow", "SiliconFlow API Key", "sk-..."),
                                "阿里云通义": ("key_dashscope", "阿里云 DashScope API Key", "sk-..."),
                            }
                            _init_img_key = _img_key_map.get(_default_img, ("", "", ""))
                            quick_img_key = gr.Textbox(
                                label=_init_img_key[1] if _init_img_key[1] else "API Key",
                                type="password",
                                value=settings.get(_init_img_key[0], "") if _init_img_key[0] else "",
                                placeholder=_init_img_key[2] if _init_img_key[2] else "",
                            )
                        with gr.Accordion("自定义提示词", open=False):
                            system_prompt_input = gr.Textbox(
                                label="系统提示词（控制 AI 写作风格）",
                                value=_STORY_SYSTEM_PROMPT,
                                lines=6,
                                max_lines=15,
                                placeholder="在这里修改 AI 的写作指令...",
                            )
                            gr.Markdown("*修改后对「生成」和「优化」都生效。留空则使用默认提示词。*")
                        story_btn = gr.Button(
                            "AI 生成故事",
                            variant="secondary",
                            size="lg",
                            elem_classes="story-btn",
                        )

                    # --- Tab 2: 已有文本 ---
                    with gr.Tab("上传/粘贴文本", id="tab_upload"):
                        file_input = gr.File(
                            label="上传 TXT 文件",
                            file_types=[".txt"],
                            type="filepath",
                        )

                # 共享文本区
                txt_input = gr.Textbox(
                    label="故事文本",
                    placeholder="AI 生成的故事会显示在这里，也可以直接粘贴或编辑...",
                    lines=10,
                    max_lines=25,
                )
                # 优化区：基于现有文本迭代改进
                with gr.Row():
                    refine_input = gr.Textbox(
                        label="优化意见",
                        placeholder="例: 结尾不够惊艳 / 节奏太慢 / 加点悬疑感 / 对话太多了...",
                        lines=1,
                        scale=4,
                    )
                    refine_btn = gr.Button("优化故事", variant="secondary", scale=1)

                gr.HTML('<div class="section-title">视频风格</div>')
                with gr.Row():
                    style_dropdown = gr.Dropdown(
                        label="画面风格", choices=STYLE_CHOICES, value="动漫风", scale=1,
                    )
                    voice_dropdown = gr.Dropdown(
                        label="配音", choices=VOICE_CHOICES, value="云希-男", scale=1,
                    )
                    rate_radio = gr.Radio(
                        label="语速", choices=RATE_CHOICES, value="正常", scale=1,
                    )

                gr.HTML('<div class="section-title">画面模式</div>')
                with gr.Row():
                    video_mode = gr.Radio(
                        label="画面生成方式",
                        choices=VIDEO_MODE_CHOICES,
                        value="静态图+特效（免费）",
                        scale=2,
                    )
                    videogen_backend = gr.Dropdown(
                        label="视频生成服务",
                        choices=VIDEOGEN_CHOICES,
                        value="可灵 Kling",
                        visible=False,
                        scale=1,
                    )

                def _on_video_mode_change(mode):
                    return gr.update(visible=VIDEO_MODE_MAP.get(mode) is not None)
                video_mode.change(
                    fn=_on_video_mode_change, inputs=[video_mode],
                    outputs=[videogen_backend],
                )

                generate_btn = gr.Button(
                    "生成视频",
                    variant="primary",
                    size="lg",
                    elem_classes="generate-btn",
                )

            # ============== Right column: Output ==============
            with gr.Column(scale=4, elem_classes="output-card"):
                gr.HTML('<div class="section-title">输出</div>')
                status_box = gr.Textbox(
                    label="当前状态",
                    interactive=False,
                    lines=3,
                    elem_classes="status-area",
                )
                video_output = gr.Video(label="视频预览", height=400)
                file_output = gr.File(label="下载视频")

        # ============== Advanced settings ==============
        with gr.Accordion("高级设置", open=False, elem_classes="settings-panel"):
            with gr.Row():
                with gr.Column():
                    gr.HTML('<div class="section-title">API 密钥</div>')
                    gr.Markdown(
                        "密钥自动保存到本地，不会上传到任何服务器。"
                    )
                    with gr.Group():
                        with gr.Row():
                            key_siliconflow = gr.Textbox(
                                label="SiliconFlow",
                                type="password",
                                value=settings.get("key_siliconflow", ""),
                                placeholder="sk-...",
                                scale=4,
                            )
                            btn_test_sf = gr.Button("测试", size="sm", scale=1)
                        with gr.Row():
                            key_gemini = gr.Textbox(
                                label="Gemini",
                                type="password",
                                value=settings.get("key_gemini", ""),
                                placeholder="AIza...",
                                scale=4,
                            )
                            btn_test_gemini = gr.Button("测试", size="sm", scale=1)
                        with gr.Row():
                            key_deepseek = gr.Textbox(
                                label="DeepSeek",
                                type="password",
                                value=settings.get("key_deepseek", ""),
                                placeholder="sk-...",
                                scale=4,
                            )
                            btn_test_ds = gr.Button("测试", size="sm", scale=1)
                        with gr.Row():
                            key_openai = gr.Textbox(
                                label="OpenAI",
                                type="password",
                                value=settings.get("key_openai", ""),
                                placeholder="sk-...",
                                scale=4,
                            )
                            btn_test_openai = gr.Button("测试", size="sm", scale=1)
                        with gr.Row():
                            key_dashscope = gr.Textbox(
                                label="阿里云 DashScope",
                                type="password",
                                value=settings.get("key_dashscope", ""),
                                placeholder="sk-...",
                                scale=4,
                            )
                            btn_test_dashscope = gr.Button("测试", size="sm", scale=1)

                with gr.Column():
                    gr.HTML('<div class="section-title">视频生成 API 密钥</div>')
                    gr.Markdown("AI 视频片段模式需要以下服务的 Key（按需配置）。")
                    with gr.Group():
                        key_kling = gr.Textbox(
                            label="可灵 Kling",
                            type="password",
                            value=settings.get("key_kling", ""),
                            placeholder="API Key",
                        )
                        key_jimeng = gr.Textbox(
                            label="即梦 Seedance",
                            type="password",
                            value=settings.get("key_jimeng", ""),
                            placeholder="API Key",
                        )
                        key_minimax = gr.Textbox(
                            label="MiniMax 海螺",
                            type="password",
                            value=settings.get("key_minimax", ""),
                            placeholder="API Key",
                        )

                with gr.Column():
                    gr.HTML('<div class="section-title">后端 & 画质</div>')
                    image_backend = gr.Dropdown(
                        label="图片生成后端",
                        choices=BACKEND_CHOICES,
                        value=_QUICK_IMG_TO_DROPDOWN.get(_default_img, "SiliconFlow"),
                    )
                    llm_backend = gr.Dropdown(
                        label="LLM 后端",
                        choices=LLM_CHOICES,
                        value=_QUICK_LLM_TO_DROPDOWN.get(_default_llm, "自动检测"),
                    )
                    quality_radio = gr.Radio(
                        label="画质",
                        choices=QUALITY_CHOICES,
                        value="高清",
                    )
                    resolution_radio = gr.Radio(
                        label="分辨率",
                        choices=RESOLUTION_CHOICES,
                        value="竖屏9:16",
                    )
                    codec_radio = gr.Radio(
                        label="视频编码",
                        choices=CODEC_CHOICES,
                        value="H.265（推荐）",
                    )

        # ====== Event wiring ======
        # Auto-save keys (advanced panel)
        for key_comp, key_name in [
            (key_siliconflow, "key_siliconflow"),
            (key_gemini, "key_gemini"),
            (key_deepseek, "key_deepseek"),
            (key_openai, "key_openai"),
            (key_dashscope, "key_dashscope"),
            (key_kling, "key_kling"),
            (key_jimeng, "key_jimeng"),
            (key_minimax, "key_minimax"),
        ]:
            key_comp.change(fn=lambda v, n=key_name: _save_key(n, v), inputs=[key_comp])

        # -- Quick LLM radio: swap single key field label/value + toggle hint --
        _llm_key_info = {
            "Gemini（免费推荐）": ("key_gemini", "Gemini API Key", "去 aistudio.google.com/apikey 免费申请"),
            "DeepSeek": ("key_deepseek", "DeepSeek API Key", "sk-..."),
            "OpenAI": ("key_openai", "OpenAI API Key", "sk-..."),
        }

        def _on_llm_select(choice):
            is_ollama = choice == "Ollama（本地免费）"
            if is_ollama:
                return (
                    gr.update(visible=False),
                    gr.update(visible=True),
                    _QUICK_LLM_TO_DROPDOWN.get(choice, "自动检测"),
                )
            info = _llm_key_info[choice]
            saved_val = load_settings().get(info[0], "")
            return (
                gr.update(visible=True, label=info[1], placeholder=info[2], value=saved_val),
                gr.update(visible=False),
                _QUICK_LLM_TO_DROPDOWN.get(choice, "自动检测"),
            )
        quick_llm.change(
            fn=_on_llm_select, inputs=[quick_llm],
            outputs=[quick_llm_key, quick_llm_hint, llm_backend],
        )

        # -- Quick image radio: swap single key field label/value + toggle hint --
        _img_key_info = {
            "SiliconFlow": ("key_siliconflow", "SiliconFlow API Key", "sk-..."),
            "阿里云通义": ("key_dashscope", "阿里云 DashScope API Key", "sk-..."),
        }

        def _on_img_select(choice):
            info = _img_key_info[choice]
            saved_val = load_settings().get(info[0], "")
            return (
                gr.update(label=info[1], placeholder=info[2], value=saved_val),
                _QUICK_IMG_TO_DROPDOWN.get(choice, "SiliconFlow"),
            )
        quick_img.change(
            fn=_on_img_select, inputs=[quick_img],
            outputs=[quick_img_key, image_backend],
        )

        # -- Save quick keys on change + sync to advanced panel --
        def _on_llm_key_change(value, llm_choice):
            info = _llm_key_info.get(llm_choice)
            if info:
                _save_key(info[0], value)
            return value  # sync to corresponding advanced key field
        # We need a mapping function that routes to the right advanced key
        def _sync_llm_key_to_adv(value, llm_choice):
            info = _llm_key_info.get(llm_choice)
            if not info:
                return gr.update(), gr.update(), gr.update()
            key_name = info[0]
            _save_key(key_name, value)
            return (
                gr.update(value=value) if key_name == "key_gemini" else gr.update(),
                gr.update(value=value) if key_name == "key_deepseek" else gr.update(),
                gr.update(value=value) if key_name == "key_openai" else gr.update(),
            )
        quick_llm_key.change(
            fn=_sync_llm_key_to_adv,
            inputs=[quick_llm_key, quick_llm],
            outputs=[key_gemini, key_deepseek, key_openai],
        )

        def _sync_img_key_to_adv(value, img_choice):
            info = _img_key_info.get(img_choice)
            if not info:
                return gr.update(), gr.update()
            key_name = info[0]
            _save_key(key_name, value)
            return (
                gr.update(value=value) if key_name == "key_siliconflow" else gr.update(),
                gr.update(value=value) if key_name == "key_dashscope" else gr.update(),
            )
        quick_img_key.change(
            fn=_sync_img_key_to_adv,
            inputs=[quick_img_key, quick_img],
            outputs=[key_siliconflow, key_dashscope],
        )

        # Test buttons
        btn_test_sf.click(fn=_test_siliconflow, inputs=[key_siliconflow])
        btn_test_gemini.click(fn=_test_gemini, inputs=[key_gemini])
        btn_test_ds.click(fn=_test_deepseek, inputs=[key_deepseek])
        btn_test_openai.click(fn=_test_openai, inputs=[key_openai])
        btn_test_dashscope.click(fn=_test_dashscope, inputs=[key_dashscope])

        # AI story generation (reads from quick keys + advanced panel)
        story_btn.click(
            fn=generate_story,
            inputs=[
                topic_input, genre_dropdown, length_dropdown,
                system_prompt_input,
                llm_backend, key_gemini, key_deepseek, key_openai,
            ],
            outputs=[txt_input],
        )

        # Story refinement (iterate on existing text)
        refine_btn.click(
            fn=refine_story,
            inputs=[
                txt_input, refine_input, system_prompt_input,
                llm_backend, key_gemini, key_deepseek, key_openai,
            ],
            outputs=[txt_input],
        )

        # Video generation
        generate_btn.click(
            fn=generate,
            inputs=[
                txt_input, file_input,
                style_dropdown, voice_dropdown, rate_radio,
                image_backend, llm_backend, quality_radio, resolution_radio, codec_radio,
                video_mode, videogen_backend,
                key_siliconflow, key_gemini, key_deepseek, key_openai, key_dashscope,
                key_kling, key_jimeng, key_minimax,
            ],
            outputs=[status_box, video_output, file_output],
        )

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = create_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
        theme=gr.themes.Soft(
            primary_hue=gr.themes.colors.purple,
            secondary_hue=gr.themes.colors.pink,
            neutral_hue=gr.themes.colors.slate,
            font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
        ),
        css=CUSTOM_CSS,
    )
