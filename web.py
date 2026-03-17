"""AI 创作工坊 - Gradio Web UI (短视频制作 + AI 小说)"""

import json
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

# Try loading .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import gradio as gr
from src.task_queue.client import TaskClient

_task_client = TaskClient()


def _ensure_task_server():
    """Start the task queue server if not already running."""
    if _task_client.is_server_running():
        return True
    try:
        log_dir = Path.home() / ".novel-video"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_dir / "server.log", "a")
        subprocess.Popen(
            [sys.executable, "-m", "src.task_queue.server"],
            start_new_session=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        # Wait briefly for server to start
        for _ in range(10):
            time.sleep(0.5)
            if _task_client.is_server_running():
                return True
        return False
    except Exception:
        return False


def _collect_keys_dict(
    key_gemini="", key_deepseek="", key_openai="",
    key_siliconflow="", key_dashscope="",
    key_kling="", key_jimeng="", key_minimax="",
) -> dict:
    """Build _keys dict for task queue from key values."""
    keys = {}
    mapping = {
        "GEMINI_API_KEY": key_gemini,
        "DEEPSEEK_API_KEY": key_deepseek,
        "OPENAI_API_KEY": key_openai,
        "SILICONFLOW_API_KEY": key_siliconflow,
        "DASHSCOPE_API_KEY": key_dashscope,
        "KLING_API_KEY": key_kling,
        "JIMENG_API_KEY": key_jimeng,
        "MINIMAX_API_KEY": key_minimax,
    }
    for env_key, val in mapping.items():
        if val and val.strip():
            keys[env_key] = val.strip()
    return keys

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

# Agent 模式阶段映射
RUN_MODE_CHOICES = ["经典模式（快速）", "Agent模式（智能质控）"]
AGENT_STAGES = {1: "导演分析", 2: "内容解析", 3: "图片生成", 4: "配音合成", 5: "视频编辑"}

# Novel writing module mapping tables
NOVEL_GENRE_CHOICES = ["都市", "玄幻", "武侠", "科幻", "言情", "悬疑", "轻小说", "历史"]
NOVEL_GENRE_MAP = {g: g for g in NOVEL_GENRE_CHOICES}

NOVEL_WORDS_CHOICES = ["5万字", "10万字", "20万字", "50万字"]  # kept for reference
NOVEL_WORDS_MAP = {
    "5万字": 50000,
    "10万字": 100000,
    "20万字": 200000,
    "50万字": 500000,
}

NOVEL_STYLE_CHOICES = ["网文爽文", "武侠古典", "轻小说"]
NOVEL_STYLE_MAP = {
    "网文爽文": "webnovel.shuangwen",
    "武侠古典": "wuxia.classical",
    "轻小说": "lightnovel",
}

NOVEL_TEMPLATE_CHOICES = [
    "循环升级（玄幻/系统流）",
    "多线交织（群像/悬疑/宫斗）",
    "经典四幕（武侠/言情/文学）",
    "自定义（在下方描述）",
]
NOVEL_TEMPLATE_MAP = {
    "循环升级（玄幻/系统流）": "cyclic_upgrade",
    "多线交织（群像/悬疑/宫斗）": "multi_thread",
    "经典四幕（武侠/言情/文学）": "classic_four_act",
    "自定义（在下方描述）": "",
}


# ---------------------------------------------------------------------------
# CSS theme
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
/* Overall — full width */
.gradio-container {
    max-width: 100% !important;
    padding: 0 24px !important;
}

/* Header */
.hero-section {
    text-align: center;
    padding: 24px 20px 16px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 14px;
    margin-bottom: 16px;
    box-shadow: 0 4px 20px rgba(102, 126, 234, 0.3);
}
.hero-section h1 {
    color: white !important;
    font-size: 1.8em !important;
    margin: 0 0 4px 0 !important;
    letter-spacing: 2px;
}
.hero-section p {
    color: rgba(255,255,255,0.85) !important;
    font-size: 1em !important;
    margin: 0 !important;
}

/* Cards — unified for all tabs */
.input-card, .output-card {
    border: 1px solid #e2e8f0 !important;
    border-radius: 12px !important;
    padding: 20px !important;
    background: white !important;
    box-shadow: 0 1px 8px rgba(0,0,0,0.04) !important;
    min-height: 500px !important;
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

/* Story / secondary action button */
.story-btn {
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%) !important;
    border: none !important;
    color: white !important;
    border-radius: 10px !important;
    box-shadow: 0 3px 12px rgba(245, 87, 108, 0.3) !important;
}

/* Section titles — unified divider style */
.section-title {
    font-size: 0.85em !important;
    color: #64748b !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
    margin: 18px 0 10px !important;
    padding-bottom: 6px !important;
    border-bottom: 2px solid #e2e8f0 !important;
}
/* First section title in a card — no top margin */
.input-card > .section-title:first-child,
.output-card > .section-title:first-child {
    margin-top: 0 !important;
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

/* Service selector hint */
.service-hint {
    font-size: 0.85em !important;
    color: #94a3b8 !important;
    margin-top: 2px !important;
}

/* Inner tab styling — consistent across all tabs */
.tabs .tab-nav button {
    font-weight: 600 !important;
}

/* Novel page green button */
.novel-btn {
    background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%) !important;
    border: none !important;
    color: #1a1a2e !important;
    font-size: 1.1em !important;
    font-weight: 600 !important;
    padding: 12px !important;
    border-radius: 10px !important;
    box-shadow: 0 4px 15px rgba(67, 233, 123, 0.35) !important;
    transition: all 0.3s !important;
}
.novel-btn:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(67, 233, 123, 0.5) !important;
}

/* Top-level tabs — centered, prominent */
.top-tabs > .tab-nav {
    justify-content: center !important;
    gap: 8px !important;
}
.top-tabs > .tab-nav button {
    font-size: 1.15em !important;
    font-weight: 700 !important;
    padding: 10px 32px !important;
    border-radius: 8px 8px 0 0 !important;
}

/* Hint text */
.hint-text {
    font-size: 0.85em !important;
    color: #94a3b8 !important;
}

/* Fix dropdown z-index */
ul.options {
    z-index: 9999 !important;
}
"""


DROPDOWN_FIX_HEAD = """
<script>
// Fix Gradio dropdown positioning on scroll/open. The option list
// uses position: fixed, but its coordinates can become stale after
// scrolling containers or after the DOM rerenders.
(function() {
    if (window.__gradioDropdownFixInstalled) return;
    window.__gradioDropdownFixInstalled = true;

    var rafId = null;

    function isVisibleList(ul) {
        if (!ul || ul.classList.contains('hide')) return false;
        var style = window.getComputedStyle(ul);
        return style.display !== 'none' && style.visibility !== 'hidden';
    }

    function getAnchorWrap(ul) {
        var container = ul.parentElement;
        if (container && container.classList && container.classList.contains('wrap')) {
            return container;
        }

        var sibling = ul.previousElementSibling;
        while (sibling) {
            if (sibling.classList && sibling.classList.contains('wrap')) {
                return sibling;
            }
            sibling = sibling.previousElementSibling;
        }

        if (!container) return null;

        for (var i = 0; i < container.children.length; i++) {
            var child = container.children[i];
            if (child.classList && child.classList.contains('wrap')) {
                return child;
            }
        }

        return container.querySelector('.wrap');
    }

    function repositionDropdown(ul) {
        if (!isVisibleList(ul)) return;

        var wrap = getAnchorWrap(ul);
        if (!wrap) return;

        var rect = wrap.getBoundingClientRect();
        var listHeight = ul.offsetHeight || ul.scrollHeight || 0;
        var gutter = 4;
        var top = rect.bottom + gutter;
        var left = Math.max(gutter, rect.left);
        var width = Math.min(rect.width, window.innerWidth - left - gutter);

        if (rect.bottom + listHeight + gutter > window.innerHeight && rect.top > listHeight) {
            top = Math.max(gutter, rect.top - listHeight - gutter);
        }

        ul.style.position = 'fixed';
        ul.style.top = top + 'px';
        ul.style.left = left + 'px';
        ul.style.bottom = 'auto';
        ul.style.right = 'auto';
        ul.style.width = Math.max(width, 0) + 'px';
    }

    function repositionDropdowns() {
        document.querySelectorAll('ul.options').forEach(repositionDropdown);
    }

    function scheduleReposition() {
        if (rafId !== null) return;
        rafId = window.requestAnimationFrame(function() {
            rafId = null;
            repositionDropdowns();
        });
    }

    window.addEventListener('scroll', scheduleReposition, true);
    window.addEventListener('resize', scheduleReposition, true);
    document.addEventListener('click', scheduleReposition, true);
    document.addEventListener('focusin', scheduleReposition, true);
    document.addEventListener('pointerdown', scheduleReposition, true);

    var observer = new MutationObserver(scheduleReposition);
    observer.observe(document.body, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ['class', 'style'],
    });

    window.addEventListener('load', scheduleReposition);
    scheduleReposition();
})();
</script>
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
        gr.Warning("请输入故事主题或想法")
        return ""

    try:
        client = _get_llm_client(llm_backend, key_gemini, key_deepseek, key_openai)
    except gr.Error:
        return ""
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
        gr.Warning(f"故事生成失败: {e}")
        return ""

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
        gr.Warning("没有可优化的故事，请先生成或粘贴故事文本")
        return current_text or ""
    if not feedback or not feedback.strip():
        gr.Warning("请输入优化意见，例如「结尾不够惊艳」「节奏太慢」「加点悬疑感」")
        return current_text

    try:
        client = _get_llm_client(llm_backend, key_gemini, key_deepseek, key_openai)
    except gr.Error:
        return current_text
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
        gr.Warning(f"优化失败: {e}")
        return current_text

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
# Agent 结果加载
# ---------------------------------------------------------------------------
def _load_agent_results(workspace_path: str) -> tuple:
    """加载 Agent 模式生成的分析结果、决策日志和质量报告。

    Returns:
        (analysis_markdown, image_paths, decisions_json, quality_markdown)
    """
    workspace = Path(workspace_path)

    # --- 内容分析 (从 agent_state.json) ---
    analysis_md = ""
    state_file = workspace / "agent_state.json"
    if state_file.exists():
        try:
            state_data = json.loads(state_file.read_text(encoding="utf-8"))
            parts = []
            if state_data.get("genre"):
                parts.append(f"**题材类型:** {state_data['genre']}")
            if state_data.get("era"):
                parts.append(f"**时代背景:** {state_data['era']}")
            if state_data.get("characters"):
                chars = state_data["characters"]
                if isinstance(chars, list):
                    chars_str = "、".join(str(c) for c in chars)
                elif isinstance(chars, str):
                    chars_str = chars
                else:
                    chars_str = str(chars)
                parts.append(f"**主要角色:** {chars_str}")
            if state_data.get("suggested_style"):
                parts.append(f"**推荐画风:** {state_data['suggested_style']}")
            if state_data.get("segments"):
                parts.append(f"**分段数量:** {len(state_data['segments'])} 段")
            if state_data.get("prompts"):
                parts.append(f"**图片提示词:** {len(state_data['prompts'])} 条")
            analysis_md = "\n\n".join(parts) if parts else "暂无分析数据"
        except (json.JSONDecodeError, OSError):
            analysis_md = "分析数据加载失败"

    # --- 生成的图片 ---
    image_paths = []
    images_dir = workspace / "images"
    if images_dir.exists():
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
            image_paths.extend(sorted(images_dir.glob(ext)))
    # 转为字符串路径列表
    image_paths = [str(p) for p in sorted(image_paths)]

    # --- 决策日志 (从 agent_decisions.json) ---
    decisions_json = []
    decisions_file = workspace / "agent_decisions.json"
    if decisions_file.exists():
        from src.agents.utils import load_decisions_from_file
        decisions_json = load_decisions_from_file(decisions_file)

    # --- 质量报告 ---
    quality_md = ""
    if state_file.exists():
        try:
            state_data = json.loads(state_file.read_text(encoding="utf-8"))
            scores = state_data.get("quality_scores", [])
            retry_counts = state_data.get("retry_counts", {})

            parts = []
            if scores:
                valid_scores = [s for s in scores if isinstance(s, (int, float)) and s >= 0]
                if valid_scores:
                    avg_score = sum(valid_scores) / len(valid_scores)
                    min_score = min(valid_scores)
                    max_score = max(valid_scores)
                    parts.append("### 图片质量评分")
                    parts.append(f"- **平均分:** {avg_score:.1f}")
                    parts.append(f"- **最低分:** {min_score:.1f}")
                    parts.append(f"- **最高分:** {max_score:.1f}")
                    parts.append(f"- **评分数量:** {len(valid_scores)}")
                else:
                    parts.append("### 图片质量评分")
                    parts.append("- 质量检查未启用（可在高级选项中开启 Agent 模式）")

            if retry_counts:
                total_retries = sum(retry_counts.values())
                parts.append("\n### 重试统计")
                parts.append(f"- **总重试次数:** {total_retries}")
                for k, v in retry_counts.items():
                    if v > 0:
                        parts.append(f"- {k}: {v} 次重试")

            # 决策统计（按 Agent 分类）
            if decisions_json:
                agent_counts: dict[str, int] = {}
                for d in decisions_json:
                    agent_name = d.get("agent", "unknown")
                    agent_counts[agent_name] = agent_counts.get(agent_name, 0) + 1
                parts.append("\n### Agent 决策统计")
                for agent_name, count in sorted(agent_counts.items()):
                    parts.append(f"- **{agent_name}:** {count} 条决策")

            quality_md = "\n".join(parts) if parts else "暂无质量数据"
        except (json.JSONDecodeError, OSError):
            quality_md = "质量数据加载失败"

    return analysis_md, image_paths, decisions_json, quality_md


# ---------------------------------------------------------------------------
# Novel writing backend functions
# ---------------------------------------------------------------------------


def _novel_set_env_keys(
    llm_backend: str, key_gemini: str, key_deepseek: str, key_openai: str,
) -> None:
    """Set LLM env vars for the novel pipeline."""
    env_map = {
        "GEMINI_API_KEY": key_gemini,
        "DEEPSEEK_API_KEY": key_deepseek,
        "OPENAI_API_KEY": key_openai,
    }
    for k, v in env_map.items():
        if v and v.strip():
            os.environ[k] = v.strip()


def _novel_create_pipeline(llm_backend: str) -> "NovelPipeline":  # noqa: F821
    """Create a NovelPipeline with the appropriate LLM config."""
    from src.novel.config import NovelConfig, load_novel_config
    from src.novel.pipeline import NovelPipeline

    config = load_novel_config()
    # Override LLM provider if specified
    llm_provider = LLM_MAP.get(llm_backend, "auto")
    if llm_provider != "auto":
        config.llm.outline_generation = llm_provider
        config.llm.character_design = llm_provider
        config.llm.scene_writing = llm_provider
        config.llm.quality_review = llm_provider
    return NovelPipeline(config=config)


def _novel_list_projects() -> list[str]:
    """Scan workspace/novels/ for existing projects, return choices list."""
    novels_dir = Path("workspace/novels")
    if not novels_dir.exists():
        return []
    projects = []
    for d in sorted(novels_dir.iterdir()):
        if d.is_dir() and (d / "novel.json").exists():
            try:
                data = json.loads((d / "novel.json").read_text(encoding="utf-8"))
                title = data.get("title", d.name)
                status = data.get("status", "unknown")
                projects.append(f"{d.name} | {title} [{status}]")
            except Exception:
                projects.append(d.name)
    return projects


def _novel_extract_project_path(project_label: str) -> str:
    """Extract project path from dropdown label like 'novel_xxx | Title [status]'."""
    if not project_label:
        raise gr.Error("请先选择一个项目")
    novel_id = project_label.split("|")[0].strip()
    return str(Path("workspace/novels") / novel_id)


def _novel_create(
    theme: str,
    author_name: str,
    target_audience: str,
    genre: str,
    target_words: str,
    style: str,
    template: str,
    custom_ideas: str,
    llm_backend: str,
    key_gemini: str,
    key_deepseek: str,
    key_openai: str,
    progress=gr.Progress(),
):
    """Create a new novel project. Returns (status, outline_md, chars_md, world_md, project_json, projects_list)."""
    if not theme or not theme.strip():
        gr.Warning("请输入主题/灵感")
        return ("请输入主题/灵感", "", "", "", None, gr.update())

    progress(0, desc="正在准备...")
    _novel_set_env_keys(llm_backend, key_gemini, key_deepseek, key_openai)
    pipe = _novel_create_pipeline(llm_backend)

    genre_val = NOVEL_GENRE_MAP.get(genre, "玄幻")
    # target_words is now a slider value in 万字
    words_val = int(target_words * 10000) if target_words else 100000
    style_val = NOVEL_STYLE_MAP.get(style, "webnovel.shuangwen")
    template_val = NOVEL_TEMPLATE_MAP.get(template, "cyclic_upgrade")

    def _progress_cb(pct, msg):
        progress(pct, desc=msg)

    try:
        result = pipe.create_novel(
            genre=genre_val,
            theme=theme.strip(),
            target_words=words_val,
            style=style_val,
            template=template_val,
            custom_ideas=custom_ideas.strip() if custom_ideas else "",
            author_name=author_name.strip() if author_name else "",
            target_audience=target_audience or "通用",
            progress_callback=_progress_cb,
        )
    except Exception as e:
        gr.Warning(f"创建项目失败: {e}")
        return (f"创建项目失败: {e}", "", "", "", None, gr.update())

    progress(0.85, desc="正在格式化结果...")

    # Format outline as markdown
    outline = result.get("outline") or {}
    outline_md = _novel_format_outline(outline)

    # Format characters as markdown
    characters = result.get("characters", [])
    chars_md = _novel_format_characters(characters)

    # Format world setting
    world = result.get("world_setting") or {}
    world_md = _novel_format_world(world)

    # Status
    total_ch = result.get("total_chapters", 0)
    errors = result.get("errors", [])
    protagonist_names = result.get("protagonist_names", [])
    synopsis = result.get("synopsis", "")
    tags = result.get("tags", [])

    status_text = (
        f"项目创建成功!\n"
        f"小说ID: {result.get('novel_id')}\n"
        f"总章数: {total_ch}\n"
        f"主角: {', '.join(protagonist_names) if protagonist_names else '待定'}\n"
        f"标签: {', '.join(tags) if tags else '无'}\n"
    )
    if synopsis:
        status_text += f"简介: {synopsis[:100]}..."
    if errors:
        status_text += f"\n警告: {len(errors)} 个错误"

    # Refresh project list and select the newly created project
    novel_id = result.get("novel_id", "")
    projects = _novel_list_projects()
    selected = None
    for p in projects:
        if p.startswith(novel_id):
            selected = p
            break
    if not selected and projects:
        selected = projects[-1]

    # Project info JSON
    project_info = {
        "novel_id": novel_id,
        "workspace": result.get("workspace"),
        "total_chapters": total_ch,
        "genre": genre_val,
        "target_words": words_val,
    }

    gr.Info("项目创建成功!")
    return (
        status_text,
        outline_md,
        chars_md,
        world_md,
        project_info,
        gr.update(choices=projects, value=selected),
    )


def _novel_format_outline(outline: dict) -> str:
    """Format outline dict as Markdown with rich chapter details."""
    if not outline:
        return "暂无大纲数据"
    parts = []
    if outline.get("title"):
        parts.append(f"# {outline['title']}\n")
    if outline.get("synopsis"):
        parts.append(f"**简介:** {outline['synopsis']}\n")
    chapters = outline.get("chapters", [])
    if chapters:
        parts.append(f"## 章节大纲（共 {len(chapters)} 章）\n")
        for ch in chapters:
            ch_num = ch.get("chapter_number", "?")
            ch_title = ch.get("title", "")
            mood = ch.get("mood", "")
            goal = ch.get("goal", ch.get("summary", ""))
            key_events = ch.get("key_events", [])
            characters = ch.get("involved_characters", [])

            # Chapter header with mood tag
            header = f"**第{ch_num}章 {ch_title}**"
            if mood:
                header += f"  `{mood}`"
            parts.append(header)

            # Goal
            if goal:
                parts.append(f"> {goal}")

            # Key events as bullet list
            if key_events:
                for evt in key_events:
                    parts.append(f"- {evt}")

            # Characters involved
            if characters:
                parts.append(f"👤 {', '.join(characters)}")

            parts.append("")  # blank line between chapters
    return "\n".join(parts) if parts else "暂无大纲数据"


def _novel_format_characters(characters: list) -> str:
    """Format character list as Markdown cards."""
    if not characters:
        return "暂无角色数据"
    parts = []
    for i, ch in enumerate(characters):
        if isinstance(ch, dict):
            name = ch.get("name", f"角色{i + 1}")
            role = ch.get("role", "")
            desc = ch.get("description", ch.get("personality", ""))
            parts.append(f"### {name}")
            if role:
                parts.append(f"**身份:** {role}")
            if desc:
                parts.append(f"{desc}")
            # Show other notable fields
            if ch.get("appearance"):
                parts.append(f"**外貌:** {ch['appearance']}")
            if ch.get("abilities"):
                abilities = ch["abilities"]
                if isinstance(abilities, list):
                    abilities = "、".join(str(a) for a in abilities)
                parts.append(f"**能力:** {abilities}")
            parts.append("")
        else:
            parts.append(f"- {ch}")
    return "\n".join(parts)


def _novel_format_world(world: dict) -> str:
    """Format world setting dict as Markdown."""
    if not world:
        return "暂无世界观数据"
    parts = []
    if world.get("era"):
        parts.append(f"**时代:** {world['era']}")
    if world.get("location"):
        parts.append(f"**地点:** {world['location']}")
    if world.get("description"):
        parts.append(f"\n{world['description']}")
    if world.get("power_system"):
        power = world["power_system"]
        if isinstance(power, dict):
            parts.append("\n### 力量体系")
            for k, v in power.items():
                parts.append(f"- **{k}:** {v}")
        else:
            parts.append(f"\n### 力量体系\n{power}")
    if world.get("factions"):
        parts.append("\n### 势力")
        factions = world["factions"]
        if isinstance(factions, list):
            for f in factions:
                if isinstance(f, dict):
                    parts.append(f"- **{f.get('name', '?')}**: {f.get('description', '')}")
                else:
                    parts.append(f"- {f}")
        elif isinstance(factions, dict):
            for k, v in factions.items():
                parts.append(f"- **{k}**: {v}")
    if world.get("rules"):
        parts.append(f"\n### 世界规则\n{world['rules']}")
    return "\n".join(parts) if parts else "暂无世界观数据"


def _novel_get_progress(project: str) -> str:
    """Get project progress as a short description string."""
    if not project:
        return ""
    project_path = _novel_extract_project_path(project)
    novel_id = Path(project_path).name
    from src.novel.pipeline import NovelPipeline
    pipe = NovelPipeline()
    try:
        status = pipe.get_status(project_path)
    except Exception:
        return ""
    current = status.get("current_chapter", 0)
    total = status.get("total_chapters", 0)
    title = status.get("title", "")
    words = status.get("total_words", 0)
    if total == 0:
        return "项目尚未初始化大纲"
    if current >= total:
        return f"已全部完成 {total}/{total} 章 ({words} 字)"
    return f"已完成 {current}/{total} 章 ({words} 字)，下一章: 第{current + 1}章"


def _novel_generate(
    project: str,
    batch_size: int,
    silent: bool,
    llm_backend: str,
    key_gemini: str,
    key_deepseek: str,
    key_openai: str,
    progress=gr.Progress(),
):
    """Generate next batch of chapters for an existing project."""
    if not project:
        gr.Warning("请先选择一个项目")
        return ("请先选择一个项目", gr.update())

    project_path = _novel_extract_project_path(project)
    novel_id = Path(project_path).name
    _novel_set_env_keys(llm_backend, key_gemini, key_deepseek, key_openai)
    pipe = _novel_create_pipeline(llm_backend)

    # Auto-detect where to continue from
    from src.novel.storage.file_manager import FileManager
    fm = FileManager(pipe.workspace)
    completed = fm.list_chapters(novel_id)
    start_ch = (max(completed) + 1) if completed else 1

    # Determine end chapter
    ckpt = pipe._load_checkpoint(novel_id)
    if ckpt is None:
        gr.Warning("项目检查点不存在，请先创建项目")
        return ("项目检查点不存在，请先创建项目", gr.update())
    outline = ckpt.get("outline", {})
    total_chapters = len(outline.get("chapters", []))

    if start_ch > total_chapters:
        gr.Info("所有章节已生成完成!")
        return f"所有章节已生成完成 ({total_chapters}/{total_chapters} 章)", ""

    batch = int(batch_size) if batch_size else 20
    end_ch = min(start_ch + batch - 1, total_chapters)

    progress(0, desc=f"正在生成第 {start_ch}-{end_ch} 章 (共 {total_chapters} 章)...")

    def _progress_cb(pct, msg):
        progress(pct, desc=msg)

    try:
        result = pipe.generate_chapters(
            project_path=project_path,
            start_chapter=start_ch,
            end_chapter=end_ch,
            silent=silent,
            progress_callback=_progress_cb,
        )
    except Exception as e:
        gr.Warning(f"章节生成失败: {e}")
        return (f"章节生成失败: {e}", gr.update())

    generated = result.get("chapters_generated", [])
    errors = result.get("errors", [])

    # Calculate new progress
    new_completed = (max(completed) if completed else 0) + len(generated)
    status = (
        f"本批完成! 生成了第 {start_ch}-{start_ch + len(generated) - 1} 章\n"
        f"当前进度: {new_completed}/{total_chapters} 章"
    )
    if new_completed < total_chapters:
        status += f"\n剩余: {total_chapters - new_completed} 章待生成"
    else:
        status += "\n全部章节已生成完成!"
    if errors:
        status += f"\n错误: {len(errors)} 个"

    # Load the latest chapter text for preview
    chapter_text = ""
    if generated:
        last_ch = max(generated)
        chapter_text = _novel_load_chapter_text(project_path, last_ch)

    gr.Info(f"完成! 生成了 {len(generated)} 章 (第{start_ch}-{end_ch})")
    return status, chapter_text


def _novel_load_chapter_text(project_path: str, chapter_num: int) -> str:
    """Load a specific chapter's text from files (with title header)."""
    ch_json = Path(project_path) / "chapters" / f"chapter_{chapter_num:03d}.json"
    if ch_json.exists():
        data = json.loads(ch_json.read_text(encoding="utf-8"))
        title = data.get("title", "")
        text = data.get("full_text", "")
        header = f"第{chapter_num}章 {title}" if title else f"第{chapter_num}章"
        word_count = data.get("word_count", len(text))
        return f"{'='*40}\n{header}（{word_count}字）\n{'='*40}\n\n{text}"
    # Fallback: try plain text
    ch_file = Path(project_path) / "chapters" / f"chapter_{chapter_num:03d}.txt"
    if ch_file.exists():
        return ch_file.read_text(encoding="utf-8")
    return ""


def _novel_list_chapter_titles(project_path: str) -> str:
    """List all chapter titles as markdown."""
    chapters_dir = Path(project_path) / "chapters"
    if not chapters_dir.exists():
        return "*暂无章节*"
    lines = []
    for f in sorted(chapters_dir.glob("chapter_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        num = data.get("chapter_number", 0)
        title = data.get("title", "无标题")
        wc = data.get("word_count", 0)
        lines.append(f"**第{num}章** {title}　({wc}字)")
    if not lines:
        return "*暂无章节*"
    return "\n\n".join(lines)


def _novel_load_chapter(project: str, chapter_num: int) -> str:
    """Load a specific chapter for display. Returns chapter text."""
    if not project:
        gr.Warning("请先选择项目")
        return "请先选择项目"
    if not chapter_num or chapter_num < 1:
        gr.Warning("请输入有效章节号")
        return "请输入有效章节号"
    project_path = _novel_extract_project_path(project)
    text = _novel_load_chapter_text(project_path, int(chapter_num))
    if not text:
        return f"第{int(chapter_num)}章尚未生成"
    return text


def _novel_refresh_status(project: str):
    """Refresh project status. Returns (status_text, chapter_text, chapter_list_md, outline_md, chars_md, world_md, project_json)."""
    if not project:
        gr.Warning("请先选择项目")
        return ("请先选择项目", gr.update(), gr.update(), "", "", "", None)

    project_path = _novel_extract_project_path(project)
    novel_id = Path(project_path).name

    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline()
    try:
        status = pipe.get_status(project_path)
    except Exception as e:
        gr.Warning(f"获取状态失败: {e}")
        return (f"获取状态失败: {e}", gr.update(), gr.update(), "", "", "", None)

    if not status:
        return ("项目数据为空", gr.update(), gr.update(), "", "", "", None)

    # Load checkpoint for outline/characters/world
    ckpt = pipe._load_checkpoint(novel_id)

    outline_md = ""
    chars_md = ""
    world_md = ""
    if ckpt:
        outline_md = _novel_format_outline(ckpt.get("outline", {}))
        chars_md = _novel_format_characters(ckpt.get("characters", []))
        world_md = _novel_format_world(ckpt.get("world_setting", {}))

    # Status text
    author = status.get("author_name", "")
    audience = status.get("target_audience", "")
    protags = status.get("protagonist_names", [])
    synopsis = status.get("synopsis", "")
    tags = status.get("tags", [])

    status_text = (
        f"标题: {status.get('title', '?')}\n"
        f"状态: {status.get('status', '?')}\n"
        f"进度: 第{status.get('current_chapter', 0)}/{status.get('total_chapters', 0)}章\n"
        f"已写字数: {status.get('total_words', 0)} / 目标 {status.get('target_words', 0)}"
    )
    if author:
        status_text += f"\n笔名: {author}"
    if audience:
        status_text += f"\n读者: {audience}"
    if protags:
        status_text += f"\n主角: {', '.join(protags)}"
    if tags:
        status_text += f"\n标签: {', '.join(tags)}"
    if synopsis:
        status_text += f"\n简介: {synopsis[:80]}..."

    # Load chapter list and latest chapter text
    chapter_list_md = _novel_list_chapter_titles(project_path)
    chapter_text = ""
    current_ch = status.get("current_chapter", 0)
    if current_ch > 0:
        chapter_text = _novel_load_chapter_text(project_path, current_ch)

    return status_text, chapter_text, chapter_list_md, outline_md, chars_md, world_md, status


def _novel_delete_project(project: str):
    """Delete a novel project. Returns (status_text, project_list_update)."""
    if not project:
        gr.Warning("请先选择项目")
        return "请先选择项目", gr.update()

    import shutil
    project_path = _novel_extract_project_path(project)
    novel_id = Path(project_path).name

    if not Path(project_path).exists():
        gr.Warning("项目不存在")
        return "项目不存在", gr.update(choices=_novel_list_projects(), value=None)

    try:
        shutil.rmtree(project_path)
        gr.Info(f"项目 {novel_id} 已删除")
        projects = _novel_list_projects()
        return f"项目 {novel_id} 已删除", gr.update(choices=projects, value=projects[0] if projects else None)
    except Exception as e:
        gr.Warning(f"删除失败: {e}")
        return f"删除失败: {e}", gr.update()


def _novel_export(project: str):
    """Export novel as TXT. Returns (status_text, file_path)."""
    if not project:
        gr.Warning("请先选择项目")
        return ("请先选择项目", None)
    project_path = _novel_extract_project_path(project)

    from src.novel.pipeline import NovelPipeline

    pipe = NovelPipeline()
    try:
        output_path = pipe.export_novel(project_path)
    except Exception as e:
        gr.Warning(f"导出失败: {e}")
        return (f"导出失败: {e}", None)

    gr.Info(f"导出成功: {output_path}")
    return f"导出成功!\n文件: {output_path}", output_path


def _novel_apply_feedback(
    project: str,
    feedback: str,
    chapter_num: int,
    dry_run: bool,
    llm_backend: str,
    key_gemini: str,
    key_deepseek: str,
    key_openai: str,
    progress=gr.Progress(),
):
    """Apply feedback to a novel project."""
    if not project:
        gr.Warning("请先选择项目")
        return "请先选择项目"
    if not feedback or not feedback.strip():
        gr.Warning("请输入反馈内容")
        return "请输入反馈内容"

    progress(0, desc="正在准备反馈处理...")
    project_path = _novel_extract_project_path(project)
    _novel_set_env_keys(llm_backend, key_gemini, key_deepseek, key_openai)
    pipe = _novel_create_pipeline(llm_backend)

    ch_num = int(chapter_num) if chapter_num and chapter_num > 0 else None

    def _progress_cb(pct, msg):
        progress(pct, desc=msg)

    try:
        result = pipe.apply_feedback(
            project_path=project_path,
            feedback_text=feedback.strip(),
            chapter_number=ch_num,
            dry_run=dry_run,
            progress_callback=_progress_cb,
        )
    except Exception as e:
        gr.Warning(f"反馈处理失败: {e}")
        return f"反馈处理失败: {e}"

    analysis = result.get("analysis", {})
    rewritten = result.get("rewritten_chapters", [])

    parts = []
    parts.append(f"反馈类型: {analysis.get('feedback_type', '?')}")
    parts.append(f"严重程度: {analysis.get('severity', '?')}")
    parts.append(f"目标章节: {analysis.get('target_chapters', [])}")
    parts.append(f"传播章节: {analysis.get('propagation_chapters', [])}")

    if dry_run:
        parts.append("\n[仅分析模式 - 未实际修改]")
    else:
        parts.append(f"\n已重写 {len(rewritten)} 章:")
        for rw in rewritten:
            ch = rw.get("chapter_number", "?")
            orig = rw.get("original_chars", 0)
            new = rw.get("new_chars", 0)
            prop = " (传播)" if rw.get("is_propagation") else ""
            parts.append(f"  第{ch}章: {orig} → {new} 字{prop}")

    status = "\n".join(parts)
    mode = "分析完成" if dry_run else "重写完成"
    gr.Info(f"反馈{mode}!")
    return status


def _novel_polish(
    project, start_ch, end_ch,
    llm_backend_val, key_gemini, key_deepseek, key_openai,
):
    """AI 精修"""
    if not project:
        return "请先选择项目"

    project_path = _novel_extract_project_path(project)
    _novel_set_env_keys(llm_backend_val, key_gemini, key_deepseek, key_openai)

    try:
        pipeline = _novel_create_pipeline(llm_backend_val)

        start = int(start_ch) if start_ch and int(start_ch) > 0 else 1
        end = int(end_ch) if end_ch and int(end_ch) > 0 else None

        result = pipeline.polish_chapters(
            project_path=project_path,
            start_chapter=start,
            end_chapter=end,
        )

        polished = result.get("polished_chapters", [])
        skipped = result.get("skipped_chapters", [])
        errors = result.get("errors", [])

        status_parts = [f"精修完成: {len(polished)}章已修改, {len(skipped)}章跳过"]
        if errors:
            status_parts.append(f", {len(errors)}章出错")
        for p in polished[:5]:
            status_parts.append(
                f"  第{p['chapter_number']}章: {p['original_chars']}->{p['polished_chars']}字"
            )

        return "\n".join(status_parts)

    except Exception as exc:
        return f"精修失败: {exc}"


def _format_polish_report(result: dict) -> str:
    """Format polish result as a rich Markdown report with before/after metrics."""
    if not result:
        return ""

    polished = result.get("polished_chapters", [])
    skipped = result.get("skipped_chapters", [])
    errors = result.get("errors", [])

    lines = ["## 📋 精修报告\n"]

    # Summary
    total = len(polished) + len(skipped) + len(errors)
    lines.append(f"**总计**: {total} 章 | "
                 f"**已修改**: {len(polished)} | "
                 f"**跳过**: {len(skipped)} | "
                 f"**出错**: {len(errors)}\n")

    if not polished:
        lines.append("*所有章节审稿通过，无需修改。*")
        return "\n".join(lines)

    # Aggregate issue stats
    all_issues: dict[str, int] = {}
    for p in polished:
        for issue in p.get("issues", []):
            t = issue.get("type", "其他")
            all_issues[t] = all_issues.get(t, 0) + 1

    if all_issues:
        issue_icons = {
            "重复": "🔁", "对话": "💬", "逻辑": "🧩", "节奏": "⏱️",
            "细节": "🔍", "AI味": "🤖", "转折": "↪️", "角色": "👤",
            "风格": "🎨", "其他": "📝",
        }
        lines.append("### 问题分布\n")
        for t, cnt in sorted(all_issues.items(), key=lambda x: -x[1]):
            icon = issue_icons.get(t, "📝")
            lines.append(f"- {icon} **{t}**: {cnt} 处")
        lines.append("")

    # For old-format results, try to compute metrics from saved revisions
    novel_id = result.get("novel_id", "")
    _fm = None
    _style_tool = None
    _quality_tool = None
    if novel_id:
        try:
            from src.novel.storage.file_manager import FileManager
            _fm = FileManager("workspace")
        except Exception:
            pass

    def _ensure_metrics(p: dict) -> None:
        """Backfill before_style/after_style/before_rules/after_rules from files if missing."""
        if p.get("before_style") and p.get("after_style"):
            return  # already has new-format data
        if not _fm or not novel_id:
            return
        nonlocal _style_tool, _quality_tool
        try:
            ch_num = p["chapter_number"]
            revisions = _fm.list_chapter_revisions(novel_id, ch_num)
            if not revisions:
                return
            original = _fm.load_chapter_revision(novel_id, ch_num, max(revisions)) or ""
            polished_text = _fm.load_chapter_text(novel_id, ch_num) or ""
            if not original or not polished_text:
                return
            if _style_tool is None:
                from src.novel.tools.style_analysis_tool import StyleAnalysisTool
                from src.novel.tools.quality_check_tool import QualityCheckTool
                _style_tool = StyleAnalysisTool()
                _quality_tool = QualityCheckTool()
            p["before_style"] = _style_tool.analyze(original).model_dump()
            p["after_style"] = _style_tool.analyze(polished_text).model_dump()
            p["before_rules"] = _quality_tool.rule_check(original).model_dump()
            p["after_rules"] = _quality_tool.rule_check(polished_text).model_dump()
        except Exception:
            pass

    # Per-chapter details
    lines.append("---\n")

    for p in polished:
        _ensure_metrics(p)

        ch_num = p["chapter_number"]
        orig_chars = p["original_chars"]
        new_chars = p["polished_chars"]
        delta = new_chars - orig_chars
        delta_str = f"+{delta}" if delta >= 0 else str(delta)
        pct = (delta / orig_chars * 100) if orig_chars else 0

        lines.append(f"### 第{ch_num}章  `{orig_chars}` → `{new_chars}` 字 ({delta_str}, {pct:+.0f}%)\n")

        # Issue tags
        issues = p.get("issues", [])
        if issues:
            tags = "  ".join(
                f"`{issue_icons.get(i.get('type', '其他'), '📝')} {i.get('type', '其他')}`"
                for i in issues
            )
            lines.append(f"**发现问题**: {tags}\n")

        # Critique summary (for old format without full critique)
        critique_summary = p.get("critique_summary", "")
        if critique_summary and not p.get("critique_full"):
            lines.append(f"**审稿意见**: {critique_summary}\n")

        # Style metrics comparison table
        before_style = p.get("before_style")
        after_style = p.get("after_style")
        if before_style and after_style:
            lines.append("<details><summary>风格指标对比</summary>\n")
            lines.append("| 指标 | 修改前 | 修改后 | 变化 |")
            lines.append("|------|--------|--------|------|")

            style_labels = {
                "avg_sentence_length": "平均句长",
                "dialogue_ratio": "对话占比",
                "exclamation_ratio": "感叹号占比",
                "avg_paragraph_length": "平均段落长",
                "classical_word_ratio": "古典词汇占比",
                "description_ratio": "描写占比",
                "first_person_ratio": "第一人称占比",
            }
            for key, label in style_labels.items():
                bv = before_style.get(key, 0)
                av = after_style.get(key, 0)
                if bv is None:
                    bv = 0
                if av is None:
                    av = 0
                # Format as percentage for ratios, integer for lengths
                if "ratio" in key:
                    b_str = f"{bv:.1%}"
                    a_str = f"{av:.1%}"
                    d = av - bv
                    d_str = f"{d:+.1%}" if d != 0 else "—"
                else:
                    b_str = f"{bv:.1f}"
                    a_str = f"{av:.1f}"
                    d = av - bv
                    d_str = f"{d:+.1f}" if abs(d) > 0.05 else "—"
                lines.append(f"| {label} | {b_str} | {a_str} | {d_str} |")
            lines.append("\n</details>\n")

        # Rule check comparison
        before_rules = p.get("before_rules")
        after_rules = p.get("after_rules")
        if before_rules and after_rules:
            rule_labels = {
                "repetition_issues": "重复问题",
                "ai_flavor_issues": "AI味",
                "paragraph_length_issues": "段落过长",
                "dialogue_distinction_issues": "对话区分度",
            }
            improvements = []
            for key, label in rule_labels.items():
                b_cnt = len(before_rules.get(key, []))
                a_cnt = len(after_rules.get(key, []))
                if b_cnt > 0 or a_cnt > 0:
                    if a_cnt < b_cnt:
                        improvements.append(f"✅ {label}: {b_cnt} → {a_cnt}")
                    elif a_cnt > b_cnt:
                        improvements.append(f"⚠️ {label}: {b_cnt} → {a_cnt}")
                    else:
                        improvements.append(f"— {label}: {b_cnt} (未变)")
            if improvements:
                lines.append("<details><summary>质量检查变化</summary>\n")
                for imp in improvements:
                    lines.append(f"- {imp}")
                lines.append("\n</details>\n")

        # Critique details (collapsible)
        critique_full = p.get("critique_full", "")
        if critique_full:
            lines.append("<details><summary>完整审稿意见</summary>\n")
            lines.append(critique_full)
            lines.append("\n</details>\n")

        lines.append("")

    if skipped:
        lines.append(f"\n**跳过章节**: {', '.join(f'第{s}章' for s in skipped)}")

    if errors:
        lines.append("\n**出错章节**:")
        for e in errors:
            lines.append(f"- 第{e['chapter']}章: {e['error']}")

    return "\n".join(lines)


def _novel_load_polish_diff(project: str, chapter_num: int) -> str:
    """Load before/after text for a specific polished chapter."""
    if not project:
        return "请先选择项目"
    try:
        project_path = _novel_extract_project_path(project)
        novel_id = Path(project_path).name

        from src.novel.storage.file_manager import FileManager
        fm = FileManager("workspace")

        ch_num = int(chapter_num)
        revisions = fm.list_chapter_revisions(novel_id, ch_num)
        if not revisions:
            return f"第{ch_num}章没有修订历史（未被精修过）"

        latest_rev = max(revisions)
        original = fm.load_chapter_revision(novel_id, ch_num, latest_rev) or ""
        polished = fm.load_chapter_text(novel_id, ch_num) or ""

        if not original and not polished:
            return f"第{ch_num}章文本为空"

        lines = [f"## 第{ch_num}章 精修对比\n"]
        lines.append(f"**版本**: rev{latest_rev} → 当前 | "
                     f"**字数**: {len(original)} → {len(polished)}\n")
        lines.append("---\n")
        lines.append(f"### 修改前 ({len(original)}字)\n")
        lines.append(original[:2000] + ("\n\n*...（截断显示前2000字）*" if len(original) > 2000 else ""))
        lines.append(f"\n\n---\n### 修改后 ({len(polished)}字)\n")
        lines.append(polished[:2000] + ("\n\n*...（截断显示前2000字）*" if len(polished) > 2000 else ""))

        return "\n".join(lines)

    except Exception as e:
        return f"加载对比失败: {e}"


def _extract_novel_polish_result(task: dict) -> str:
    """Extract polish result from completed task and format report."""
    if not task or task.get("status") != "completed":
        return ""
    result_str = task.get("result", "")
    if not result_str:
        return ""
    try:
        result = json.loads(result_str) if isinstance(result_str, str) else result_str
    except (json.JSONDecodeError, TypeError):
        return ""
    return _format_polish_report(result)


# ---------------------------------------------------------------------------
# AI 短视频导演 -- 后端函数
# ---------------------------------------------------------------------------

_DIRECTOR_BUDGET_MAP = {
    "免费(纯图片)": "free",
    "低(少量动态)": "low",
    "中(部分视频)": "medium",
    "高(全视频)": "high",
}


def _director_generate(
    inspiration, duration, budget_label,
    llm_service, img_service,
    key_gemini, key_deepseek, key_openai,
    key_siliconflow, key_dashscope,
    key_kling, key_jimeng, key_minimax,
    llm_backend_setting, img_backend_setting,
):
    """AI导演模式: 灵感 -> 视频"""
    if not inspiration or not inspiration.strip():
        return (
            "请输入灵感/创意",
            None, None, None, None, "请先输入灵感",
        )

    # 设置环境变量 (复用 generate() 中的逻辑)
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

    budget = _DIRECTOR_BUDGET_MAP.get(budget_label, "low")

    try:
        from src.director_pipeline import DirectorPipeline

        # 构建 config
        llm_provider = LLM_MAP.get(llm_backend_setting, "auto")
        img_backend = BACKEND_MAP.get(img_backend_setting, "siliconflow")
        config = {
            "llm": {"provider": llm_provider},
            "imagegen": {"backend": img_backend},
            "video": {
                "codec": "libx265",
                "crf": 18,
                "resolution": [1080, 1920],
            },
        }

        pipeline = DirectorPipeline(config=config, workspace="workspace/videos")

        status_updates = []

        def on_progress(pct, desc):
            status_updates.append(f"[{int(pct * 100)}%] {desc}")

        result = pipeline.run(
            inspiration=inspiration.strip(),
            target_duration=int(duration),
            budget=budget,
            progress_callback=on_progress,
        )

        # 格式化分段详情
        segments_md = _format_director_segments(result.get("segments", []))

        video_path = result.get("video_path", "")
        if video_path:
            video_path = str(Path(video_path).resolve())
        status_text = "\n".join(status_updates[-5:]) if status_updates else "完成"

        return (
            status_text,
            video_path if video_path and Path(video_path).exists() else None,
            video_path if video_path and Path(video_path).exists() else None,
            result.get("script"),
            result.get("idea"),
            segments_md,
        )

    except Exception as exc:
        import traceback
        return (
            f"生成失败: {exc}\n\n{traceback.format_exc()}",
            None, None, None, None,
            f"错误: {exc}",
        )


def _format_director_segments(segments: list) -> str:
    """格式化分段详情为 Markdown"""
    if not segments:
        return "无分段数据"

    lines = []
    for seg in segments:
        purpose = seg.get("purpose", "?")
        voiceover = seg.get("voiceover", "")
        visual = seg.get("visual", "")
        duration = seg.get("duration_sec", 0)
        asset_type = seg.get("asset_type", "image")
        motion = seg.get("motion", "static")

        lines.append(
            f"### 段{seg.get('id', '?')} [{purpose}] {duration:.1f}s\n"
            f"**旁白:** {voiceover}\n\n"
            f"**画面:** {visual}\n\n"
            f"素材: `{asset_type}` | 镜头: `{motion}`\n\n---\n"
        )
    return "\n".join(lines)


def _director_list_projects() -> list[str]:
    """Scan workspace/videos/ for existing runs, return choices list."""
    videos_dir = Path("workspace/videos")
    if not videos_dir.exists():
        return []
    projects = []
    for d in sorted(videos_dir.iterdir(), reverse=True):
        if not d.is_dir() or not d.name.startswith("run_"):
            continue
        script_file = d / "script.json"
        mp4_files = list(d.glob("*.mp4"))
        if not script_file.exists():
            continue
        try:
            data = json.loads(script_file.read_text(encoding="utf-8"))
            title = data.get("title", d.name)
            duration = data.get("total_duration", 0)
            seg_count = len(data.get("segments", []))
            has_video = "✓" if mp4_files else "✗"
            projects.append(
                f"{d.name} | {title} [{seg_count}段 {duration:.0f}s] {has_video}"
            )
        except Exception:
            projects.append(d.name)
    return projects


def _load_director_run_dir(run_dir: Path):
    """Load director results from a run directory.

    Returns (status, video, file, script_json, idea_json, segments_md).
    """
    if not run_dir.exists():
        return (f"项目目录不存在: {run_dir}", None, None, None, None, "")

    script_file = run_dir / "script.json"
    if not script_file.exists():
        return ("脚本文件不存在", None, None, None, None, "")

    try:
        data = json.loads(script_file.read_text(encoding="utf-8"))
    except Exception as e:
        return (f"读取脚本失败: {e}", None, None, None, None, "")

    # Find video file — use absolute path for Gradio compatibility
    mp4_files = list(run_dir.glob("*.mp4"))
    video_path = str(mp4_files[0].resolve()) if mp4_files else None

    # Format segments
    segments_md = _format_director_segments(data.get("segments", []))

    # Extract idea
    idea = data.get("idea")

    title = data.get("title", "未知")
    duration = data.get("total_duration", 0)
    seg_count = len(data.get("segments", []))
    status = f"已加载: {title}\n时长: {duration:.0f}s | {seg_count}段"
    if video_path:
        status += f"\n视频: {Path(video_path).name}"

    return (
        status,
        video_path if video_path and Path(video_path).exists() else None,
        video_path if video_path and Path(video_path).exists() else None,
        data,
        idea,
        segments_md,
    )


def _director_load_project(project_label: str):
    """Load a previously generated director project.

    Returns (status, video, file, script_json, idea_json, segments_md).
    """
    if not project_label:
        return ("请选择一个项目", None, None, None, None, "")

    run_id = project_label.split("|")[0].strip()
    run_dir = Path("workspace/videos") / run_id
    return _load_director_run_dir(run_dir)


def _extract_director_result_from_task(task: dict):
    """Extract director results from a completed task queue response.

    Returns (video, file, script_json, idea_json, segments_md) or all None.
    """
    _none = (None, None, None, None, "")
    if not task or task.get("status") != "completed":
        return _none

    result_str = task.get("result", "")
    if not result_str:
        return _none

    try:
        result = json.loads(result_str) if isinstance(result_str, str) else result_str
    except (json.JSONDecodeError, TypeError):
        return _none

    # Try to load from run_dir (most reliable — reads script.json)
    run_dir = result.get("run_dir", "")
    if run_dir and Path(run_dir).exists():
        parts = _load_director_run_dir(Path(run_dir))
        # Skip status (index 0), return rest
        return parts[1:]

    # Fallback: extract from task result dict directly
    video_path = result.get("video_path", "")
    if video_path:
        video_path = str(Path(video_path).resolve())
    segments_md = _format_director_segments(result.get("segments", []))
    return (
        video_path if video_path and Path(video_path).exists() else None,
        video_path if video_path and Path(video_path).exists() else None,
        result.get("script"),
        result.get("idea"),
        segments_md,
    )


# ---------------------------------------------------------------------------
# Qimao Publishing Agent
# ---------------------------------------------------------------------------
_QIMAO_PROFILE_DIR = Path.home() / ".novel-video" / "chrome_profile"
_QIMAO_AUTH_FILE = Path.home() / ".novel-video" / "qimao_auth.json"


def _qimao_check_login() -> str:
    """检查七猫登录状态"""
    if _QIMAO_PROFILE_DIR.exists():
        return "✓ 已登录（session 已保存）"
    return "未登录 — 请先点击「登录七猫作家中心」"


def _qimao_login(progress=gr.Progress()):
    """打开 Chrome 让用户登录七猫"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        gr.Warning("需要安装 playwright: pip install playwright && playwright install chromium")
        return "需要安装 playwright: pip install playwright && playwright install chromium"

    _QIMAO_PROFILE_DIR.parent.mkdir(parents=True, exist_ok=True)

    progress(0.1, desc="启动 Chrome...")
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not Path(chrome).exists():
        chrome = None  # fallback

    with sync_playwright() as p:
        kwargs = {
            "user_data_dir": str(_QIMAO_PROFILE_DIR),
            "headless": False,
        }
        if chrome:
            kwargs["executable_path"] = chrome
            kwargs["args"] = ["--disable-blink-features=AutomationControlled"]
        else:
            kwargs["channel"] = "chrome"

        context = p.chromium.launch_persistent_context(**kwargs)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://zuozhe.qimao.com")

        progress(0.3, desc="等待登录... 请在弹出的 Chrome 中登录")
        try:
            page.wait_for_url("**/writer/**", timeout=300_000)
        except Exception:
            pass

        context.storage_state(path=str(_QIMAO_AUTH_FILE))
        context.close()

    return "✓ 已登录（session 已保存）"


def _qimao_publish(
    project: str,
    start: int,
    end: int,
    progress=gr.Progress(),
):
    """自动发布章节到七猫"""
    if not project:
        gr.Warning("请先选择项目")
        return "请先选择项目"
    if not _QIMAO_PROFILE_DIR.exists():
        gr.Warning("请先登录七猫作家中心")
        return "请先登录七猫作家中心"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        gr.Warning("需要安装 playwright")
        return "需要安装 playwright"

    import time as _time

    project_path = _novel_extract_project_path(project)
    chapters_dir = Path(project_path) / "chapters"
    if not chapters_dir.exists():
        gr.Warning("章节目录不存在")
        return "章节目录不存在"

    # 加载章节
    chapters = []
    for f in sorted(chapters_dir.glob("chapter_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        chapters.append(data)

    if not chapters:
        gr.Warning("没有找到章节")
        return "没有找到章节"

    start = int(start) if start and start > 0 else 1
    end_ch = int(end) if end and end > 0 else max(ch["chapter_number"] for ch in chapters)
    chapters = [ch for ch in chapters if start <= ch["chapter_number"] <= end_ch]

    if not chapters:
        gr.Warning(f"范围 {start}-{end_ch} 内没有章节")
        return f"范围 {start}-{end_ch} 内没有章节"

    log_lines = [f"准备发布 {len(chapters)} 章 (第{start}-{end_ch}章)"]
    log_lines.append("=" * 40)

    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    with sync_playwright() as p:
        kwargs = {
            "user_data_dir": str(_QIMAO_PROFILE_DIR),
            "headless": False,
        }
        if Path(chrome).exists():
            kwargs["executable_path"] = chrome
            kwargs["args"] = ["--disable-blink-features=AutomationControlled"]
        else:
            kwargs["channel"] = "chrome"

        context = p.chromium.launch_persistent_context(**kwargs)
        page = context.pages[0] if context.pages else context.new_page()

        progress(0.05, desc="进入作家后台...")
        page.goto("https://zuozhe.qimao.com")
        page.wait_for_load_state("networkidle")
        _time.sleep(2)

        # 进入章节管理
        mgmt = page.locator("a:has-text('章节管理'), span:has-text('章节管理')")
        if mgmt.count() > 0:
            mgmt.first.click()
            page.wait_for_load_state("networkidle")
            _time.sleep(2)
            log_lines.append("✓ 进入章节管理")

        chapter_mgmt_url = page.url
        uploaded = 0

        for idx, ch in enumerate(chapters):
            ch_num = ch["chapter_number"]
            ch_title = ch.get("title", f"第{ch_num}章")
            ch_text = ch.get("full_text", "")
            ch_wc = ch.get("word_count", len(ch_text))

            pct = 0.1 + 0.85 * idx / len(chapters)
            progress(pct, desc=f"上传第{ch_num}章 {ch_title}...")

            try:
                # 新建章节
                new_btn = page.locator(
                    "button:has-text('新建章节'), "
                    "a:has-text('新建章节'), "
                    "span:has-text('新建章节')"
                )
                if new_btn.count() == 0:
                    log_lines.append(f"✗ 第{ch_num}章: 未找到新建按钮")
                    continue
                new_btn.first.click()
                page.wait_for_load_state("networkidle")
                _time.sleep(2)

                # 标题
                title_area = page.locator(
                    "[placeholder*='章节名称'], [data-placeholder*='章节名称']"
                )
                if title_area.count() > 0:
                    title_area.first.click()
                    title_area.first.fill(ch_title)

                # 正文
                editable = page.locator("div[contenteditable='true']")
                if editable.count() > 0:
                    editable.first.click()
                    editable.first.fill(ch_text)

                _time.sleep(1)

                # 发布
                publish_clicked = False
                for btn_text in ["立即发布", "更新章节", "存为草稿"]:
                    loc = page.locator(f"text={btn_text}")
                    for i in range(loc.count()):
                        try:
                            if loc.nth(i).is_visible():
                                loc.nth(i).click(timeout=3000)
                                publish_clicked = True
                                break
                        except Exception:
                            continue
                    if publish_clicked:
                        break

                if publish_clicked:
                    _time.sleep(3)
                    # 处理弹窗
                    for _ in range(8):
                        _time.sleep(1)
                        done = False
                        for txt in [
                            "确认发布", "确认更新", "立即发布",
                            "我已阅读并知晓", "确定", "知道了",
                        ]:
                            loc = page.locator(f"text={txt}")
                            for i in range(loc.count()):
                                try:
                                    if loc.nth(i).is_visible():
                                        loc.nth(i).click(timeout=2000)
                                        done = True
                                        _time.sleep(2)
                                        break
                                except Exception:
                                    continue
                            if done:
                                break
                        if not done:
                            break

                    uploaded += 1
                    log_lines.append(f"✓ 第{ch_num}章 {ch_title} ({ch_wc}字)")

                # 返回章节管理
                page.goto(chapter_mgmt_url)
                page.wait_for_load_state("networkidle")
                _time.sleep(2)

            except Exception as e:
                log_lines.append(f"✗ 第{ch_num}章: {e}")
                try:
                    page.goto(chapter_mgmt_url)
                    page.wait_for_load_state("networkidle")
                    _time.sleep(2)
                except Exception:
                    pass

        context.storage_state(path=str(_QIMAO_AUTH_FILE))
        context.close()

    log_lines.append("=" * 40)
    log_lines.append(f"完成: {uploaded}/{len(chapters)} 章已发布")
    progress(1.0, desc="发布完成")
    return "\n".join(log_lines)


# ---------------------------------------------------------------------------
# Main video generation
# ---------------------------------------------------------------------------
def generate(
    text, file, style, voice, rate,
    image_backend, llm_backend, quality, resolution, codec,
    video_mode, videogen_backend,
    key_siliconflow, key_gemini, key_deepseek, key_openai, key_dashscope,
    key_kling, key_jimeng, key_minimax,
    run_mode, budget_mode, quality_threshold,
    progress=gr.Progress(),
):
    # 1. Resolve input text
    if file is not None:
        novel_text = Path(file).read_text(encoding="utf-8")
    elif text and text.strip():
        novel_text = text.strip()
    else:
        gr.Warning("请先输入或生成故事文本")
        return ("请先输入故事文本", None, None, "", [], None, "", gr.update(), gr.update(), gr.update())

    if len(novel_text) < 10:
        gr.Warning("文本内容太短，请输入至少 10 个字符")
        return ("文本太短", None, None, "", [], None, "", gr.update(), gr.update(), gr.update())

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

    # 5. 判断运行模式
    is_agent_mode = run_mode == "Agent模式（智能质控）"

    if is_agent_mode:
        mode_desc = "Agent模式：智能分析 -> 质量控制 -> 生成"
        if budget_mode:
            mode_desc += "（省钱模式）"
    else:
        mode_desc = "经典模式：直接生成"

    progress(0, desc=f"正在初始化... [{mode_desc}]")

    # 6. 创建并运行 Pipeline
    if is_agent_mode:
        from src.agent_pipeline import AgentPipeline

        def progress_cb(stage, total, desc):
            stage_name = AGENT_STAGES.get(stage, desc)
            progress(
                stage / total if total > 0 else 0,
                desc=f"阶段 {stage}/{total}: {stage_name}",
            )

        try:
            pipe = AgentPipeline(
                input_file=input_file,
                config=config,
                resume=False,
                budget_mode=budget_mode,
                quality_threshold=quality_threshold if quality_threshold else None,
            )
            output = pipe.run(progress_callback=progress_cb)
            workspace_path = str(pipe.workspace)
        except Exception as e:
            gr.Warning(f"Agent 模式生成失败: {e}")
            return (f"Agent 模式生成失败: {e}", None, None, "", [], [], "", gr.update(), gr.update(), gr.update())

        output_path = str(output)

        # 加载 Agent 分析结果
        analysis_md, image_paths, decisions_json, quality_md = _load_agent_results(
            workspace_path
        )

        return (
            f"Agent 模式生成完成!\n{mode_desc}\n输出文件: {output_path}",
            output_path,
            output_path,
            # Agent 专属输出
            analysis_md,
            image_paths,
            decisions_json,
            quality_md,
            # 显示 Agent Tabs
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(visible=True),
        )
    else:
        from src.pipeline import Pipeline

        def progress_cb(stage, total, desc):
            progress(
                stage / total if total > 0 else 0,
                desc=f"阶段 {stage}/{total}: {desc}",
            )

        try:
            pipe = Pipeline(input_file=input_file, config=config, resume=False)
            output = pipe.run(progress_callback=progress_cb)
        except Exception as e:
            gr.Warning(f"生成失败: {e}")
            return (f"生成失败: {e}", None, None, "", [], [], "", gr.update(), gr.update(), gr.update())

        output_path = str(output)
        return (
            f"经典模式生成完成!\n输出文件: {output_path}",
            output_path,
            output_path,
            # Agent 专属输出：空值
            "",
            [],
            [],
            "",
            # 隐藏 Agent Tabs
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )


# ---------------------------------------------------------------------------
# Quick config helpers
# ---------------------------------------------------------------------------
# Maps quick-radio labels -> advanced dropdown labels (must match LLM_CHOICES exactly)
_QUICK_LLM_TO_DROPDOWN = {
    "Gemini（免费推荐）": "Gemini",
    "DeepSeek": "DeepSeek",
    "OpenAI": "OpenAI",
    "Ollama（本地免费）": "Ollama本地",
}
# Maps quick-radio labels -> advanced dropdown labels (must match BACKEND_CHOICES exactly)
_QUICK_IMG_TO_DROPDOWN = {
    "SiliconFlow": "SiliconFlow",
    "阿里云通义": "阿里云通义",
}
# Maps quick-radio labels -> pipeline config values
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
# Service status helpers
# ---------------------------------------------------------------------------

# LLM service: label → settings key (None = no key needed)
_LLM_SERVICE_KEYS = {
    "Gemini": "key_gemini",
    "DeepSeek": "key_deepseek",
    "OpenAI": "key_openai",
    "Ollama（本地）": None,  # no key needed
}

# Image service: label → settings key
_IMG_SERVICE_KEYS = {
    "SiliconFlow": "key_siliconflow",
    "阿里云通义": "key_dashscope",
}


def _build_service_choices(service_keys: dict[str, str | None]) -> list[str]:
    """Build dropdown choices with status indicators.

    Returns labels like "Gemini  ✓" or "DeepSeek  ·未配置".
    """
    settings = load_settings()
    choices = []
    for label, key_name in service_keys.items():
        if key_name is None or settings.get(key_name):
            choices.append(f"{label}  ✓")
        else:
            choices.append(f"{label}  ·未配置")
    return choices


def _extract_service_name(choice: str) -> str:
    """Strip status suffix from a service choice label."""
    return choice.replace("  ✓", "").replace("  ·未配置", "").strip()


def _detect_default_llm_choice() -> str:
    """Pick the first configured LLM service as default choice."""
    choices = _build_service_choices(_LLM_SERVICE_KEYS)
    # prefer first configured
    for c in choices:
        if "✓" in c:
            return c
    return choices[0]


def _detect_default_img_choice() -> str:
    """Pick the first configured image service as default choice."""
    choices = _build_service_choices(_IMG_SERVICE_KEYS)
    for c in choices:
        if "✓" in c:
            return c
    return choices[0]


# ---------------------------------------------------------------------------
# Task queue submit / poll helpers
# ---------------------------------------------------------------------------

_TASK_TYPE_LABELS = {
    "novel_create": "创建小说",
    "novel_generate": "章节生成",
    "novel_polish": "AI 精修",
    "novel_feedback": "反馈重写",
    "director_generate": "AI 导演",
    "video_generate": "视频生成",
    "ppt_generate": "PPT 生成",
    "ppt_outline": "PPT 大纲生成",
    "ppt_continue": "PPT 继续生成",
}


def _submit_novel_create(
    theme, author_name, target_audience, genre, target_words,
    style, template, custom_ideas,
    llm_backend, key_gemini, key_deepseek, key_openai,
):
    """Submit novel_create to task server. Returns (task_id, status_text)."""
    if not theme or not theme.strip():
        gr.Warning("请输入主题/灵感")
        return "", "请输入主题/灵感"
    if not _ensure_task_server():
        gr.Warning("后端服务启动失败，请手动运行: python -m src.task_queue.server")
        return "", "后端服务未启动"
    try:
        task_id = _task_client.submit_task("novel_create", {
            "genre": NOVEL_GENRE_MAP.get(genre, "玄幻"),
            "theme": theme.strip(),
            "target_words": int(target_words * 10000) if target_words else 100000,
            "style": NOVEL_STYLE_MAP.get(style, "webnovel.shuangwen"),
            "template": NOVEL_TEMPLATE_MAP.get(template, "cyclic_upgrade"),
            "custom_ideas": custom_ideas.strip() if custom_ideas else "",
            "author_name": author_name.strip() if author_name else "",
            "target_audience": target_audience or "通用",
            "_keys": _collect_keys_dict(key_gemini, key_deepseek, key_openai),
        })
        return task_id, f"任务已提交 (ID: {task_id})，正在执行..."
    except Exception as e:
        gr.Warning(f"提交失败: {e}")
        return "", f"提交失败: {e}"


def _submit_novel_generate(
    project, batch_size, silent,
    llm_backend, key_gemini, key_deepseek, key_openai,
):
    """Submit novel_generate to task server."""
    if not project:
        gr.Warning("请先选择一个项目")
        return "", "请先选择一个项目"
    if not _ensure_task_server():
        return "", "后端服务未启动"
    project_path = _novel_extract_project_path(project)
    try:
        task_id = _task_client.submit_task("novel_generate", {
            "project_path": project_path,
            "start_chapter": None,  # auto-detect in worker
            "end_chapter": None,
            "batch_size": int(batch_size) if batch_size else 20,
            "silent": bool(silent),
            "_keys": _collect_keys_dict(key_gemini, key_deepseek, key_openai),
        })
        return task_id, f"章节生成任务已提交 (ID: {task_id})..."
    except Exception as e:
        return "", f"提交失败: {e}"


def _submit_novel_polish(
    project, start_ch, end_ch,
    llm_backend, key_gemini, key_deepseek, key_openai,
):
    """Submit novel_polish to task server."""
    if not project:
        return "", "请先选择项目"
    if not _ensure_task_server():
        return "", "后端服务未启动"
    project_path = _novel_extract_project_path(project)
    try:
        task_id = _task_client.submit_task("novel_polish", {
            "project_path": project_path,
            "start_chapter": int(start_ch) if start_ch and int(start_ch) > 0 else 1,
            "end_chapter": int(end_ch) if end_ch and int(end_ch) > 0 else None,
            "_keys": _collect_keys_dict(key_gemini, key_deepseek, key_openai),
        })
        return task_id, f"精修任务已提交 (ID: {task_id})..."
    except Exception as e:
        return "", f"提交失败: {e}"


def _submit_director_generate(
    inspiration, duration, budget_label,
    llm_service, img_service,
    key_gemini, key_deepseek, key_openai,
    key_siliconflow, key_dashscope,
    key_kling, key_jimeng, key_minimax,
    llm_backend_setting, img_backend_setting,
):
    """Submit director_generate to task server."""
    if not inspiration or not inspiration.strip():
        return "", "请输入灵感/创意"
    if not _ensure_task_server():
        return "", "后端服务未启动"

    llm_provider = LLM_MAP.get(llm_backend_setting, "auto")
    img_backend = BACKEND_MAP.get(img_backend_setting, "siliconflow")
    config = {
        "llm": {"provider": llm_provider},
        "imagegen": {"backend": img_backend},
        "video": {"codec": "libx265", "crf": 18, "resolution": [1080, 1920]},
    }
    budget = _DIRECTOR_BUDGET_MAP.get(budget_label, "low")
    try:
        task_id = _task_client.submit_task("director_generate", {
            "inspiration": inspiration.strip(),
            "target_duration": int(duration),
            "budget": budget,
            "config": config,
            "_keys": _collect_keys_dict(
                key_gemini, key_deepseek, key_openai,
                key_siliconflow, key_dashscope,
                key_kling, key_jimeng, key_minimax,
            ),
        })
        return task_id, f"导演任务已提交 (ID: {task_id})..."
    except Exception as e:
        return "", f"提交失败: {e}"


def _submit_video_generate(
    text, file, style, voice, rate,
    image_backend, llm_backend, quality, resolution, codec,
    video_mode, videogen_backend,
    key_siliconflow, key_gemini, key_deepseek, key_openai, key_dashscope,
    key_kling, key_jimeng, key_minimax,
    run_mode, budget_mode, quality_threshold,
):
    """Submit video_generate to task server."""
    # Resolve input text
    if file is not None:
        novel_text = Path(file).read_text(encoding="utf-8")
    elif text and text.strip():
        novel_text = text.strip()
    else:
        gr.Warning("请先输入或生成故事文本")
        return "", "请先输入故事文本"
    if len(novel_text) < 10:
        return "", "文本太短"
    if not _ensure_task_server():
        return "", "后端服务未启动"

    # Write to input file (same as original)
    input_dir = Path("input")
    input_dir.mkdir(exist_ok=True)
    text_hash = hashlib.md5(novel_text.encode()).hexdigest()[:8]
    input_file = input_dir / f"web_{text_hash}.txt"
    input_file.write_text(novel_text, encoding="utf-8")

    # Build config (same as original)
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
    if VIDEO_MODE_MAP.get(video_mode):
        vg_backend = VIDEOGEN_MAP.get(videogen_backend, "kling")
        config["videogen"] = {
            "backend": vg_backend, "duration": 5,
            "aspect_ratio": "9:16", "use_image_as_first_frame": True,
        }

    is_agent = run_mode == "Agent模式（智能质控）"
    try:
        task_id = _task_client.submit_task("video_generate", {
            "input_file": str(input_file),
            "config": config,
            "run_mode": "agent" if is_agent else "classic",
            "budget_mode": bool(budget_mode),
            "quality_threshold": quality_threshold if quality_threshold else None,
            "_keys": _collect_keys_dict(
                key_gemini, key_deepseek, key_openai,
                key_siliconflow, key_dashscope,
                key_kling, key_jimeng, key_minimax,
            ),
        })
        mode_desc = "Agent模式" if is_agent else "经典模式"
        return task_id, f"视频生成任务已提交 ({mode_desc}, ID: {task_id})..."
    except Exception as e:
        return "", f"提交失败: {e}"


def _submit_ppt_generate(
    text, theme, max_pages, gen_images, deck_type_choice,
    llm_backend_setting,
    key_gemini, key_deepseek, key_openai,
    key_siliconflow, key_dashscope,
):
    """Submit ppt_generate to task server."""
    if not text or not text.strip():
        gr.Warning("请输入文本或上传文档")
        return "", "请输入文本或上传文档"

    # 文档适配性预检（不阻断，仅提示；不适合的文档会在 pipeline 中自动改写）
    try:
        from src.ppt.document_analyzer import check_ppt_suitability
        suit_result = check_ppt_suitability(text)
        if not suit_result.suitable:
            gr.Info("该文档将自动改写为 PPT 友好版本后再生成")
    except ImportError:
        pass
    if not _ensure_task_server():
        return "", "后端服务未启动"

    llm_provider = LLM_MAP.get(llm_backend_setting, "auto")
    config = {
        "llm": {"provider": llm_provider},
        "imagegen": {"backend": "siliconflow"},
    }

    # Resolve deck_type: "auto" -> None (let pipeline auto-detect)
    resolved_deck_type = None if (not deck_type_choice or deck_type_choice == "auto") else deck_type_choice

    try:
        task_id = _task_client.submit_task("ppt_generate", {
            "text": text.strip(),
            "theme": theme or "modern",
            "max_pages": int(max_pages) if max_pages and int(max_pages) > 0 else None,
            "generate_images": bool(gen_images),
            "deck_type": resolved_deck_type,
            "config": config,
            "_keys": _collect_keys_dict(
                key_gemini, key_deepseek, key_openai,
                key_siliconflow, key_dashscope,
            ),
        })
        return task_id, f"任务已提交 (ID: {task_id})，正在执行..."
    except Exception as e:
        gr.Warning(f"提交失败: {e}")
        return "", f"提交失败: {e}"


def _extract_ppt_result(task: dict):
    """Extract results from a completed PPT task.

    Returns:
        (output_path, outline_markdown, quality_markdown, info_dict)
    """
    if not task:
        return None, "", "", {}
    result_str = task.get("result", "")
    if not result_str:
        return None, "", "", {}
    try:
        result = json.loads(result_str)
        output_path = result.get("output_path", "")

        # Format outline as Markdown
        outline_md = _format_ppt_outline_md(result.get("outline", []))

        # Format quality report as Markdown
        quality_md = _format_ppt_quality_md(result.get("quality_report", {}))

        # Info dict (exclude large fields already shown elsewhere)
        planning = result.get("planning") or {}
        deck_type_labels = {
            "business_report": "汇报材料",
            "course_lecture": "课程讲义",
            "product_intro": "产品介绍",
        }
        info = {
            "project_id": result.get("project_id", ""),
            "output_path": output_path,
        }
        if planning:
            dt = planning.get("deck_type", "")
            info["deck_type"] = deck_type_labels.get(dt, dt)
            info["core_message"] = planning.get("core_message", "")
            info["presentation_goal"] = planning.get("presentation_goal", "")
            info["audience"] = planning.get("audience", "")

        return output_path, outline_md, quality_md, info
    except Exception:
        return None, "", "", {}


def _format_ppt_outline_md(outline_data: list) -> str:
    """Format PPT outline data as readable Markdown."""
    if not outline_data:
        return "*大纲数据不可用*"

    lines = [f"## PPT 大纲（共 {len(outline_data)} 页）\n"]
    for page in outline_data:
        num = page.get("page_number", "?")
        title = page.get("title", "未命名")
        layout = page.get("layout", "unknown")
        subtitle = page.get("subtitle", "")

        lines.append(f"### 第 {num} 页 — {title}")
        lines.append(f"**布局**: `{layout}`")
        if subtitle:
            lines.append(f"**副标题**: {subtitle}")

        key_points = page.get("key_points", [])
        if key_points:
            lines.append("**要点**:")
            for kp in key_points:
                lines.append(f"- {kp}")

        if page.get("needs_image"):
            prompt = page.get("image_prompt", "")
            lines.append(f"**配图**: {prompt[:80]}{'...' if len(prompt or '') > 80 else ''}")

        lines.append("")  # blank line between pages

    return "\n".join(lines)


def _format_ppt_quality_md(quality_data: dict) -> str:
    """Format PPT quality report as readable Markdown."""
    if not quality_data:
        return "*质量报告不可用*"

    score = quality_data.get("score", 0)
    summary = quality_data.get("summary", "")
    total_pages = quality_data.get("total_pages", 0)
    issues = quality_data.get("issues", [])

    # Score emoji based on value
    if score >= 9:
        grade = "优秀"
    elif score >= 7:
        grade = "良好"
    elif score >= 5:
        grade = "一般"
    else:
        grade = "需改进"

    lines = [
        f"## 质量检查报告\n",
        f"**总评分**: {score}/10 （{grade}）",
        f"**总页数**: {total_pages}",
        f"**概要**: {summary}\n",
    ]

    if issues:
        lines.append("### 问题列表\n")
        lines.append("| 页码 | 类型 | 严重度 | 描述 | 可自动修复 |")
        lines.append("|------|------|--------|------|------------|")
        for issue in issues:
            page = issue.get("page_number", "?")
            itype = issue.get("issue_type", "")
            severity = issue.get("severity", "")
            desc = issue.get("description", "")
            fixable = "是" if issue.get("auto_fixable") else "否"
            lines.append(f"| {page} | {itype} | {severity} | {desc} | {fixable} |")
        lines.append("")
    else:
        lines.append("*未发现问题*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PPT V2 helpers: outline ↔ DataFrame conversion
# ---------------------------------------------------------------------------

def _editable_outline_to_df(outline):
    """EditableOutline -> DataFrame rows for gr.DataFrame display."""
    rows = []
    for slide in outline.slides:
        rows.append([
            slide.page_number,
            slide.role,
            slide.title,
            " | ".join(slide.key_points) if slide.key_points else "",
            slide.layout,
            slide.image_strategy,
        ])
    return rows


def _df_to_editable_outline(df_data, project_id):
    """DataFrame rows -> EditableOutline for pipeline consumption."""
    from src.ppt.models import EditableOutline, EditableSlide

    slides = []
    for row in df_data:
        if not row or len(row) < 6:
            continue
        page_num = int(row[0]) if row[0] else len(slides) + 1
        key_points = [kp.strip() for kp in str(row[3]).split("|") if kp.strip()]
        slides.append(EditableSlide(
            page_number=page_num,
            role=str(row[1]),
            title=str(row[2]),
            key_points=key_points,
            layout=str(row[4]),
            image_strategy=str(row[5]),
        ))

    return EditableOutline(
        project_id=project_id,
        total_pages=len(slides),
        slides=slides,
    )


def _submit_ppt_outline_generate(
    mode, topic, audience, scenario, doc_text, theme, target_pages,
    llm_backend_setting,
    key_gemini, key_deepseek, key_openai,
    key_siliconflow, key_dashscope,
):
    """Submit PPT outline generation to task queue (async).

    Returns (task_id, status_text).
    """
    if not _ensure_task_server():
        return "", "后端服务未启动"

    # Validate inputs early
    if mode == "从主题生成":
        if not topic or not topic.strip():
            gr.Warning("请输入主题")
            return "", "请输入主题"
    else:
        if not doc_text or not doc_text.strip():
            gr.Warning("请输入文档内容或上传文档")
            return "", "请输入文档内容或上传文档"

    llm_provider = LLM_MAP.get(llm_backend_setting, "auto")
    config = {
        "llm": {"provider": llm_provider},
        "imagegen": {"backend": "siliconflow"},
    }

    target_pg = int(target_pages) if target_pages and int(target_pages) > 0 else None

    task_params = {
        "topic": topic.strip() if topic else None,
        "document_text": doc_text.strip() if doc_text else None,
        "audience": audience or "business",
        "scenario": scenario or "quarterly_review",
        "theme": theme or "modern",
        "target_pages": target_pg,
        "config": config,
        "_keys": _collect_keys_dict(
            key_gemini, key_deepseek, key_openai,
            key_siliconflow, key_dashscope,
        ),
    }

    try:
        task_id = _task_client.submit_task("ppt_outline", task_params)
        return task_id, f"大纲生成中... (任务: {task_id})"
    except Exception as e:
        gr.Warning(f"提交失败: {e}")
        return "", f"提交失败: {e}"


def _submit_ppt_continue(
    project_id, df_data, gen_images, deck_type,
    llm_backend_setting,
    key_gemini, key_deepseek, key_openai,
    key_siliconflow, key_dashscope,
):
    """Submit PPT continue-from-outline task to background worker."""
    if not project_id:
        gr.Warning("没有可用的大纲项目，请先生成大纲")
        return "", "请先生成大纲"
    if not _ensure_task_server():
        return "", "后端服务未启动"

    # Convert DataFrame to list of lists (Gradio may return various formats)
    if hasattr(df_data, "values"):
        # pandas DataFrame
        df_data = df_data.values.tolist()
    elif isinstance(df_data, dict):
        # dict of columns
        import pandas as pd
        df_data = pd.DataFrame(df_data).values.tolist()

    if not df_data or len(df_data) == 0:
        gr.Warning("大纲为空，请先生成大纲")
        return "", "大纲为空"

    try:
        outline = _df_to_editable_outline(df_data, project_id)
    except Exception as e:
        gr.Warning(f"大纲数据解析失败: {e}")
        return "", f"大纲数据解析失败: {e}"

    llm_provider = LLM_MAP.get(llm_backend_setting, "auto")
    config = {
        "llm": {"provider": llm_provider},
        "imagegen": {"backend": "siliconflow"},
    }
    resolved_deck_type = None if (not deck_type or deck_type == "auto") else deck_type

    try:
        task_id = _task_client.submit_task("ppt_continue", {
            "project_id": project_id,
            "edited_outline": outline.model_dump(),
            "generate_images": bool(gen_images),
            "deck_type": resolved_deck_type,
            "config": config,
            "_keys": _collect_keys_dict(
                key_gemini, key_deepseek, key_openai,
                key_siliconflow, key_dashscope,
            ),
        })
        return task_id, f"PPT 生成任务已提交 (ID: {task_id})，正在执行..."
    except Exception as e:
        gr.Warning(f"提交失败: {e}")
        return "", f"提交失败: {e}"


def _poll_task(task_id: str) -> dict:
    """Poll a task's status. Returns raw task dict or empty dict."""
    if not task_id:
        return {}
    try:
        return _task_client.get_task(task_id)
    except Exception:
        return {}


def _format_task_progress(task: dict) -> str:
    """Format task status for display in status box."""
    if not task:
        return ""
    status = task.get("status", "unknown")
    progress = task.get("progress", 0)
    msg = task.get("progress_msg", "")
    pct = int(progress * 100)

    task_type = task.get("task_type", "")
    label = _TASK_TYPE_LABELS.get(task_type, task_type)

    if status == "pending":
        return f"[{label}] 排队中..."
    elif status == "running":
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        return f"[{label}] {bar} {pct}%\n{msg}"
    elif status == "completed":
        return f"[{label}] 已完成!"
    elif status == "failed":
        error = task.get("error", "未知错误")
        return f"[{label}] 失败: {error[:200]}"
    elif status == "cancelled":
        return f"[{label}] 已取消"
    return f"[{label}] {status}"


def _format_task_queue_table() -> str:
    """Format all tasks as a markdown table for the task queue panel."""
    try:
        tasks = _task_client.list_tasks(limit=20)
    except Exception:
        return "无法连接后端服务"
    if not tasks:
        return "暂无任务"

    lines = ["| 任务ID | 类型 | 状态 | 进度 | 信息 |",
             "|--------|------|------|------|------|"]
    status_icons = {
        "pending": "⏳", "running": "🔄", "completed": "✅",
        "failed": "❌", "cancelled": "🚫",
    }
    for t in tasks:
        tid = t.get("task_id", "?")
        ttype = _TASK_TYPE_LABELS.get(t.get("task_type", ""), "?")
        status = t.get("status", "?")
        icon = status_icons.get(status, "?")
        pct = int(t.get("progress", 0) * 100)
        msg = t.get("progress_msg", "")[:30]
        if t.get("error"):
            msg = t["error"][:30]
        lines.append(f"| {tid} | {ttype} | {icon} {status} | {pct}% | {msg} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Build Gradio UI
# ---------------------------------------------------------------------------
def create_ui() -> gr.Blocks:
    settings = load_settings()
    _has_any_key = any(settings.get(k) for k in ["key_gemini", "key_deepseek", "key_openai", "key_siliconflow"])
    _default_llm = _detect_quick_llm(settings)
    _default_img = _detect_quick_img(settings)

    with gr.Blocks(title="AI 创作工坊") as app:

        # ====== Hero header ======
        gr.HTML("""
        <div class="hero-section">
            <h1>AI 创作工坊</h1>
            <p>短视频故事 · AI 小说 — 一站式 AI 创作平台</p>
        </div>
        """)

        with gr.Tabs(elem_classes="top-tabs") as top_tabs:

            # ============================================================
            # Tab 0: AI 短视频导演（新流程）
            # ============================================================
            with gr.Tab("AI导演", id="tab_director"):
                with gr.Row(equal_height=False):
                    # ============== Left: Input ==============
                    with gr.Column(scale=5, elem_classes="input-card"):
                        gr.HTML('<div class="section-title">灵感输入</div>')
                        director_inspiration = gr.Textbox(
                            label="你的灵感/创意",
                            placeholder="例: 凌晨三点外卖员接到一单送往废弃医院的外卖...",
                            lines=3,
                        )
                        with gr.Row():
                            director_duration = gr.Slider(
                                label="目标时长(秒)",
                                minimum=15,
                                maximum=120,
                                step=5,
                                value=45,
                                scale=1,
                            )
                            director_budget = gr.Radio(
                                label="预算",
                                choices=["免费(纯图片)", "低(少量动态)", "中(部分视频)", "高(全视频)"],
                                value="低(少量动态)",
                                scale=2,
                            )
                        with gr.Row():
                            director_llm_select = gr.Dropdown(
                                label="AI 服务",
                                choices=_build_service_choices(_LLM_SERVICE_KEYS),
                                value=_detect_default_llm_choice(),
                                scale=1,
                            )
                            director_img_select = gr.Dropdown(
                                label="图片服务",
                                choices=_build_service_choices(_IMG_SERVICE_KEYS),
                                value=_detect_default_img_choice(),
                                scale=1,
                            )

                        with gr.Row():
                            director_generate_btn = gr.Button(
                                "一键生成视频",
                                variant="primary",
                                size="lg",
                                elem_classes="generate-btn",
                                scale=4,
                            )
                            director_new_btn = gr.Button(
                                "新建", variant="secondary", size="lg", scale=1, min_width=80,
                            )

                        # 历史记录
                        gr.HTML('<div class="section-title">历史记录</div>')
                        with gr.Row():
                            director_project_select = gr.Dropdown(
                                label="已生成的视频",
                                choices=_director_list_projects(),
                                value=None,
                                scale=4,
                            )
                            director_load_btn = gr.Button(
                                "加载", size="sm", scale=1, min_width=60,
                            )
                            director_refresh_btn = gr.Button(
                                "刷新", size="sm", variant="secondary", scale=1, min_width=60,
                            )

                        # 脚本预览区（生成后显示）
                        gr.HTML('<div class="section-title">脚本预览</div>')
                        director_script_display = gr.JSON(
                            label="结构化脚本",
                        )

                    # ============== Right: Output ==============
                    with gr.Column(scale=4, elem_classes="output-card"):
                        director_status = gr.Textbox(
                            label="状态",
                            interactive=False,
                            lines=4,
                            elem_classes="status-area",
                        )
                        with gr.Tabs():
                            with gr.Tab("视频预览"):
                                director_video = gr.Video(label="视频", height=400)
                                director_file = gr.File(label="下载")
                            with gr.Tab("视频方案"):
                                director_idea_display = gr.JSON(label="视频方案")
                            with gr.Tab("分段详情"):
                                director_segments_display = gr.Markdown(
                                    value="生成后显示各段详情..."
                                )

            # ============================================================
            # Tab 1: 短视频制作 (all existing content)
            # ============================================================
            with gr.Tab("短视频制作", id="tab_video"):

                with gr.Row(equal_height=False):
                    # ============== Left column: Input ==============
                    with gr.Column(scale=5, elem_classes="input-card"):
                        with gr.Tabs():
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
                                # 服务选择（Key 在「设置」Tab 统一管理）
                                with gr.Row():
                                    video_llm_select = gr.Dropdown(
                                        label="AI 服务 (LLM)",
                                        choices=_build_service_choices(_LLM_SERVICE_KEYS),
                                        value=_detect_default_llm_choice(),
                                        scale=1,
                                    )
                                    video_img_select = gr.Dropdown(
                                        label="图片服务",
                                        choices=_build_service_choices(_IMG_SERVICE_KEYS),
                                        value=_detect_default_img_choice(),
                                        scale=1,
                                    )
                                gr.Markdown(
                                    '*✓ 表示已配置 Key，未配置请前往「设置」Tab*',
                                    elem_classes="service-hint",
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

                        with gr.Accordion("高级选项", open=False):
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

                            video_mode.change(
                                fn=lambda mode: gr.update(visible=VIDEO_MODE_MAP.get(mode) is not None),
                                inputs=[video_mode],
                                outputs=[videogen_backend],
                                show_progress="hidden",
                            )

                            run_mode_radio = gr.Radio(
                                label="运行模式",
                                choices=RUN_MODE_CHOICES,
                                value="经典模式（快速）",
                                info="经典模式快速生成；Agent模式多AI协作+自动质控",
                            )

                            with gr.Group(visible=False) as agent_options_group:
                                with gr.Row():
                                    budget_mode_checkbox = gr.Checkbox(
                                        label="省钱模式",
                                        value=False,
                                        info="跳过质量检查，减少API调用",
                                    )
                                    quality_threshold_slider = gr.Slider(
                                        label="图片质量阈值",
                                        minimum=1,
                                        maximum=10,
                                        step=0.5,
                                        value=6.0,
                                        info="低于此分数的图片自动重新生成",
                                    )

                            run_mode_radio.change(
                                fn=lambda mode: gr.update(visible=mode == "Agent模式（智能质控）"),
                                inputs=[run_mode_radio],
                                outputs=[agent_options_group],
                                show_progress="hidden",
                            )

                        with gr.Row():
                            generate_btn = gr.Button(
                                "生成视频",
                                variant="primary",
                                size="lg",
                                elem_classes="generate-btn",
                                scale=4,
                            )
                            video_new_btn = gr.Button(
                                "新建", variant="secondary", size="lg", scale=1, min_width=80,
                            )

                    # ============== Right column: Output ==============
                    with gr.Column(scale=4, elem_classes="output-card"):
                        status_box = gr.Textbox(
                            label="当前状态",
                            interactive=False,
                            lines=3,
                            elem_classes="status-area",
                        )

                        with gr.Tabs():
                            # --- 视频预览 Tab ---
                            with gr.Tab("视频预览"):
                                video_output = gr.Video(label="视频预览", height=400)
                                file_output = gr.File(label="下载视频")

                            # --- Agent 分析 Tab（默认隐藏）---
                            with gr.Tab("Agent 分析", visible=False) as agent_tab:
                                agent_analysis = gr.Markdown(
                                    label="内容分析",
                                    value="Agent 模式生成后将显示内容分析结果...",
                                )
                                agent_gallery = gr.Gallery(
                                    label="生成的图片",
                                    columns=3,
                                    height=300,
                                )

                            # --- 决策日志 Tab（默认隐藏）---
                            with gr.Tab("决策日志", visible=False) as decision_tab:
                                decision_display = gr.JSON(label="Agent 决策记录")

                            # --- 质量报告 Tab（默认隐藏）---
                            with gr.Tab("质量报告", visible=False) as quality_tab:
                                quality_report = gr.Markdown(
                                    label="质量报告",
                                    value="Agent 模式生成后将显示质量报告...",
                                )

            # ============================================================
            # Tab 2: AI 小说
            # ============================================================
            with gr.Tab("AI 小说", id="tab_novel"):

                with gr.Row(equal_height=False):
                    # ============== Left column: Novel Input ==============
                    with gr.Column(scale=5, elem_classes="input-card"):

                        # --- Section 1: 创建小说项目 ---
                        gr.HTML('<div class="section-title">创建小说项目</div>')
                        novel_theme_input = gr.Textbox(
                            label="主题/灵感",
                            placeholder="例: 少年修炼逆天改命，一路打脸升级...",
                            lines=2,
                        )
                        with gr.Row():
                            novel_author = gr.Textbox(
                                label="笔名",
                                placeholder="例: 唐家三少",
                                scale=1,
                            )
                            novel_audience = gr.Radio(
                                label="目标读者",
                                choices=["男频", "女频", "通用"],
                                value="通用",
                                scale=1,
                            )
                        with gr.Row():
                            novel_genre = gr.Dropdown(
                                label="题材",
                                choices=NOVEL_GENRE_CHOICES,
                                value="玄幻",
                                scale=1,
                            )
                            novel_words = gr.Slider(
                                label="目标字数（万字）",
                                minimum=0.5,
                                maximum=50,
                                step=0.5,
                                value=10,
                                scale=1,
                            )
                        with gr.Row():
                            novel_style = gr.Dropdown(
                                label="风格",
                                choices=NOVEL_STYLE_CHOICES,
                                value="网文爽文",
                                scale=1,
                            )
                            novel_template = gr.Dropdown(
                                label="大纲模板",
                                choices=NOVEL_TEMPLATE_CHOICES,
                                value="循环升级（玄幻/系统流）",
                                scale=1,
                            )
                        with gr.Accordion("自定义想法 / 大纲描述", open=False) as novel_custom_accordion:
                            novel_custom_ideas = gr.Textbox(
                                label="额外创意/自定义大纲结构",
                                placeholder="例: 主角有双重人格；前10章校园生活，中间穿越异世界，最后回归现实...",
                                lines=4,
                                info="选择「自定义」模板时，在这里描述你想要的故事结构",
                            )
                        with gr.Row():
                            novel_create_btn = gr.Button(
                                "创建项目",
                                variant="secondary",
                                size="lg",
                                elem_classes="story-btn",
                                scale=4,
                            )
                            novel_new_btn = gr.Button(
                                "新建", variant="secondary", size="lg", scale=1, min_width=80,
                            )

                        # --- Section 2: 章节生成 ---
                        gr.HTML('<div class="section-title">章节生成</div>')
                        novel_project_select = gr.Dropdown(
                            label="项目选择",
                            choices=_novel_list_projects(),
                            value=None,
                        )
                        novel_batch_size = gr.Slider(
                            label="本次生成章节数",
                            minimum=1,
                            maximum=50,
                            step=1,
                            value=20,
                            info="从当前进度自动续写，每次写一批",
                        )
                        novel_silent = gr.Checkbox(
                            label="静默模式（跳过审核暂停）",
                            value=True,
                        )
                        novel_generate_btn = gr.Button(
                            "继续写作",
                            variant="primary",
                            size="lg",
                            elem_classes="novel-btn",
                        )

                        # --- Section 3: AI 精修 ---
                        gr.HTML('<div class="section-title">AI 精修</div>')
                        gr.Markdown("*AI 自动审稿并修改，无需手动输入反馈*", elem_classes="hint-text")
                        with gr.Row():
                            novel_polish_start = gr.Number(
                                label="起始章节",
                                value=1,
                                minimum=1,
                                precision=0,
                                scale=1,
                            )
                            novel_polish_end = gr.Number(
                                label="结束章节（0=全部）",
                                value=0,
                                minimum=0,
                                precision=0,
                                scale=1,
                            )
                        novel_polish_btn = gr.Button(
                            "开始精修",
                            variant="secondary",
                            size="lg",
                            elem_classes="story-btn",
                        )

                    # ============== Right column: Novel Output ==============
                    with gr.Column(scale=4, elem_classes="output-card"):
                        novel_status_box = gr.Textbox(
                            label="状态",
                            interactive=False,
                            lines=4,
                            elem_classes="status-area",
                        )

                        with gr.Tabs():
                            with gr.Tab("大纲预览"):
                                novel_outline_display = gr.Markdown(
                                    value="创建项目后将显示大纲...",
                                )
                            with gr.Tab("角色设定"):
                                novel_chars_display = gr.Markdown(
                                    value="创建项目后将显示角色...",
                                )
                            with gr.Tab("世界观"):
                                novel_world_display = gr.Markdown(
                                    value="创建项目后将显示世界观...",
                                )
                            with gr.Tab("章节内容"):
                                novel_chapter_list = gr.Markdown(
                                    value="*选择项目后显示章节目录*",
                                    label="章节目录",
                                )
                                with gr.Row():
                                    novel_read_ch_num = gr.Number(
                                        label="跳转章节",
                                        value=1,
                                        minimum=1,
                                        precision=0,
                                        scale=2,
                                    )
                                    novel_read_btn = gr.Button(
                                        "加载章节", size="sm", scale=1,
                                    )
                                novel_chapter_display = gr.Textbox(
                                    label="章节文本",
                                    interactive=False,
                                    lines=20,
                                    max_lines=50,
                                )
                            with gr.Tab("项目信息"):
                                novel_info_display = gr.JSON(
                                    label="项目详情",
                                )
                            with gr.Tab("精修报告"):
                                novel_polish_report = gr.Markdown(
                                    value="*精修完成后显示修改报告...*",
                                )
                                gr.HTML('<div class="section-title">章节对比查看</div>')
                                with gr.Row():
                                    novel_diff_ch_num = gr.Number(
                                        label="章节号",
                                        value=1,
                                        minimum=1,
                                        precision=0,
                                        scale=2,
                                    )
                                    novel_diff_btn = gr.Button(
                                        "查看对比", size="sm", scale=1,
                                    )
                                novel_diff_display = gr.Markdown(
                                    value="*选择章节号后点击查看修改前后对比*",
                                )

                        with gr.Row():
                            novel_refresh_btn = gr.Button(
                                "刷新状态", variant="secondary", scale=1,
                            )
                            novel_export_btn = gr.Button(
                                "导出 TXT", variant="secondary", scale=1,
                            )
                            novel_delete_btn = gr.Button(
                                "删除项目", variant="stop", scale=1,
                            )
                            novel_export_file = gr.File(
                                label="下载文件", visible=True, scale=1,
                            )

            # ============================================================
            # Tab 3: PPT 生成 (V2: 双模式 + 大纲编辑)
            # ============================================================
            with gr.Tab("PPT生成", id="tab_ppt"):

                with gr.Row(equal_height=False):
                    # ============== Left: Input ==============
                    with gr.Column(scale=5, elem_classes="input-card"):
                        gr.HTML('<div class="section-title">AI 智能 PPT 生成</div>')
                        gr.Markdown(
                            "从主题直接生成，或上传文档转换为 PPT。"
                            "生成大纲后可编辑，确认后再生成完整 PPT。",
                            elem_classes="hint-text",
                        )

                        # --- Mode selector ---
                        ppt_mode = gr.Radio(
                            label="生成模式",
                            choices=["从主题生成", "从文档转换"],
                            value="从主题生成",
                        )

                        # --- Topic mode form ---
                        with gr.Group(visible=True) as ppt_topic_group:
                            ppt_topic_input = gr.Textbox(
                                label="PPT 主题",
                                placeholder="例如：2024年Q3季度业绩汇报、Python异步编程入门...",
                                lines=2,
                            )
                            with gr.Row():
                                ppt_audience = gr.Dropdown(
                                    label="受众类型",
                                    choices=[
                                        ("商务人士", "business"),
                                        ("技术人员", "technical"),
                                        ("教育场景", "educational"),
                                        ("创意人群", "creative"),
                                        ("通用", "general"),
                                    ],
                                    value="business",
                                    scale=1,
                                )
                                ppt_scenario = gr.Dropdown(
                                    label="使用场景",
                                    choices=[
                                        ("季度汇报", "quarterly_review"),
                                        ("产品发布", "product_launch"),
                                        ("技术分享", "tech_share"),
                                        ("课程讲义", "course_lecture"),
                                        ("融资路演", "pitch_deck"),
                                        ("工作坊", "workshop"),
                                        ("进度更新", "status_update"),
                                    ],
                                    value="quarterly_review",
                                    scale=1,
                                )
                            ppt_materials_file = gr.File(
                                label="零散材料（可选，.txt/.md）",
                                file_types=[".txt", ".md"],
                                type="filepath",
                            )

                        # --- Document mode form ---
                        with gr.Group(visible=False) as ppt_doc_group:
                            ppt_text_input = gr.Textbox(
                                label="文档内容",
                                placeholder="粘贴您的文档内容，或上传文件后自动填充...",
                                lines=10,
                                max_lines=30,
                            )
                            ppt_file_input = gr.File(
                                label="上传文档 (.txt / .md)",
                                file_types=[".txt", ".md"],
                                type="filepath",
                            )

                        # --- Common settings ---
                        with gr.Row():
                            ppt_theme = gr.Dropdown(
                                label="主题风格",
                                choices=[
                                    ("简约现代", "modern"),
                                    ("商务正式", "business"),
                                    ("创意活泼", "creative"),
                                    ("科技极客", "tech"),
                                    ("教育清新", "education"),
                                ],
                                value="modern",
                                scale=1,
                            )
                            ppt_max_pages = gr.Slider(
                                label="目标页数",
                                minimum=0, maximum=30, step=1, value=15,
                                info="0 = 自动确定",
                                scale=1,
                            )
                        ppt_gen_images = gr.Checkbox(
                            label="生成 AI 配图（关闭可加快速度）",
                            value=True,
                        )

                        # --- Generate outline button ---
                        with gr.Row():
                            ppt_outline_btn = gr.Button(
                                "生成大纲",
                                variant="primary",
                                size="lg",
                                elem_classes="story-btn",
                                scale=4,
                            )
                            ppt_new_btn = gr.Button(
                                "新建", variant="secondary", size="lg", scale=1, min_width=80,
                            )

                        # --- Outline editor (initially hidden) ---
                        with gr.Group(visible=False) as ppt_outline_editor:
                            gr.Markdown(
                                "### 大纲编辑\n"
                                "可直接编辑表格中的内容。"
                                "要点用 `|` 分隔多条。"
                                "编辑完成后点击「确认并生成 PPT」。"
                            )
                            ppt_outline_df = gr.DataFrame(
                                headers=["页码", "角色", "标题", "要点", "布局", "配图策略"],
                                datatype=["number", "str", "str", "str", "str", "str"],
                                interactive=True,
                                col_count=(6, "fixed"),
                                wrap=True,
                            )
                            with gr.Row():
                                ppt_delete_row_btn = gr.Button(
                                    "删除末页", variant="secondary", size="sm",
                                )
                                ppt_add_row_btn = gr.Button(
                                    "新增一页", variant="secondary", size="sm",
                                )
                            with gr.Row():
                                ppt_confirm_btn = gr.Button(
                                    "确认并生成 PPT",
                                    variant="primary",
                                    size="lg",
                                    elem_classes="story-btn",
                                )
                                ppt_deck_type = gr.Radio(
                                    label="PPT 类型",
                                    choices=[
                                        ("自动检测", "auto"),
                                        ("汇报材料", "business_report"),
                                        ("课程讲义", "course_lecture"),
                                        ("产品介绍", "product_intro"),
                                    ],
                                    value="auto",
                                )

                        # --- Legacy one-click button (hidden, for poll timer compat) ---
                        ppt_generate_btn = gr.Button(
                            "生成 PPT", visible=False,
                        )

                    # ============== Right: Output ==============
                    with gr.Column(scale=4, elem_classes="output-card"):
                        ppt_status_box = gr.Textbox(
                            label="状态",
                            interactive=False,
                            lines=4,
                            elem_classes="status-area",
                        )

                        with gr.Tabs():
                            with gr.Tab("生成结果"):
                                ppt_output_file = gr.File(
                                    label="下载 PPT",
                                    interactive=False,
                                )
                            with gr.Tab("大纲预览"):
                                ppt_outline_display = gr.Markdown(
                                    value="*生成大纲后将显示...*",
                                )
                            with gr.Tab("质量报告"):
                                ppt_quality_display = gr.Markdown(
                                    value="*生成后将显示质量检查报告...*",
                                )
                            with gr.Tab("项目信息"):
                                ppt_info_display = gr.JSON(
                                    label="项目详情",
                                )

            # ============================================================
            # Tab 4: 全局设置
            # ============================================================
            with gr.Tab("设置", id="tab_settings"):

                with gr.Row(equal_height=False):
                    # ============== Left column: API 密钥 ==============
                    with gr.Column(scale=5, elem_classes="input-card"):
                        gr.HTML('<div class="section-title">LLM & 图片服务密钥</div>')
                        gr.Markdown("密钥自动保存到本地 (`~/.novel-video/settings.json`)，不会上传到任何服务器。", elem_classes="hint-text")
                        with gr.Row():
                            key_gemini = gr.Textbox(
                                label="Gemini", type="password",
                                value=settings.get("key_gemini", ""),
                                placeholder="AIza...", scale=5,
                            )
                            btn_test_gemini = gr.Button("测试", size="sm", scale=1, min_width=60)
                        with gr.Row():
                            key_deepseek = gr.Textbox(
                                label="DeepSeek", type="password",
                                value=settings.get("key_deepseek", ""),
                                placeholder="sk-...", scale=5,
                            )
                            btn_test_ds = gr.Button("测试", size="sm", scale=1, min_width=60)
                        with gr.Row():
                            key_openai = gr.Textbox(
                                label="OpenAI", type="password",
                                value=settings.get("key_openai", ""),
                                placeholder="sk-...", scale=5,
                            )
                            btn_test_openai = gr.Button("测试", size="sm", scale=1, min_width=60)
                        with gr.Row():
                            key_siliconflow = gr.Textbox(
                                label="SiliconFlow (图片)", type="password",
                                value=settings.get("key_siliconflow", ""),
                                placeholder="sk-...", scale=5,
                            )
                            btn_test_sf = gr.Button("测试", size="sm", scale=1, min_width=60)
                        with gr.Row():
                            key_dashscope = gr.Textbox(
                                label="阿里云 DashScope (图片)", type="password",
                                value=settings.get("key_dashscope", ""),
                                placeholder="sk-...", scale=5,
                            )
                            btn_test_dashscope = gr.Button("测试", size="sm", scale=1, min_width=60)

                        gr.HTML('<div class="section-title">视频生成 API 密钥</div>')
                        gr.Markdown("AI 视频片段模式需要以下服务的 Key（按需配置）。", elem_classes="hint-text")
                        key_kling = gr.Textbox(
                            label="可灵 Kling", type="password",
                            value=settings.get("key_kling", ""),
                            placeholder="API Key",
                        )
                        key_jimeng = gr.Textbox(
                            label="即梦 Seedance", type="password",
                            value=settings.get("key_jimeng", ""),
                            placeholder="API Key",
                        )
                        key_minimax = gr.Textbox(
                            label="MiniMax 海螺", type="password",
                            value=settings.get("key_minimax", ""),
                            placeholder="API Key",
                        )

                    # ============== Right column: 后端 & 画质 ==============
                    with gr.Column(scale=4, elem_classes="output-card"):
                        gr.HTML('<div class="section-title">后端 & 画质</div>')
                        llm_backend = gr.Dropdown(
                            label="LLM 后端",
                            choices=LLM_CHOICES,
                            value=_QUICK_LLM_TO_DROPDOWN.get(_default_llm, "自动检测"),
                        )
                        image_backend = gr.Dropdown(
                            label="图片生成后端",
                            choices=BACKEND_CHOICES,
                            value=_QUICK_IMG_TO_DROPDOWN.get(_default_img, "SiliconFlow"),
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

            # ============================================================
            # Tab 4: 任务队列
            # ============================================================
            with gr.Tab("任务队列", id="tab_tasks"):
                with gr.Row():
                    with gr.Column(scale=8):
                        task_queue_display = gr.Markdown(
                            value="加载中...",
                            label="任务列表",
                        )
                    with gr.Column(scale=2):
                        task_refresh_btn = gr.Button("刷新", variant="secondary")
                        task_cancel_id = gr.Textbox(
                            label="任务 ID",
                            placeholder="输入要操作的任务ID",
                        )
                        task_cancel_btn = gr.Button("取消任务", variant="stop")
                        task_delete_btn = gr.Button("删除记录", variant="stop")
                        task_action_status = gr.Textbox(
                            label="操作结果",
                            interactive=False,
                            lines=2,
                        )

        # ====== Hidden states for task polling ======
        novel_create_task_id = gr.State("")
        novel_gen_task_id = gr.State("")
        novel_polish_task_id = gr.State("")
        director_task_id = gr.State("")
        video_task_id = gr.State("")
        ppt_task_id = gr.State("")
        ppt_project_id = gr.State("")
        ppt_editable_outline = gr.State(None)

        # Timer for polling (active when any task is running)
        poll_timer = gr.Timer(value=2, active=False)

        # ====== "新建" Reset handlers ======

        def _reset_director():
            """Reset AI导演 tab to initial state."""
            return (
                "",              # director_inspiration
                45,              # director_duration
                "低(少量动态)",   # director_budget
                gr.update(interactive=True, value="一键生成视频"),  # director_generate_btn
                "",              # director_status
                None,            # director_video
                None,            # director_file
                None,            # director_script_display
                None,            # director_idea_display
                "生成后显示各段详情...",  # director_segments_display
                "",              # director_task_id
            )

        director_new_btn.click(
            fn=_reset_director,
            outputs=[
                director_inspiration, director_duration, director_budget,
                director_generate_btn,
                director_status, director_video, director_file,
                director_script_display, director_idea_display,
                director_segments_display,
                director_task_id,
            ],
        )

        def _reset_video():
            """Reset 短视频制作 tab to initial state."""
            return (
                "",              # topic_input
                gr.update(interactive=True, value="生成视频"),  # generate_btn
                "",              # status_box
                None,            # video_output
                None,            # file_output
                "",              # video_task_id
            )

        video_new_btn.click(
            fn=_reset_video,
            outputs=[
                topic_input,
                generate_btn,
                status_box, video_output, file_output,
                video_task_id,
            ],
        )

        def _reset_novel():
            """Reset AI小说 tab to initial state."""
            return (
                "",              # novel_theme_input
                "",              # novel_custom_ideas
                gr.update(interactive=True, value="创建项目"),   # novel_create_btn
                gr.update(interactive=True, value="继续写作"),   # novel_generate_btn
                gr.update(interactive=True, value="开始精修"),   # novel_polish_btn
                "",              # novel_status_box
                "创建项目后将显示大纲...",    # novel_outline_display
                "创建项目后将显示角色...",    # novel_chars_display
                "创建项目后将显示世界观...",  # novel_world_display
                "",              # novel_chapter_display
                None,            # novel_info_display
                "*精修完成后显示修改报告...*",  # novel_polish_report
                "",              # novel_create_task_id
                "",              # novel_gen_task_id
                "",              # novel_polish_task_id
            )

        novel_new_btn.click(
            fn=_reset_novel,
            outputs=[
                novel_theme_input, novel_custom_ideas,
                novel_create_btn, novel_generate_btn, novel_polish_btn,
                novel_status_box,
                novel_outline_display, novel_chars_display, novel_world_display,
                novel_chapter_display, novel_info_display, novel_polish_report,
                novel_create_task_id, novel_gen_task_id, novel_polish_task_id,
            ],
        )

        def _reset_ppt():
            """Reset PPT生成 tab to initial state."""
            return (
                "从主题生成",    # ppt_mode
                "",              # ppt_topic_input
                "",              # ppt_text_input
                gr.update(interactive=True, value="生成大纲"),  # ppt_outline_btn
                gr.update(interactive=True, value="确认并生成 PPT"),  # ppt_confirm_btn
                gr.update(visible=False),  # ppt_outline_editor
                "",              # ppt_status_box
                None,            # ppt_output_file
                "",              # ppt_outline_display
                "",              # ppt_quality_display
                None,            # ppt_info_display
                "",              # ppt_task_id
                "",              # ppt_project_id
                None,            # ppt_editable_outline
                gr.update(visible=True),   # ppt_topic_group
                gr.update(visible=False),  # ppt_doc_group
            )

        ppt_new_btn.click(
            fn=_reset_ppt,
            outputs=[
                ppt_mode, ppt_topic_input, ppt_text_input,
                ppt_outline_btn, ppt_confirm_btn,
                ppt_outline_editor,
                ppt_status_box,
                ppt_output_file, ppt_outline_display,
                ppt_quality_display, ppt_info_display,
                ppt_task_id, ppt_project_id, ppt_editable_outline,
                ppt_topic_group, ppt_doc_group,
            ],
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

        # -- Service selector → sync to settings backend dropdowns --
        _LLM_NAME_TO_BACKEND = {
            "Gemini": "Gemini",
            "DeepSeek": "DeepSeek",
            "OpenAI": "OpenAI",
            "Ollama（本地）": "Ollama本地",
        }
        _IMG_NAME_TO_BACKEND = {
            "SiliconFlow": "SiliconFlow",
            "阿里云通义": "阿里云通义",
        }

        def _on_video_llm_change(choice):
            name = _extract_service_name(choice)
            backend_label = _LLM_NAME_TO_BACKEND.get(name, "自动检测")
            return gr.update(value=backend_label)
        video_llm_select.change(
            fn=_on_video_llm_change, inputs=[video_llm_select],
            outputs=[llm_backend],
            show_progress="hidden",
        )

        def _on_video_img_change(choice):
            name = _extract_service_name(choice)
            backend_label = _IMG_NAME_TO_BACKEND.get(name, "SiliconFlow")
            return gr.update(value=backend_label)
        video_img_select.change(
            fn=_on_video_img_change, inputs=[video_img_select],
            outputs=[image_backend],
            show_progress="hidden",
        )

        # Refresh service status indicators when switching to video tab
        def _refresh_service_status():
            return (
                gr.update(choices=_build_service_choices(_LLM_SERVICE_KEYS)),
                gr.update(choices=_build_service_choices(_IMG_SERVICE_KEYS)),
            )
        top_tabs.select(fn=_refresh_service_status, outputs=[video_llm_select, video_img_select], show_progress="hidden")

        # Test buttons
        btn_test_sf.click(fn=_test_siliconflow, inputs=[key_siliconflow], show_progress="hidden")
        btn_test_gemini.click(fn=_test_gemini, inputs=[key_gemini], show_progress="hidden")
        btn_test_ds.click(fn=_test_deepseek, inputs=[key_deepseek], show_progress="hidden")
        btn_test_openai.click(fn=_test_openai, inputs=[key_openai], show_progress="hidden")
        btn_test_dashscope.click(fn=_test_dashscope, inputs=[key_dashscope], show_progress="hidden")

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

        # Video generation (submit to task queue)
        def _on_video_submit(
            text, file, style, voice, rate,
            img_be, llm_be, quality, res, codec,
            vid_mode, vg_be,
            k_sf, k_gem, k_ds, k_oai, k_dash,
            k_kl, k_jm, k_mm,
            run_mode, budget_mode, quality_threshold,
        ):
            task_id, status = _submit_video_generate(
                text, file, style, voice, rate,
                img_be, llm_be, quality, res, codec,
                vid_mode, vg_be,
                k_sf, k_gem, k_ds, k_oai, k_dash,
                k_kl, k_jm, k_mm,
                run_mode, budget_mode, quality_threshold,
            )
            return (
                task_id, status,
                gr.update(interactive=False, value="生成中..."),
                gr.Timer(active=bool(task_id)),
            )

        generate_btn.click(
            fn=_on_video_submit,
            inputs=[
                txt_input, file_input,
                style_dropdown, voice_dropdown, rate_radio,
                image_backend, llm_backend, quality_radio, resolution_radio, codec_radio,
                video_mode, videogen_backend,
                key_siliconflow, key_gemini, key_deepseek, key_openai, key_dashscope,
                key_kling, key_jimeng, key_minimax,
                run_mode_radio, budget_mode_checkbox, quality_threshold_slider,
            ],
            outputs=[
                video_task_id, status_box,
                generate_btn, poll_timer,
            ],
        )

        # ====== Novel event wiring ======

        # Auto-open custom ideas when "自定义" template selected
        def _on_template_change(template):
            is_custom = "自定义" in template
            return gr.update(open=is_custom)
        novel_template.change(
            fn=_on_template_change, inputs=[novel_template],
            outputs=[novel_custom_accordion],
            show_progress="hidden",
        )

        # Create novel project (submit to task queue)
        def _on_novel_create_submit(
            theme, author, audience, genre, words, style, template, custom,
            llm_be, k_gem, k_ds, k_oai,
        ):
            task_id, status = _submit_novel_create(
                theme, author, audience, genre, words, style, template, custom,
                llm_be, k_gem, k_ds, k_oai,
            )
            return (
                task_id,
                status,
                gr.update(interactive=False, value="创建中..."),
                gr.Timer(active=bool(task_id)),
            )

        novel_create_btn.click(
            fn=_on_novel_create_submit,
            inputs=[
                novel_theme_input, novel_author, novel_audience,
                novel_genre, novel_words,
                novel_style, novel_template, novel_custom_ideas,
                llm_backend, key_gemini, key_deepseek, key_openai,
            ],
            outputs=[
                novel_create_task_id,
                novel_status_box,
                novel_create_btn,
                poll_timer,
            ],
        )

        # Auto-load project data when project is selected
        _refresh_outputs = [
            novel_status_box,
            novel_chapter_display,
            novel_chapter_list,
            novel_outline_display,
            novel_chars_display,
            novel_world_display,
            novel_info_display,
        ]
        novel_project_select.change(
            fn=_novel_refresh_status,
            inputs=[novel_project_select],
            outputs=_refresh_outputs,
            show_progress="hidden",
        )

        # Generate chapters (submit to task queue)
        def _on_novel_gen_submit(project, batch, silent, llm_be, k_gem, k_ds, k_oai):
            task_id, status = _submit_novel_generate(
                project, batch, silent, llm_be, k_gem, k_ds, k_oai,
            )
            return (
                task_id, status,
                gr.update(interactive=False, value="写作中..."),
                gr.Timer(active=bool(task_id)),
            )

        novel_generate_btn.click(
            fn=_on_novel_gen_submit,
            inputs=[
                novel_project_select, novel_batch_size,
                novel_silent,
                llm_backend, key_gemini, key_deepseek, key_openai,
            ],
            outputs=[
                novel_gen_task_id, novel_status_box,
                novel_generate_btn, poll_timer,
            ],
        )

        # Load specific chapter
        novel_read_btn.click(
            fn=_novel_load_chapter,
            inputs=[novel_project_select, novel_read_ch_num],
            outputs=[novel_chapter_display],
        )

        # Refresh: first update project list, then refresh status
        novel_refresh_btn.click(
            fn=lambda: gr.update(choices=_novel_list_projects()),
            inputs=[],
            outputs=[novel_project_select],
        ).then(
            fn=_novel_refresh_status,
            inputs=[novel_project_select],
            outputs=_refresh_outputs,
        )

        # Delete project (with JS confirm dialog)
        novel_delete_btn.click(
            fn=None,
            inputs=None,
            outputs=None,
            js="() => { if (!confirm('确定要删除该项目吗？此操作无法恢复！')) { throw new Error('cancelled'); } }",
        ).then(
            fn=_novel_delete_project,
            inputs=[novel_project_select],
            outputs=[novel_status_box, novel_project_select],
        )

        # Export novel
        def _novel_export_wrapper(project):
            status, path = _novel_export(project)
            return status, path
        novel_export_btn.click(
            fn=_novel_export_wrapper,
            inputs=[novel_project_select],
            outputs=[novel_status_box, novel_export_file],
        )


        # Polish chapters (submit to task queue)
        def _on_novel_polish_submit(project, start, end, llm_be, k_gem, k_ds, k_oai):
            task_id, status = _submit_novel_polish(
                project, start, end, llm_be, k_gem, k_ds, k_oai,
            )
            return (
                task_id, status,
                gr.update(interactive=False, value="精修中..."),
                gr.Timer(active=bool(task_id)),
            )

        novel_polish_btn.click(
            fn=_on_novel_polish_submit,
            inputs=[
                novel_project_select, novel_polish_start, novel_polish_end,
                llm_backend, key_gemini, key_deepseek, key_openai,
            ],
            outputs=[
                novel_polish_task_id, novel_status_box,
                novel_polish_btn, poll_timer,
            ],
        )

        # Polish diff viewer
        novel_diff_btn.click(
            fn=_novel_load_polish_diff,
            inputs=[novel_project_select, novel_diff_ch_num],
            outputs=[novel_diff_display],
        )

        # ====== Director event wiring (submit to task queue) ======
        def _on_director_submit(
            insp, dur, budget, llm_svc, img_svc,
            k_gem, k_ds, k_oai, k_sf, k_dash, k_kl, k_jm, k_mm,
            llm_be, img_be,
        ):
            task_id, status = _submit_director_generate(
                insp, dur, budget, llm_svc, img_svc,
                k_gem, k_ds, k_oai, k_sf, k_dash, k_kl, k_jm, k_mm,
                llm_be, img_be,
            )
            return (
                task_id, status,
                gr.update(interactive=False, value="生成中..."),
                gr.Timer(active=bool(task_id)),
            )

        director_generate_btn.click(
            fn=_on_director_submit,
            inputs=[
                director_inspiration, director_duration, director_budget,
                director_llm_select, director_img_select,
                key_gemini, key_deepseek, key_openai,
                key_siliconflow, key_dashscope,
                key_kling, key_jimeng, key_minimax,
                llm_backend, image_backend,
            ],
            outputs=[
                director_task_id, director_status,
                director_generate_btn, poll_timer,
            ],
        )

        # Director: load history project
        director_load_btn.click(
            fn=_director_load_project,
            inputs=[director_project_select],
            outputs=[
                director_status,
                director_video,
                director_file,
                director_script_display,
                director_idea_display,
                director_segments_display,
            ],
        )

        # Director: refresh project list
        director_refresh_btn.click(
            fn=lambda: gr.update(choices=_director_list_projects()),
            outputs=[director_project_select],
            show_progress="hidden",
        )

        # ====== PPT tab events ======

        # Mode switcher: show/hide topic vs document form
        def _on_ppt_mode_change(mode):
            if mode == "从主题生成":
                return gr.update(visible=True), gr.update(visible=False)
            else:
                return gr.update(visible=False), gr.update(visible=True)

        ppt_mode.change(
            fn=_on_ppt_mode_change,
            inputs=[ppt_mode],
            outputs=[ppt_topic_group, ppt_doc_group],
        )

        # File upload -> auto-fill text (document mode)
        def _ppt_on_file_upload(file_path):
            if file_path:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception as e:
                    return f"文件读取失败: {e}"
            return ""

        ppt_file_input.change(
            fn=_ppt_on_file_upload,
            inputs=[ppt_file_input],
            outputs=[ppt_text_input],
        )

        # Generate outline button — submits to task queue
        def _on_ppt_outline_generate(
            mode, topic, audience, scenario, doc_text,
            theme, max_pages,
            llm_be, k_gem, k_ds, k_oai, k_sf, k_dash,
        ):
            task_id, status_text = _submit_ppt_outline_generate(
                mode, topic, audience, scenario, doc_text,
                theme, max_pages,
                llm_be, k_gem, k_ds, k_oai, k_sf, k_dash,
            )
            if task_id:
                btn_update = gr.update(interactive=False, value="大纲生成中...")
            else:
                btn_update = gr.update()  # don't change button on failure
            return (
                task_id,               # ppt_task_id state
                status_text,           # ppt_status_box
                btn_update,            # ppt_outline_btn
                gr.Timer(active=bool(task_id)),  # poll_timer
            )

        ppt_outline_btn.click(
            fn=_on_ppt_outline_generate,
            inputs=[
                ppt_mode, ppt_topic_input, ppt_audience, ppt_scenario,
                ppt_text_input,
                ppt_theme, ppt_max_pages,
                llm_backend, key_gemini, key_deepseek, key_openai,
                key_siliconflow, key_dashscope,
            ],
            outputs=[
                ppt_task_id,
                ppt_status_box,
                ppt_outline_btn,
                poll_timer,
            ],
        )

        # Add row to outline table
        def _ppt_add_row(df_data):
            if df_data is None or len(df_data) == 0:
                new_row = [1, "knowledge_point", "新页面", "要点1 | 要点2", "bullet_with_icons", "none"]
            else:
                next_num = len(df_data) + 1
                new_row = [next_num, "knowledge_point", "新页面", "要点1 | 要点2", "bullet_with_icons", "none"]
            rows = list(df_data) if df_data is not None else []
            rows.append(new_row)
            return rows

        ppt_add_row_btn.click(
            fn=_ppt_add_row,
            inputs=[ppt_outline_df],
            outputs=[ppt_outline_df],
        )

        # Delete last row from outline table
        def _ppt_delete_row(df_data):
            if df_data is None or len(df_data) == 0:
                return df_data
            rows = list(df_data)
            rows.pop()
            # Renumber pages
            for i, row in enumerate(rows):
                row[0] = i + 1
            return rows

        ppt_delete_row_btn.click(
            fn=_ppt_delete_row,
            inputs=[ppt_outline_df],
            outputs=[ppt_outline_df],
        )

        # Confirm outline and submit PPT generation task
        def _on_ppt_confirm_submit(
            proj_id, df_data, gen_images, deck_type_val,
            llm_be, k_gem, k_ds, k_oai, k_sf, k_dash,
        ):
            task_id, status = _submit_ppt_continue(
                proj_id, df_data, gen_images, deck_type_val,
                llm_be, k_gem, k_ds, k_oai, k_sf, k_dash,
            )
            if task_id:
                btn_update = gr.update(interactive=False, value="PPT 生成中...")
            else:
                btn_update = gr.update()  # don't change button on failure
            return (
                task_id,
                status,
                btn_update,
                gr.Timer(active=bool(task_id)),
            )

        ppt_confirm_btn.click(
            fn=_on_ppt_confirm_submit,
            inputs=[
                ppt_project_id, ppt_outline_df, ppt_gen_images, ppt_deck_type,
                llm_backend, key_gemini, key_deepseek, key_openai,
                key_siliconflow, key_dashscope,
            ],
            outputs=[
                ppt_task_id, ppt_status_box,
                ppt_confirm_btn, poll_timer,
            ],
        )

        # ====== Poll timer handler ======
        def _poll_all_tasks(
            nc_tid, ng_tid, np_tid, dir_tid, vid_tid, ppt_tid,
        ):
            """Poll all active tasks. Returns updated status boxes + button states + timer."""
            results = {
                "novel_create": _poll_task(nc_tid) if nc_tid else {},
                "novel_generate": _poll_task(ng_tid) if ng_tid else {},
                "novel_polish": _poll_task(np_tid) if np_tid else {},
                "director": _poll_task(dir_tid) if dir_tid else {},
                "ppt": _poll_task(ppt_tid) if ppt_tid else {},
                "video": _poll_task(vid_tid) if vid_tid else {},
            }

            # Determine which tasks are still active
            any_active = False
            outputs = []

            # Novel create status
            nc = results["novel_create"]
            nc_status = nc.get("status", "") if nc else ""
            nc_done = nc_status in ("completed", "failed", "cancelled")
            if nc_tid and not nc_done:
                any_active = True

            # Novel generate status
            ng = results["novel_generate"]
            ng_status = ng.get("status", "") if ng else ""
            ng_done = ng_status in ("completed", "failed", "cancelled")
            if ng_tid and not ng_done:
                any_active = True

            # Novel polish status
            np_ = results["novel_polish"]
            np_status = np_.get("status", "") if np_ else ""
            np_done = np_status in ("completed", "failed", "cancelled")
            if np_tid and not np_done:
                any_active = True

            # Director status
            dr = results["director"]
            dr_status = dr.get("status", "") if dr else ""
            dr_done = dr_status in ("completed", "failed", "cancelled")
            if dir_tid and not dr_done:
                any_active = True

            # Video status
            vd = results["video"]
            vd_status = vd.get("status", "") if vd else ""
            vd_done = vd_status in ("completed", "failed", "cancelled")
            if vid_tid and not vd_done:
                any_active = True

            # PPT status
            pt = results["ppt"]
            pt_status = pt.get("status", "") if pt else ""
            pt_done = pt_status in ("completed", "failed", "cancelled")
            if ppt_tid and not pt_done:
                any_active = True

            # Build status text for the most recently active task
            # (update the appropriate status box)
            novel_status = ""
            if nc_tid and nc:
                novel_status = _format_task_progress(nc)
            elif ng_tid and ng:
                novel_status = _format_task_progress(ng)
            elif np_tid and np_:
                novel_status = _format_task_progress(np_)

            dir_status_text = _format_task_progress(dr) if dir_tid and dr else gr.update()
            vid_status_text = _format_task_progress(vd) if vid_tid and vd else gr.update()
            ppt_status_text = _format_task_progress(pt) if ppt_tid and pt else gr.update()

            # Extract PPT results when task completes
            pt_task_type = pt.get("task_type", "") if pt else ""
            if pt_done and pt_status == "completed" and pt_task_type == "ppt_outline":
                # Outline generation completed — populate DataFrame + show editor
                try:
                    result_str = pt.get("result", "{}")
                    import json as _json
                    pt_result = _json.loads(result_str) if isinstance(result_str, str) else result_str
                    from src.ppt.models import EditableOutline as _EO
                    outline_obj = _EO(**pt_result["outline"])
                    df_rows = _editable_outline_to_df(outline_obj)
                    # Build preview markdown
                    preview_parts = []
                    for s in outline_obj.slides:
                        kp_text = "\n".join(f"- {kp}" for kp in s.key_points) if s.key_points else ""
                        preview_parts.append(
                            f"### 第 {s.page_number} 页 — {s.title}\n"
                            f"**角色**: `{s.role}` | **布局**: `{s.layout}`\n{kp_text}"
                        )
                    outline_md = f"## 大纲预览（共 {len(outline_obj.slides)} 页）\n\n" + "\n\n".join(preview_parts)
                    ppt_proj_id_out = pt_result.get("project_id", "")
                    ppt_outline_obj_out = outline_obj
                    ppt_df_out = df_rows
                    ppt_editor_vis = gr.update(visible=True)
                    ppt_outline_md = outline_md
                except Exception:
                    ppt_proj_id_out = gr.update()
                    ppt_outline_obj_out = gr.update()
                    ppt_df_out = gr.update()
                    ppt_editor_vis = gr.update()
                    ppt_outline_md = gr.update()
                ppt_file = gr.update()
                ppt_quality = gr.update()
                ppt_info = gr.update()
            elif pt_done and pt_status == "completed":
                # PPT continue/generate completed — show result file
                ppt_file, ppt_outline_md, ppt_quality, ppt_info = _extract_ppt_result(pt)
                ppt_proj_id_out = gr.update()
                ppt_outline_obj_out = gr.update()
                ppt_df_out = gr.update()
                ppt_editor_vis = gr.update()
            else:
                ppt_file = gr.update()
                ppt_outline_md = gr.update()
                ppt_quality = gr.update()
                ppt_info = gr.update()
                ppt_proj_id_out = gr.update()
                ppt_outline_obj_out = gr.update()
                ppt_df_out = gr.update()
                ppt_editor_vis = gr.update()

            # Extract director results when task completes
            if dr_done and dr_status == "completed":
                dr_video, dr_file, dr_script, dr_idea, dr_seg_md = (
                    _extract_director_result_from_task(dr)
                )
            else:
                dr_video = gr.update()
                dr_file = gr.update()
                dr_script = gr.update()
                dr_idea = gr.update()
                dr_seg_md = gr.update()

            # Extract video results when task completes
            if vd_done and vd_status == "completed":
                try:
                    import json as _json
                    vd_result = _json.loads(vd.get("result", "{}"))
                    vd_path = vd_result.get("output", vd_result.get("output_path", ""))
                    if vd_path and Path(vd_path).exists():
                        vid_video_out = str(vd_path)
                        vid_file_out = str(vd_path)
                    else:
                        vid_video_out = gr.update()
                        vid_file_out = gr.update()
                except Exception:
                    vid_video_out = gr.update()
                    vid_file_out = gr.update()
            else:
                vid_video_out = gr.update()
                vid_file_out = gr.update()

            # Extract novel create results when task completes
            if nc_done and nc_status == "completed":
                try:
                    import json as _json
                    nc_result = _json.loads(nc.get("result", "{}"))
                    nc_novel_id = nc_result.get("novel_id", "")
                    nc_project_path = f"workspace/novels/{nc_novel_id}"
                    # Refresh project data
                    nc_refresh = _novel_refresh_status(
                        f"{nc_result.get('title', nc_novel_id)} ({nc_novel_id})"
                        if nc_result.get("title")
                        else nc_novel_id
                    )
                    novel_create_status = nc_refresh[0]
                    novel_create_ch = nc_refresh[1]
                    novel_create_ch_list = nc_refresh[2]
                    novel_create_outline = nc_refresh[3]
                    novel_create_chars = nc_refresh[4]
                    novel_create_world = nc_refresh[5]
                    novel_create_info = nc_refresh[6]
                    # Auto-select new project in dropdown
                    novel_project_update = gr.update(
                        choices=_novel_list_projects(), value=nc_project_path,
                    )
                except Exception:
                    novel_create_status = gr.update()
                    novel_create_ch = gr.update()
                    novel_create_ch_list = gr.update()
                    novel_create_outline = gr.update()
                    novel_create_chars = gr.update()
                    novel_create_world = gr.update()
                    novel_create_info = gr.update()
                    novel_project_update = gr.update(choices=_novel_list_projects())
            else:
                novel_create_status = gr.update()
                novel_create_ch = gr.update()
                novel_create_ch_list = gr.update()
                novel_create_outline = gr.update()
                novel_create_chars = gr.update()
                novel_create_world = gr.update()
                novel_create_info = gr.update()
                # Refresh project list when novel generate completes too
                if ng_done and ng_status == "completed":
                    novel_project_update = gr.update(choices=_novel_list_projects())
                else:
                    novel_project_update = gr.update()

            # Extract polish report when task completes
            if np_done and np_status == "completed":
                polish_report = _extract_novel_polish_result(np_)
            else:
                polish_report = gr.update()

            # Auto-refresh task queue table when any task is active
            queue_table = _format_task_queue_table() if any_active else gr.update()

            # Determine correct button text for PPT outline button on completion
            if pt_done and pt_task_type == "ppt_outline":
                ppt_outline_btn_update = gr.update(interactive=True, value="重新生成大纲")
                ppt_confirm_btn_update = gr.update()  # don't touch confirm btn
            elif pt_done:
                ppt_outline_btn_update = gr.update(interactive=True, value="生成大纲")
                ppt_confirm_btn_update = gr.update(interactive=True, value="确认并生成 PPT")
            else:
                ppt_outline_btn_update = gr.update()
                ppt_confirm_btn_update = gr.update()

            return (
                # Status boxes
                novel_status if novel_status else gr.update(),
                dir_status_text,
                vid_status_text,
                ppt_status_text,
                # Button re-enable when done
                gr.update(interactive=True, value="创建项目") if nc_done else gr.update(),
                gr.update(interactive=True, value="继续写作") if ng_done else gr.update(),
                gr.update(interactive=True, value="开始精修") if np_done else gr.update(),
                gr.update(interactive=True, value="一键生成视频") if dr_done else gr.update(),
                gr.update(interactive=True, value="生成视频") if vd_done else gr.update(),
                gr.update(interactive=True, value="生成 PPT") if pt_done else gr.update(),
                # PPT V2 buttons re-enable
                ppt_confirm_btn_update,
                ppt_outline_btn_update,
                # Timer
                gr.Timer(active=any_active),
                # Clear task_ids when done
                "" if nc_done else gr.update(),
                "" if ng_done else gr.update(),
                "" if np_done else gr.update(),
                "" if dr_done else gr.update(),
                "" if vd_done else gr.update(),
                "" if pt_done else gr.update(),
                # Director result outputs
                dr_video, dr_file,
                dr_script, dr_idea, dr_seg_md,
                # Video result outputs
                vid_video_out, vid_file_out,
                # Novel create result outputs
                novel_create_outline, novel_create_chars,
                novel_create_world, novel_create_info,
                novel_create_ch, novel_create_ch_list,
                novel_project_update,
                # Polish report
                polish_report,
                # PPT result outputs
                ppt_file, ppt_outline_md,
                ppt_quality, ppt_info,
                # PPT outline editor outputs (populated on outline completion)
                ppt_proj_id_out, ppt_outline_obj_out,
                ppt_df_out, ppt_editor_vis,
                # Task queue table (auto-refresh)
                queue_table,
            )

        poll_timer.tick(
            fn=_poll_all_tasks,
            inputs=[
                novel_create_task_id, novel_gen_task_id, novel_polish_task_id,
                director_task_id, video_task_id, ppt_task_id,
            ],
            outputs=[
                novel_status_box, director_status, status_box, ppt_status_box,
                novel_create_btn, novel_generate_btn, novel_polish_btn,
                director_generate_btn, generate_btn, ppt_generate_btn,
                ppt_confirm_btn, ppt_outline_btn,
                poll_timer,
                novel_create_task_id, novel_gen_task_id, novel_polish_task_id,
                director_task_id, video_task_id, ppt_task_id,
                # Director result outputs (populated on completion)
                director_video, director_file,
                director_script_display, director_idea_display,
                director_segments_display,
                # Video result outputs (populated on completion)
                video_output, file_output,
                # Novel create result outputs (populated on completion)
                novel_outline_display, novel_chars_display,
                novel_world_display, novel_info_display,
                novel_chapter_display, novel_chapter_list,
                novel_project_select,
                # Polish report (populated on completion)
                novel_polish_report,
                # PPT result outputs (populated on completion)
                ppt_output_file, ppt_outline_display,
                ppt_quality_display, ppt_info_display,
                # PPT outline editor outputs (populated on outline completion)
                ppt_project_id, ppt_editable_outline,
                ppt_outline_df, ppt_outline_editor,
                # Task queue table (auto-refresh)
                task_queue_display,
            ],
        )

        # ====== Task queue tab events ======
        task_refresh_btn.click(
            fn=_format_task_queue_table,
            outputs=[task_queue_display],
        )

        def _on_task_cancel(task_id):
            if not task_id:
                return "请输入任务 ID"
            try:
                result = _task_client.cancel_task(task_id)
                return result.get("msg", "已取消")
            except Exception as e:
                return f"取消失败: {e}"

        task_cancel_btn.click(
            fn=_on_task_cancel,
            inputs=[task_cancel_id],
            outputs=[task_action_status],
        )

        def _on_task_delete(task_id):
            if not task_id:
                return "请输入任务 ID"
            try:
                _task_client.delete_task(task_id)
                return "已删除"
            except Exception as e:
                return f"删除失败: {e}"

        task_delete_btn.click(
            fn=_on_task_delete,
            inputs=[task_cancel_id],
            outputs=[task_action_status],
        )

        # Refresh novel project list + task queue on tab select
        def _on_tab_select():
            return gr.update(choices=_novel_list_projects()), _format_task_queue_table()
        top_tabs.select(fn=_on_tab_select, outputs=[novel_project_select, task_queue_display], show_progress="hidden")

        # --- Load saved keys on page open (workaround for Gradio password fields) ---
        _key_components = [
            key_gemini, key_deepseek, key_openai, key_siliconflow,
            key_dashscope, key_kling, key_jimeng, key_minimax,
        ]
        _key_names = [
            "key_gemini", "key_deepseek", "key_openai", "key_siliconflow",
            "key_dashscope", "key_kling", "key_jimeng", "key_minimax",
        ]

        def _load_all_keys():
            s = load_settings()
            return [s.get(n, "") for n in _key_names]

        app.load(fn=_load_all_keys, outputs=_key_components)
        app.load(fn=_format_task_queue_table, outputs=[task_queue_display])

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    _ensure_task_server()
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
        head=DROPDOWN_FIX_HEAD,
    )
