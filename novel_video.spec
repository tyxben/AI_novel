# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 - AI 小说转视频

用法:
    pyinstaller novel_video.spec

Mac 输出: dist/AI小说转视频.app
Windows 输出: dist/AI小说转视频/AI小说转视频.exe
"""

import platform
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

# 收集 Gradio 和 edge-tts 的全部数据文件
gradio_datas, gradio_binaries, gradio_hiddenimports = collect_all('gradio')
gradio_client_datas, gradio_client_binaries, gradio_client_hiddenimports = collect_all('gradio_client')
edge_tts_datas, edge_tts_binaries, edge_tts_hiddenimports = collect_all('edge_tts')

all_datas = [
    ('config.yaml', '.'),
    ('src/', 'src/'),
]
all_datas += gradio_datas
all_datas += gradio_client_datas
all_datas += edge_tts_datas

all_binaries = gradio_binaries + gradio_client_binaries + edge_tts_binaries

all_hiddenimports = [
    'gradio',
    'gradio_client',
    'edge_tts',
    'PIL',
    'yaml',
    'click',
    'rich',
    'aiofiles',
    'httpx',
    'src',
    'src.pipeline',
    'src.config_manager',
    'src.checkpoint',
    'src.logger',
    'src.segmenter',
    'src.segmenter.text_segmenter',
    'src.segmenter.simple_segmenter',
    'src.segmenter.llm_segmenter',
    'src.promptgen',
    'src.promptgen.prompt_generator',
    'src.promptgen.style_presets',
    'src.promptgen.character_tracker',
    'src.imagegen',
    'src.imagegen.image_generator',
    'src.imagegen.siliconflow_backend',
    'src.imagegen.dashscope_backend',
    'src.imagegen.together_backend',
    'src.imagegen.diffusers_backend',
    'src.tts',
    'src.tts.tts_engine',
    'src.tts.subtitle_generator',
    'src.video',
    'src.video.video_assembler',
    'src.video.effects',
    'src.llm',
    'src.llm.llm_client',
    'src.llm.openai_backend',
    'src.llm.gemini_backend',
    'src.llm.ollama_backend',
    'src.utils',
    'src.utils.ffmpeg_helper',
]
all_hiddenimports += gradio_hiddenimports
all_hiddenimports += gradio_client_hiddenimports
all_hiddenimports += edge_tts_hiddenimports

a = Analysis(
    ['web.py'],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch',
        'diffusers',
        'transformers',
        'accelerate',
        'safetensors',
        'triton',
        'nvidia',
    ],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AI小说转视频',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 无控制台窗口
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AI小说转视频',
)

# macOS .app bundle
if platform.system() == 'Darwin':
    app = BUNDLE(
        coll,
        name='AI小说转视频.app',
        bundle_identifier='com.novel-video.app',
        info_plist={
            'CFBundleDisplayName': 'AI小说转视频',
            'CFBundleShortVersionString': '0.4.0',
            'NSHighResolutionCapable': True,
        },
    )
