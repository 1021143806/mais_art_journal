"""mais_art_journal 共享常量"""

# Base64 图片格式前缀，用于区分 base64 数据与 URL
# JPEG: /9j/  PNG: iVBORw  WEBP: UklGR  GIF: R0lGOD
BASE64_IMAGE_PREFIXES = ("iVBORw", "/9j/", "UklGR", "R0lGOD")

# 自拍通用手部质量负面提示词（所有自拍风格共用）
SELFIE_HAND_NEGATIVE = (
    "extra fingers, missing fingers, fused fingers, too many fingers, "
    "mutated hands, malformed hands, bad hands, wrong hands, "
    "extra hands, extra arms, 3 hands, 4 hands, multiple hands, "
    "deformed fingers, interlocked fingers, twisted fingers, "
    "six fingers, more than 5 fingers, fewer than 5 fingers, "
    "extra digit, missing digit, bad anatomy"
)

# 标准自拍专用：防止生成双手拿手机等不自然姿态
ANTI_DUAL_PHONE_PROMPT = (
    "two phones, camera in both hands, "
    "holding phone with both hands, "
    "both hands holding phone, "
    "phone in frame, visible phone in hand, "
    "both hands visible"
)

# 第三人称照片专用：明确主体不是在自拍，也不应手持拍摄设备
PHOTO_NO_PHONE_PROMPT = (
    "phone, smartphone, cellphone, mobile phone, "
    "visible phone, phone in hand, holding phone, "
    "camera in hand, selfie, selfie stick, taking selfie"
)

# 向后兼容别名
ANTI_DUAL_HANDS_PROMPT = f"{SELFIE_HAND_NEGATIVE}, {ANTI_DUAL_PHONE_PROMPT}"
