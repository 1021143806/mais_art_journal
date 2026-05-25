"""mais_art_journal 共享常量"""

# Base64 图片格式前缀，用于区分 base64 数据与 URL
# JPEG: /9j/  PNG: iVBORw  WEBP: UklGR  GIF: R0lGOD
BASE64_IMAGE_PREFIXES = ("iVBORw", "/9j/", "UklGR", "R0lGOD")

# 自拍通用手部质量负面提示词（所有自拍风格共用）
SELFIE_HAND_NEGATIVE = (
    "(extra fingers:1.4), (missing fingers:1.4), (fused fingers:1.4), (too many fingers:1.5), "
    "(mutated hands:1.5), (malformed hands:1.5), (bad hands:1.4), (wrong hands:1.4), "
    "(extra hands:1.6), (extra arms:1.6), (3 hands:1.7), (4 hands:1.7), (multiple hands:1.6), "
    "(deformed fingers:1.4), (interlocked fingers:1.3), (twisted fingers:1.4), "
    "(six fingers:1.5), (more than 5 fingers:1.5), (fewer than 5 fingers:1.4), "
    "(extra digit:1.4), (missing digit:1.4), (bad anatomy:1.3), "
    "(multiple arms:1.6), (extra limbs:1.5), (deformed hands:1.5), "
    "(hands with more than one person:1.5), (overlapping hands:1.4), "
    "(disconnected hands:1.4), (floating hands:1.4), "
    "(abnormal hand structure:1.4), (hand mutation:1.5)"
)

# 标准自拍专用：防止生成双手拿手机等不自然姿态
ANTI_DUAL_PHONE_PROMPT = (
    "(two phones:1.5), (camera in both hands:1.5), "
    "(holding phone with both hands:1.6), "
    "(both hands holding phone:1.6), "
    "(phone in frame:1.4), (visible phone in hand:1.4), "
    "(both hands visible:1.6), (two hands in frame:1.6), "
    "(both arms visible:1.5), (two arms extended:1.5), "
    "(hands together:1.5), (hands touching each other:1.5), "
    "(two-hand gesture:1.5)"
)

# 第三人称照片专用：明确主体不是在自拍，也不应手持拍摄设备
PHOTO_NO_PHONE_PROMPT = (
    "(phone:1.5), (smartphone:1.5), (cellphone:1.5), (mobile phone:1.5), "
    "(visible phone:1.5), (phone in hand:1.6), (holding phone:1.6), "
    "(camera in hand:1.5), (selfie:1.6), (selfie stick:1.6), (taking selfie:1.6)"
)

# 向后兼容别名
ANTI_DUAL_HANDS_PROMPT = f"{SELFIE_HAND_NEGATIVE}, {ANTI_DUAL_PHONE_PROMPT}"
