"""AssetStrategy - 为每段脚本分配素材类型和生成策略"""
from __future__ import annotations
import logging
from src.scriptplan.models import AssetType, MotionType, SegmentPurpose, VideoScript

log = logging.getLogger("scriptplan")

# 成本预算档位
BUDGET_PROFILES = {
    "free": {
        # 全部用静图，零成本
        "max_video_segments": 0,
        "max_i2v_segments": 0,
    },
    "low": {
        # 最多1段AI视频，2段图生视频
        "max_video_segments": 0,
        "max_i2v_segments": 2,
    },
    "medium": {
        # 最多2段AI视频，其余图生视频
        "max_video_segments": 1,
        "max_i2v_segments": 3,
    },
    "high": {
        # 全部用AI视频
        "max_video_segments": 99,
        "max_i2v_segments": 99,
    },
}

# 用途 → 素材优先级（从高到低）
_PURPOSE_ASSET_PRIORITY: dict[str, list[AssetType]] = {
    "hook": [AssetType.IMAGE2VIDEO, AssetType.IMAGE],      # 开场尽量动态
    "setup": [AssetType.IMAGE, AssetType.IMAGE2VIDEO],      # 铺垫静图够用
    "develop": [AssetType.IMAGE, AssetType.IMAGE2VIDEO],    # 发展段看预算
    "twist": [AssetType.IMAGE2VIDEO, AssetType.VIDEO],      # 反转段要动态
    "climax": [AssetType.IMAGE2VIDEO, AssetType.VIDEO],     # 高潮段要动态
    "ending": [AssetType.IMAGE, AssetType.IMAGE2VIDEO],     # 结尾可以静
}


class AssetStrategy:
    """为脚本的每个段落分配素材类型。"""

    def assign(self, script: VideoScript, budget: str = "low") -> VideoScript:
        """根据预算分配素材类型。

        Args:
            script: 视频脚本
            budget: 预算档位 (free/low/medium/high)

        Returns:
            更新了 asset_type 的 VideoScript
        """
        profile = BUDGET_PROFILES.get(budget, BUDGET_PROFILES["low"])
        max_video = profile["max_video_segments"]
        max_i2v = profile["max_i2v_segments"]

        video_count = 0
        i2v_count = 0

        # 按优先级排序：hook和twist段优先获得动态素材
        priority_order = [
            SegmentPurpose.HOOK,
            SegmentPurpose.TWIST,
            SegmentPurpose.CLIMAX,
            SegmentPurpose.DEVELOP,
            SegmentPurpose.SETUP,
            SegmentPurpose.ENDING,
        ]

        # 先按优先级分配
        segments_by_priority = sorted(
            script.segments,
            key=lambda s: (
                priority_order.index(s.purpose) if s.purpose in priority_order else 99
            ),
        )

        for seg in segments_by_priority:
            priorities = _PURPOSE_ASSET_PRIORITY.get(
                seg.purpose.value, [AssetType.IMAGE],
            )
            assigned = AssetType.IMAGE  # 默认静图

            for asset_type in priorities:
                if asset_type == AssetType.VIDEO and video_count < max_video:
                    assigned = AssetType.VIDEO
                    video_count += 1
                    break
                elif asset_type == AssetType.IMAGE2VIDEO and i2v_count < max_i2v:
                    assigned = AssetType.IMAGE2VIDEO
                    i2v_count += 1
                    break
                elif asset_type == AssetType.IMAGE:
                    assigned = AssetType.IMAGE
                    break

            seg.asset_type = assigned

            # 镜头运动规则：静图段默认用 Ken Burns 效果
            if assigned == AssetType.IMAGE and seg.motion == MotionType.STATIC:
                # 给静图加点动感
                if seg.purpose in (SegmentPurpose.HOOK, SegmentPurpose.TWIST):
                    seg.motion = MotionType.PUSH_IN
                elif seg.purpose == SegmentPurpose.ENDING:
                    seg.motion = MotionType.ZOOM  # zoom out 效果

        log.info(
            "素材分配完成: %d段图片, %d段图生视频, %d段AI视频",
            sum(1 for s in script.segments if s.asset_type == AssetType.IMAGE),
            i2v_count,
            video_count,
        )

        return script
