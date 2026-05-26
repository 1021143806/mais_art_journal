"""子命令 handlers — import 触发 @subcommand 注册

dispatcher 通过 `from . import handlers` 加载此包，
此处 import 所有 handler 模块以确保装饰器在 dispatcher 初始化时已执行。
"""

from . import config_handlers  # noqa: F401
from . import selfie_handlers  # noqa: F401
from . import style_handlers  # noqa: F401
from . import toggle_handlers  # noqa: F401
