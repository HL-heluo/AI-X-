"""AI 视频创作平台 · 后端（v1）。

对应《工程文档.md》§4.2 的目录树。模块职责：

    config.py     环境变量（含 AK/SK，绝不硬编码）
    database.py   连接与会话
    models.py     表结构（§11）
    schemas.py    请求/响应形状（**前端契约的唯一出处**）
    deps.py       依赖注入（当前用户等）
    enums.py      任务状态与错误码（8 个状态的唯一定义处）
    routers/      HTTP 层：只做参数校验与形状组装
    services/     业务：记账、队列、存储、审核、worker
    providers/    外部 AI 能力（Protocol + 假实现 + 即梦实现）
"""

__version__ = "1.0.0"
