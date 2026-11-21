"""配置 —— **全部**走环境变量，一个都不硬编码。

《工程文档.md》§4 铁律：AK/SK 只能从环境变量读，绝不能进代码、绝不进 git。
即梦接入文档 §1 同款要求。

─────────────────────────────────────────────────────────────
【这个文件为什么值得写这么长】

因为它是**密钥防线**。后端唯一可能泄漏 AK/SK 的地方就是这里 ——
只要这里做对了，代码里任何一处都不可能「顺手写死一个密钥」。

防线由三件事组成：

1. **密钥字段没有默认值**。`JWT_SECRET` 缺了就启动失败。
   反例：写成 `JWT_SECRET: str = "dev-secret"` —— 那样本地跑得通、
   部署时忘了配环境变量也照样跑得通，然后用 `dev-secret` 签发了真实用户的
   token，而且**没有任何报错**。这类事故不会在开发期被发现。

2. **默认值是「离线能跑」的那一套**（`PROVIDER=fake` / `STORAGE=local`），
   而不是「连着生产资源」。这样 B0–B6 全程不花一分钱、不发一个外网请求，
   而想连真即梦时必须**显式**改配置 —— 误连生产需要人主动做一件事。

3. **计价与配额这些数字有默认值，且与前端逐字一致**。
   它们不是密钥，是契约值（§7）。放在这里是为了让「前端写死 4 积分/张」
   这件事在后端有一个可对照的出处。
─────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 后端仓库根目录（本文件在 app/ 下）。用于把相对路径解析成绝对路径。
BASE_DIR = Path(__file__).resolve().parent.parent

# JWT 密钥的长度下限。
#
# 【为什么是模块级常量，而不是 Settings 里的类属性】
# 写在 `Settings` 里的话，pydantic 会把它当成一个**字段**，然后报
# `A non-annotated attribute was detected` —— 要么给它加 `ClassVar[int]`
# 注解，要么挪出来。挪出来更省事，而且这个数字本来也不该是「配置」：
# 它是个安全下限，不是能靠环境变量调的旋钮。
#
# 32 是按 `secrets.token_urlsafe(32)` 的量级定的（约 256 位熵），
# 也就是 `generate_dev_secret()` 的产出的长度。
MIN_JWT_SECRET_LEN = 32


class ProviderKind(StrEnum):
    """AI 能力提供方。

    【为什么是 `fake` 而不是「没有 provider」】见 §12.2 的两个 Protocol：
    假实现**不是临时脚手架，是永久测试夹具**。前端的 136 条契约测试里，
    冻结 32 / 结算 24 / 退回 8 这三个数字是写死的 —— 假 provider 复现不出
    这三个数，契约门禁就过不了。所以它必须和真实现一样是一等公民。
    """

    fake = "fake"
    jimeng = "jimeng"
    minimax = "minimax"
        # 【只有视频，没有图片】MiniMax 在这条链路上**只替代图生视频**
        # （即梦那边那个产品的并发配额是 0，图生视频一步都没成过，
        # 见 HANDOFF §2.6 第四件事）。它的文生图是**另一套接口**
        # （`POST /v1/image_generation`，v1 而非 v2，响应形状也不同），
        # 而即梦那条文生图**已经被真外部验过**（作品页看得见那张图）。
        # 所以拿它当 `provider`（图片那个）会在 `model_post_init` 里被拒。
        #
        # 【为什么不是「一个 provider 包住两个」】见 `providers/__init__.py`
        # `build_provider` 的说明 —— 关键在于 `poll()` 拿不到 kind。


class StorageKind(StrEnum):
    """对象存储。

    `local` 把文件写到本地目录并通过 `PUBLIC_BASE_URL` 暴露 ——
    【为什么 v1 就够用】因为它的对外行为（返回一个永久可读的 URL）
    和 OSS 完全一样，而 `Storage` 是个 Protocol，换实现不动调用方。
    """

    local = "local"
    oss = "oss"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        # 【为什么不许有多余的环境变量就报错】机器上有一堆无关的环境变量
        # （PATH、JAVA_HOME……），`extra="forbid"` 会让服务起不来。
        extra="ignore",
        case_sensitive=False,
        # 【这一行是必需的，不是保险】pydantic v2 **默认不校验默认值**：
        # 环境变量没提供时，字段直接用默认值、连校验器都不跑。
        # 而 `database_url` 的默认值恰恰要靠校验器翻译（见 `_default_sqlite`）——
        # 不开这个开关的话，没配 DATABASE_URL 时会拿到一个空串，
        # 然后在建引擎时炸成一句看不懂的 SQLAlchemy 错误。
        validate_default=True,
        # ── 空值当作「没写」──────────────────────────────────
        # 【为什么这一行是安全相关的，不只是方便】
        #
        # 环境变量是字符串，于是 `X=` 和「没写 X」在 pydantic 眼里是
        # **两件不同的事**：前者提供了一个空串。这在本项目里造成两个后果，
        # 一个是吵人的，一个是危险：
        #
        # · 吵人的：`.env` 里留一个 `TEST_MODE=` 会让 app **起不来**，
        #   报的是 `Input should be a valid boolean, unable to interpret
        #   input`，和你真正想做的事毫无关系。
        #
        # · 危险的：`JWT_SECRET=` 留空时，`str` 类型**会接受这个空串** ——
        #   于是服务带着一把**空密钥**正常启动，所有 token 谁都能伪造。
        #   而「密钥必填」本来是这套配置最要紧的一条防线，
        #   它却在最容易被触发的写法（留空）上失效了。
        #
        # 打开这个开关后，空值一律按「没提供」处理：布尔退回默认值，
        # 必填项则直接报「字段缺失」—— 正是我们想要的。
        env_ignore_empty=True,
    )

    # ─── 运行环境 ───────────────────────────────────────────
    app_env: str = "dev"
        # dev / prod。目前只用来决定错误响应里要不要带堆栈。

    test_mode: bool = False
        # 【硬门禁】只有它为真时，`/__test/*`（重置、发积分）才会挂载。
        # 见 §15.1 的验收自动化 —— 那些接口能凭空造钱，绝不能在线上可达。

    # ─── 安全（**没有默认值，缺了就起不来**）───────────────
    jwt_secret: str = Field(
        ...,
        description="JWT 签名密钥。必填，无默认值 —— 见本文件顶部的说明。",
    )
    jwt_expire_minutes: int = 60 * 24 * 7
        # 7 天。§6.1 无 refresh token，过期即 401 → 前端登出。
        # 【为什么给一周】v1 是内测，用户量小；太短会被投诉「老是要重登」。
        # 要改的话改这里，不要改 `deps.py`。

    bcrypt_rounds: int = 12
        # 密码哈希强度。12 是 2024 年前后的常用值（约 250ms/次）。
        # 【为什么写进配置】测试里要能调到最低（4），否则 136 条前端契约测试
        # 里凡是要注册的用例，每条都多付 250ms。

    # ─── 即梦（AK/SK）—— 只有 PROVIDER=jimeng 时才必需 ─────
    jimeng_ak: str = ""
    jimeng_sk: str = ""
        # 【为什么这两个可以有默认空值，JWT_SECRET 却不行】
        # 因为 PROVIDER 默认是 fake，这时它们用不着。
        # 但**真的要用即梦时会强制校验**（见 `model_post_init`）——
        # 「配置成 jimeng 却没给密钥」必须在启动那一刻就炸，
        # 不能等到某个用户点了生成才发现。
    jimeng_region: str = "cn-north-1"
    jimeng_service: str = "cv"
        # 即梦接入文档 §2：签名 V4 要用它算 credential scope。
    jimeng_host: str = "visual.volcengineapi.com"
    jimeng_req_key_image: str = ""
    jimeng_req_key_video: str = ""
        # 【B6】能力路由键（`req_key`）。即梦的**同一个接口**用不同的
        # `req_key` 提供不同的能力，而它决定了「这次调用花多少钱」——
        # 所以它同时是计费的依据和审计里最有用的那一列。
        #
        # ⚠️ **这两个值是猜测，必须在控制台确认（§18-2）。** 官方文档
        #    没有公开一张 req_key 对照表，`pippit_iv2v_v20_cvtob_with_vinput`
        #    只是社区里流传的一个候选。填错的表现是接口回一个
        #    「不支持的 req_key」的错误码，**不会是别的东西** ——
        #    那正是我们要的失败形态：响亮、好认、且不花钱。
        #
        # 【为什么放在配置里，而不是代码里】因为它可能因**子账号开通的
        # 能力**而不同（同一个平台，A 账号能用的能力 B 账号未必有）。
        # 硬编码的话，换一个子账号就要改代码、重新发版。
        #
        # 【为什么默认空串，而不是给个候选当默认值】空串会在启动时
        # 被 `model_post_init` 拦下；给一个「大概对」的默认值，则会
        # 让一个没配的部署**跑起来**，然后在第一次生成时花掉一次真调用
        # 换来一个看不懂的错误。

    # ─── MiniMax（图生视频）—— 只有解析出来的视频 provider 是它时才必需 ──
    minimax_api_key: str = ""
        # 【铁律同 AK/SK】只从环境变量读、绝不写进 `.py`、绝不进 git。
        # 它比即梦那对还好一点：MiniMax 走 `Authorization: Bearer`，
        # **不签名**，所以没有「AK 进 HTTP 头、头被记进库」那条泄漏路径。
        # 但 `ProviderCallMeta` 仍然一个头都不记（见 `base.py`）——
        # 那条纪律是对的，不该因为这次不用签名就放宽。
    minimax_api_host: str = "api.minimax.cn"
    minimax_video_model: str = "MiniMax-H3-Max"
        # 文档里可用值只有 `MiniMax-H3` 与 `MiniMax-H3-Max` 两个。
        # 放在配置里而不是写死，是因为**它们的能力档位不同**：
        # H3 有 768P/2K、4~15 秒；H3-Max 只有 480P/768P、5~15 秒（不支持 4 秒）。
        # 换模型时若分辨率/时长跟着越界，接口会回 400 —— 所以那两个值也在下面。
    minimax_video_resolution: str = "768P"
        # H3-Max 可用 `480P` / `768P`。**写死 768P 是因为契约里根本没有
        # 分辨率字段**（前端「720P」是纯展示，`VideoGenIn` 里没有它，
        # 即梦那条 `_submit_body` 也从没发过分辨率）—— 见 HANDOFF §5 第 8 条。
        # 所以这是「后端替契约定的一档」，不是从请求里读来的。

    # ─── 对象存储（S3 协议，B6）—— 只有 STORAGE=oss 时才必需 ──
    s3_endpoint_url: str = ""
        # 桶的 endpoint。填 `https://oss-cn-hangzhou.aliyuncs.com`
        # （阿里云 OSS）、`https://cos.ap-guangzhou.myqcloud.com`（腾讯 COS）、
        # 或者 MinIO 的地址 —— **这一个字段就是「S3 协议」的全部好处**。
        # 留空则用 boto3 的默认解析（AWS 本家）。
    s3_bucket: str = ""
    s3_region: str = ""
        # 有的服务商要（OSS 需要 `cn-hangzhou` 这类），有的不要。
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_session_token: str = ""
        # 【铁律同 AK/SK】只从环境变量读，绝不写进 `.py`、绝不进 git，
        # 开发与生产用**不同**的子账号密钥。见 `.env.example`。
    s3_public_base_url: str = ""
        # 【B6】产物的**永久**公网前缀，例如 `https://cdn.example.com`
        # 或 `https://my-bucket.oss-cn-hangzhou.aliyuncs.com`。
        #
        # 【为什么必须单独配，而不是从 endpoint + bucket 拼】因为
        # OSS/COS 常把桶挂在一个 CDN 域名后面，而 CDN 域名的形状
        # 与服务商的默认域名不同。拼出来的话，「换 CDN」会变成
        # 「改代码」。
        #
        # ⚠️ 留空时退化成 `{endpoint}/{bucket}`。**那条路不可靠**
        #    （它假设了桶是公共读、且 endpoint 就是读地址），
        #    生产上请显式填它。
    s3_force_path_style: bool = False
        # 路径风格（`{endpoint}/{bucket}/{key}`）还是虚拟主机风格
        # （`{bucket}.{endpoint}/{key}`）。**OSS / COS / MinIO 通常要路径风格**，
        # AWS 本家要虚拟主机风格。默认 False 是照 boto3 的约定。

    # ─── 通用开关 ──────────────────────────────────────────
    provider: ProviderKind = ProviderKind.fake
        # 【现在它是「图片 provider」】语义变了，但**默认值没变**
        # （仍是离线的 fake），所以现存部署不用改任何东西。
        # 谁按 kind 取谁，全在 `providers.build_provider(kind)` 一处。
    video_provider: ProviderKind | None = None
        # 【协议视频那一路走谁】`None` = **跟随 `provider`**（现存行为，
        # 也是「只跑 fake」和「只跑即梦」两种部署需要的）。
        #
        # 设成 `minimax` 就把图生视频整条挪到 MiniMax H3-Max 上，
        # 而文生图留在 `provider` 那一个 —— 这正是这一批的目的。
        #
        # 【为什么是 `None` 而不是直接默认 `ProviderKind.fake`】
        # 因为「没说过」和「就是要 fake」是两件事：前者要在 `provider`
        # 改值时跟着走，后者不会。写成默认 fake 的话，一个把
        # `PROVIDER=jimeng` 配上来的部署会发现自己的视频悄悄跑在假实现上。
    storage: StorageKind = StorageKind.local

    # ─── 影子链（方案 B：链下积分 1:1 映射到链上 VCR）──────────
    # 默认关闭；开了之后 worker 会把 grant/settle 等流水逐条上链。
    chain_enabled: bool = False
    chain_rpc_url: str = "http://127.0.0.1:8545"
    chain_platform_private_key: str = ""
    chain_id: int = Field(default=1337, gt=0)
    chain_sync_paused: bool = False
    chain_contract_address: str = ""
    chain_artifact_path: str = str(BASE_DIR / "app" / "chain" / "VideoCredit.json")

    fabric_enabled: bool = False
    fabric_bridge_url: str = "http://127.0.0.1:8801"
    fabric_bridge_token: str = ""
    fabric_network_id: str = Field(default="local-fabric", min_length=1, max_length=64)
    fabric_channel: str = Field(default="videochannel", min_length=1, max_length=64)
    fabric_chaincode: str = Field(default="video-evidence", min_length=1, max_length=64)

    # ─── 计价（§7.1）—— **契约值，改它必须前后端一起改** ────
    credits_per_image: int = 4
        # 文生图固定 4 积分（= ¥0.40，成本 ¥0.20，毛利 50%）
    credits_per_sec_720: int = 4
        # 720P 视频 4 积分/秒。换算直觉：4 积分 = 1 张图 = 1 秒 720P。
    credits_per_sec_1080: int = 9
        # 【v1 用不到】§7.1 定了价，但 §14.1 说 v1 只上 720P，
        # 而且**契约上根本没有清晰度字段**（HANDOFF §5 第 8 条）——
        # 所以 1080P 在构造上就不可达。留着是为了 §7.1 的定价表完整，
        # 不是为了哪天顺手打开它：打开它要先补契约。
    duration_slack_sec: int = 3
        # §7.2 的「请求时长 + 3 秒余量」。冻结 = (输入时长 + 请求时长 + 余量) × 单价。
        # 【这是占位值】真值由 B0.5 的即梦 Spike 实测修正（§18-2）。
        # 现在与前端 `_durationSlackSec` 逐字一致 —— 不一致会导致
        # 前端显示「冻结 32」而后端冻 40，用户看到对不上的账。

    signup_grant: int = 50
        # §12.1：新用户注册赠送。**契约值**（原为 20，F8 上调，理由见
        # `flutter_application_1/HANDOFF.md` §3.1）。
        # 【为什么它不是「随便一个奖励数」】因为视频要按「请求时长 + 3 秒余量」
        # 冻结，5 秒的要冻 32 —— 赠送额低于 32 的话，新用户第一次做视频
        # 必然撞墙，而 v1 没有充值入口（§7.6）。

    # ─── 配额（§7.5 / §8.2）────────────────────────────────
    daily_task_limit: int = 20
        # 每个用户每天的任务数上限（图片与视频**分开**计数，
        # 否则用户排个十分钟的视频之后连图都生成不了 —— 图片会被视频饿死）
    max_concurrent_tasks: int = 1
        # 每个用户同时进行的任务数上限（同类）。§8.2：扩容 ¥500/日/并发，
        # 所以这个数字直接等于钱。要调先算账。
    provider_qps: float = 1.0
        # 即梦的 QPS 限制（对应审计码 50429）。worker 出队速率不能超过它，
        # 否则会拿到一串限流错误，看起来像 provider 挂了。

    # ─── 输入上限（§11.2）—— 与前端逐字一致 ────────────────
    max_prompt_len: int = 2000
        # 前端 `ApiErrorCode.invalidPrompt.defaultMessage` 里写的就是 2000。
    max_image_bytes: int = 20 * 1024 * 1024
        # 20MB。前端 `_maxImageBytes` 同款。

    # ─── 队列与 worker（§8）────────────────────────────────
    worker_enabled: bool = True
    """是否在本进程里跑后台 worker 线程（§8.3 的单进程轮询循环）。

    【为什么要有一个开关，而不是「永远跑」】两个实在的用途：
    · **验收自动化**（`TEST_MODE=1`）下它会被强制关掉 —— 见 `main.py`
      的说明，后台 tick 和 `POST /__test/reset` 的 `drop_all` 抢库。
    · 手工调试时想「只跑 API 不跑 worker」，或者想单独起一个
      worker 进程，都需要能把它关掉。
    """

    provider_max_concurrency: int = 1
    """**出队闸门**：同时交给 provider 的任务数上限，**全局、按类分开计**。

    ─────────────────────────────────────────────────────
    【⚠️ 它和 `max_concurrent_tasks` 不是一个东西，别合并】

    · `max_concurrent_tasks`（上面）= §7.5 的**每用户**入口闸：
      「这一个人同时能开几个任务」。它是**成本自保**，
      防的是单个用户把额度堆满。
    · `provider_max_concurrency`（这里）= §8.2 的**闸门值**：
      「整个平台同时能压几个任务给即梦」。它是**物理约束** ——
      §8.1：即梦默认并发 1–2 且平台共享，与用户数无关，
      扩容 ¥500/日/并发。

    两者默认都是 1，所以看起来像同一个数。但它们会**朝不同方向
    漂**：内测期用户变多时该动的不是这里，而是上面那个；
    provider 扩容时该动的只有这里。合并成一个数的话，
    「给单个用户放宽一点」会顺手把整条 provider 通道打爆，
    而账单要到月底才看得出来。
    ─────────────────────────────────────────────────────
    """

    worker_retry_backoff_sec: float = 2.0
    """重试退避的基数（秒）。§7.5：**指数退避且设上限**。

    第 n 次重试等 `base × 2^(n-1)` 秒，上限 `worker_retry_max_backoff_sec`。
    【为什么退避是「把 queued_at 推到未来」而不是 sleep】因为
    sleep 会把整个 worker 卡住 —— 别人的任务也跟着等。
    推到未来则只是这个任务自己晚一点再被捞起来，见
    `services/queue.py` 的 `claim_next`。
    """

    worker_retry_max_backoff_sec: float = 30.0
    """退避上限。防的是「重试次数被调大之后，第 10 次重试要等 17 分钟」。"""

    worker_poll_interval_sec: float = 2.0
        # worker 多久巡一次「有没有该出队的任务」。
        # 【为什么不是事件驱动】§4.1 明确 v1 不引入 Redis/Celery，
        # DB 队列 + 轮询就是定稿方案。2 秒是体验（用户等得少）与
        # 空转（每秒查一次库）之间的折中。
    provider_poll_interval_sec: float = 10.0
        # 已提交的任务多久问一次即梦。
        # 【为什么比出队间隔大得多】即梦一条视频要跑 10 分钟（§15.1 的
        # 「10 分钟等待是否可接受」），10 秒问一次已经很密了。
    task_timeout_sec: int = 60 * 60
        # 超过 1 小时还没终态 → 判 `expired`（§11.3 的 8 个状态之一），
        # 冻结额全额退回。防的是「provider 永远不给结果」把用户的积分
        # 无限期锁死。

    provider_max_retries: int = 3
        # 可重试类错误（50429 限流 / 5xx）的退避重试上限。
        # 【审核类错误不在其内】50411/50413/50511/50514 这类重试一万次
        # 也是同样结果，重试只是白花钱（§10 / B6）。

    # ─── 存储与对外地址 ────────────────────────────────────
    media_root: Path = BASE_DIR / "media"
        # STORAGE=local 时的落地目录（已被 .gitignore 忽略）
    public_base_url: str = "http://127.0.0.1:8000"
        # 拼接产物的公网地址。**必须是外部可达的地址** ——
        # 写成 localhost 的话，App 拿到的 URL 指向它自己，图全是裂的。
    max_upload_side: int = 4096
        # 缩略图/参考图的最长边。§9.4 的「≤4096×4096」，在 B4 落成
        # **上传时的校验**（超出即 `IMAGE_TOO_LARGE`）。
        #
        # ⚠️ 它只对**能读出声明的边长**的文件生效：解不出的文件照收
        # （用户拍板的宽松口径，见 `services/assets.py` 的说明）。
        # 所以这一条对「一个改了扩展名的 21MB 压缩包」等于不执行 ——
        # 那是口径的代价，不是漏了。

    provider_spool_root: Path = BASE_DIR / ".provider_spool"
    """**provider 产物的暂存区**（B4）。fake 把真字节做在这里，
    并把 `file://` 地址当作 `provider_url` 返回。

    ─────────────────────────────────────────────────────────
    【为什么这块地必须有自己的根，而且要能被配置】

    因为转存层要回答一个问题：「这个 `provider_url` 是谁给的？」
    真 provider 给的是 **https 外网地址**，fake 给的是**本地文件**。
    如果允许 `file://` 指向任意路径，那么一个被污染的
    `provider_url`（将来真 provider 的回参进了库）就变成一次
    **任意文件读取** —— 后端会把 `C:/Windows/...` 复制进
    `media_root` 并公开发布出去。

    所以 `file://` 只允许读 `provider_spool_root` **之内**的东西
    （包含性检查见 `services/transfer.py`，是 `resolve()` 之后
    按路径比，不是字符串前缀 —— 字符串前缀是能绕过的）。
    这个目录是**我们自己**的东西，不是用户能写的地方。

    默认值不进 git（见 `.gitignore`），测试里必须钉到 `tmp_path`
    （见 `tests/conftest.py`）—— 否则一次 pytest 会在仓库里
    留下一堆产物，还会让两次运行互相影响。
    ─────────────────────────────────────────────────────────
    """

    max_artifact_bytes: int = 200 * 1024 * 1024
    """单个产物的转存上限（200MB）。§9.3 的成本自保。

    【为什么它和 `max_image_bytes` 是两个数】那个管**用户上传**
    （§9.4 明文规定 20MB），这个管 **provider 给我们的成品** ——
    一段 720P 视频本来就比一张参考图大得多。用一个数的话，
    要么把视频卡死，要么把上传的口子开到 200MB。
    """

    ffmpeg_timeout_sec: float = 30.0
    """单次 ffmpeg / ffprobe 调用的超时。

    【为什么必须有超时】它们处理的是**不可信字节**（provider 回来的
    文件）。畸形容器让解码器陷入长循环是已知的一类问题，
    而没有超时的话，卡住的是 worker 线程 —— 整个平台的队列一起停。
    """

    # ─── 转存重试（§9.3 / §3.6）────────────────────────────
    transfer_max_retries: int = 3
    """转存失败的重试上限。耗尽 → 任务 `failed` + `TRANSFER_FAILED` + 全额退回。

    【为什么要重试】转存是一次跨网络的搬运（B6 之后是 OSS），
    失败大多是瞬时的（超时、5xx）。§9.3 明确要求重试而不是直接失败。
    """

    transfer_retry_backoff_sec: float = 2.0
    """两次转存重试之间的最小间隔。

    【为什么需要退避，而不是「下一轮就再试」】因为 worker 一轮是
    2 秒，而重试预算是 3 次 —— 没有退避的话，一个坏掉的地址会在
    **6 秒内**烧完全部预算然后判死，一次抖动都不给它扛过去的机会。
    退避把「3 次重试」摊开成一段真正的时间。
    """

    # ─── 合规：审核与隐式标识（B5 / §10）──────────────────
    moderation_enabled: bool = True
    """入口审核（§10.2 第①层）的总开关。**默认开。**

    【为什么默认是开的】§10.1 把「生成前的输入审核」和「标识」并列成
    必做项。默认关掉的话，一个忘了配的部署就是**不审核**的 ——
    而它在外表上与正常部署完全一样（`/health` 正常、测试全绿）。
    要关必须显式写一行环境变量，那行字在 `git diff` 里看得见。
    """

    moderation_extra_keywords: str = ""
    """额外违规词，**英文逗号分隔**。运营加词走这里，不用改代码。

    ⚠️ **只放 ASCII。** 中文放这里要经过环境变量 / `.env` 的编码往返，
    而本机的区域编码是 GBK —— 一个中文词在途中被转成 GBK 字节之后
    就不再等于代码里的那个词，表现是「词明明配了却拦不住」。
    内置的那份词表在 `services/moderation.py` 里（Python 源码，UTF-8）。
    """

    marking_enabled: bool = True
    """给 AI 产物写**隐式标识**（§10.1 的文件元数据）。**默认开。**

    【为什么它默认开、且默认值有测试钉着】这是《人工智能生成合成内容
    标识办法》规定的法律义务，不是可选项。关掉它只有一种正当理由：
    这台环境上的元数据写入工具坏了，先让交付继续 ——
    见 `services/transfer.py` 里那段「合规优先」的说明。
    """

    marking_creator: str = "AI Video Platform"
    """写进标识里的「生成工具」名。**ASCII** —— 它要进 EXIF / XMP / MP4
    三种容器，而这三者的字符集约定各不相同，ASCII 是唯一在三种里都
    确定的写法。"""

    provider_call_audit_enabled: bool = True
    """`provider_calls` 对账（§11.1）。**默认开。**

    这张表 B1 就建好了，却一直没被写过一行 —— 于是「provider 到底被
    调了几次、每次说了什么」在库里没有痕迹。B5 把它接上。
    关掉它只用于「审计子系统本身在出问题，而我需要生成先跑起来」。
    """

    # ─── 数据库 ────────────────────────────────────────────
    database_url: str = ""
        # 【为什么默认 SQLite】§4.1 定的路径是 SQLite → PostgreSQL，
        # 先跑起来最重要。但**并发相关的写法从一开始就按 PostgreSQL 写**
        # （见 database.py 里关于 WAL 与 immediate 事务的说明）——
        # 等到迁移时才发现「原来靠的是 SQLite 的串行化」就晚了。
        #
        # 【为什么默认值是空串而不是那个 sqlite 地址】
        # 因为空串要交给下面的校验器翻译 —— 见 `_default_sqlite`。

    # ─── 派生量 ────────────────────────────────────────────
    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_must_be_strong(cls, v: str) -> str:
        """密钥不能是空的、纯空白的、或者短得能被暴力枚举。

        ─────────────────────────────────────────────────────
        【为什么「必填」还不够，这才是真正的防线】

        `jwt_secret: str = Field(...)` 只保证**字段被提供了**，
        它不保证提供的东西**有用**。实测过的两种失效写法：

            JWT_SECRET=          → 空串，`str` 类型完全接受
            JWT_SECRET="   "     → 纯空格，同样接受

        两种都会让服务**带着一把空/易猜的密钥正常启动**：日志正常、
        `/health` 正常、测试全绿，而任何人都能伪造登录态。
        「没有默认值」这条防线，恰恰在最容易写出来的形式上漏了。

        （空串还有一道 `env_ignore_empty=True` 挡着，它把空值当成
        「没提供」；但那管不到纯空格，也管不到 `JWT_SECRET=abc`。）

        32 字符的下限是按 `secrets.token_urlsafe(32)` 的产出来定的
        —— 也就是 `generate_dev_secret()` 给的那种量级，约 256 位熵。
        一个手打的短密钥在这里就红，比等到被爆破强。
        ─────────────────────────────────────────────────────
        """
        if len(v.strip()) < MIN_JWT_SECRET_LEN:
            raise ValueError(
                f"JWT_SECRET 太短（{len(v.strip())} 字符，至少 {MIN_JWT_SECRET_LEN}）。"
                "生成一个：python -c \"from app.config import generate_dev_secret as g; print(g())\""
            )
        return v

    @field_validator("public_base_url")
    @classmethod
    def _no_trailing_slash(cls, v: str) -> str:
        # 【为什么要管这个】拼 URL 时 `f"{base}/uploads/{name}"` 和
        # `f"{base}uploads/{name}"` 只差一个斜杠，而结果一个是 200 一个是 404。
        # 在入口处统一掉，比在每个拼接点写 `.rstrip('/')` 可靠。
        return v.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def _default_sqlite(cls, v: str) -> str:
        """空值 → 仓库根目录的 SQLite 文件。

        ─────────────────────────────────────────────────────
        【为什么必须有这个校验器：一个空环境变量就是一个陷阱】

        `.env.example` 里如果写着 `DATABASE_URL=`（为了让人知道有这么一项），
        那么 `.env` 里它也是空的。而 pydantic-settings 会把空串**当成一个
        有效的值**读进来，于是 `database_url == ""` —— 建引擎时才会炸，
        报的是一句和「你少配了一个环境变量」毫无关系的 SQLAlchemy 错误。

        这类「空串和没写不是一回事」的坑在配置里到处都是，挡在入口最省事。
        顺带一提，`.env.example` 里那一行仍然是注释掉的：两处都做，
        是因为**代码挡得住错误，文档教人怎么用对**。
        ─────────────────────────────────────────────────────
        """
        if v.strip():
            return v
        return f"sqlite:///{(BASE_DIR / 'aivideo.db').as_posix()}"

    @field_validator("media_root", "provider_spool_root", mode="before")
    @classmethod
    def _abs_media_root(cls, v: object) -> object:
        """相对路径 → 相对**仓库根**的绝对路径。

        【为什么两个目录共用一个校验器】它们的要求逐字相同（都可以被
        环境变量覆盖、都要能过测试的 `tmp_path`），而分成两个的话，
        将来给其中一个补规则时另一个必然被忘掉 —— 那时错误的表现是
        「`MEDIA_ROOT` 认相对路径，`PROVIDER_SPOOL_ROOT` 不认」。
        """
        if isinstance(v, str):
            p = Path(v)
            return p if p.is_absolute() else BASE_DIR / p
        return v

    @property
    def image_provider(self) -> ProviderKind:
        """文生图走谁。**就是 `provider`** —— 留着这个名字，是为了让
        `model_post_init` 里那两组守卫读起来能一眼看出「判的是哪一路」。"""
        return self.provider

    @property
    def resolved_video_provider(self) -> ProviderKind:
        """图生视频走谁。`video_provider` 为 `None` 时跟随 `provider`。

        【为什么这必须是**一个属性**而不是各处写 `x or y`】
        因为守卫要判的和 `build_provider` 要用的必须是**同一个值**。
        写成两处的话，「启动时判的是即梦、运行时用的是 minimax」这种
        错位不会报任何错 —— 直到某个用户点了生成。
        """
        return self.video_provider or self.provider

    def model_post_init(self, _context: object) -> None:
        """跨字段校验：选了真 provider 就必须有真密钥。

        【为什么放在这里而不是在校验器里】因为这是**两个字段之间**的约束，
        单字段校验器看不到对方。而它必须存在的原因是前面说的那条：
        「配置成 jimeng 却没给 AK/SK」要在**启动那一刻**炸，
        不能等到用户点了生成才炸 —— 那时候错误会以一个看不懂的
        签名失败的形式出现，排查成本高得多。

        【B7.x 起它判的是「解析出来的两个 provider」】图片那一路就是
        `provider`，视频那一路是 `resolved_video_provider`。每条守卫各判
        一次 —— 于是 `PROVIDER=fake` + `VIDEO_PROVIDER=jimeng` 这种新组合
        也被拦得住（它没有 AK/SK，却真的会去打即梦）。

        同理，`req_key` 那条也变成**每路只要求自己那一个**：一个
        「图片即梦、视频 MiniMax」的部署不该被要求填
        `JIMENG_REQ_KEY_VIDEO` —— 那是一个用不上的键。要求它只会
        让正确的配置起不来，而人看到的消息会把病因指向一个无辜的字段。
        """
        image_kind = self.image_provider
        video_kind = self.resolved_video_provider

        # 【B7.x：判据从「一个 provider」变成「两路各自」】
        #
        # 每一路各判自己那一个 `req_key`，**不是「哪一路用即梦就要两个」**。
        # 判据写错的话，本批的推荐配置（`PROVIDER=jimeng` +
        # `VIDEO_PROVIDER=minimax`）会因为缺 `JIMENG_REQ_KEY_VIDEO`
        # 而起不来 —— 而视频那一路根本不用那个键，那是一个
        # 「要求用户配一个用不上的东西」的假失败。
        routes = (
            (image_kind, "图片", "JIMENG_REQ_KEY_IMAGE", self.jimeng_req_key_image),
            (video_kind, "视频", "JIMENG_REQ_KEY_VIDEO", self.jimeng_req_key_video),
        )
        for kind, route, req_key_name, req_key in routes:
            if kind is not ProviderKind.jimeng:
                continue
            # 【为什么对两路各判一次，而不是判一次就够】它们可以不同
            # （`PROVIDER=jimeng` + `VIDEO_PROVIDER=minimax` 正是本批的配置）。
            # 判一次的话，只有视频那一路用即梦的部署会**正常启动**，
            # 然后在第一次出片时炸在签名上。
            if not (self.jimeng_ak and self.jimeng_sk):
                raise ValueError(
                    f"{route}这一路配的是 jimeng，必须提供 JIMENG_AK 与 JIMENG_SK。"
                    "密钥只从环境变量读（《工程文档.md》§4 铁律），"
                    "不要写进代码或 .env 提交到仓库。"
                )
            if not req_key:
                # 【B6 加的第三条守卫】缺 req_key 时，前面那条 AK/SK 守卫
                # 挡不住 —— 一个配了密钥却没配 req_key 的部署会**正常启动**，
                # 然后在第一次生成时花掉一次真调用换回一句
                # 「不支持的 req_key」。那笔钱不多，但它是**在能事前拦住的
                # 情况下花掉的**，而事后要从日志里认出这件事得先知道有这个坑。
                raise ValueError(
                    f"{route}这一路配的是 jimeng，必须提供 {req_key_name}"
                    "（能力的路由键，见 §18-2：这个值要在控制台确认，"
                    "不是从文档里抄的）。"
                )

        # ── MiniMax ─────────────────────────────────────────
        if image_kind is ProviderKind.minimax:
            # 【为什么这是一条硬拒，而不是「回退到别的 provider」】
            # 因为 MiniMax 在本仓库**只有视频**（见 `ProviderKind.minimax`
            # 上面那段）。静默回退的话，一个以为「全平台换 MiniMax」的部署
            # 会看到文生图照常出图 —— 只是出的是即梦的图，而成本表上
            # 两笔账从此分不开。响亮地拒绝，人一眼就知道该改哪一个值。
            raise ValueError(
                "PROVIDER=minimax 不行：MiniMax 在 v1 只接了图生视频，"
                "没有文生图（那要接另一套接口 /v1/image_generation）。"
                "请把 PROVIDER 留成 fake 或 jimeng，改设 VIDEO_PROVIDER=minimax。"
            )
        if video_kind is ProviderKind.minimax and not self.minimax_api_key:
            # 同款理由：配了真 provider 却没密钥的部署会正常启动，
            # 然后在第一次出片时花掉一次真调用换回一个 401。
            raise ValueError(
                "视频这一路配的是 minimax，必须提供 MINIMAX_API_KEY。"
                "密钥只从环境变量读，不要写进代码或 .env 提交到仓库。"
            )
        if self.storage is StorageKind.oss and not (self.s3_bucket and self.s3_access_key_id):
            # 同款理由：STORAGE=oss 却没给桶名/密钥的部署会正常启动，
            # 然后**所有**生成都在转存那一步失败 —— 而那时任务已经
            # 冻结了积分、provider 那边也已经花了钱。
            raise ValueError(
                "STORAGE=oss 时必须提供 S3_BUCKET 与 S3_ACCESS_KEY_ID "
                "（S3_SECRET_ACCESS_KEY 同理）。"
                "密钥只从环境变量读，绝不写进代码或 .env 提交到仓库。"
            )

    # ─── 便捷属性 ──────────────────────────────────────────
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def media_root_ready(self) -> Path:
        """确保媒体目录存在并返回它。

        【为什么是 `mkdir` 而不是启动时建一次】因为测试会换 `MEDIA_ROOT`，
        而换完之后第一次写文件才发现目录不存在，报的是一个 IO 错误 ——
        离真正的病因隔了两层。
        """
        self.media_root.mkdir(parents=True, exist_ok=True)
        return self.media_root

    @property
    def provider_spool_root_ready(self) -> Path:
        """确保 provider 暂存目录存在并返回它。理由同 `media_root_ready`。"""
        self.provider_spool_root.mkdir(parents=True, exist_ok=True)
        return self.provider_spool_root


@lru_cache
def get_settings() -> Settings:
    """取配置（进程内缓存）。

    【为什么要缓存】pydantic-settings 每次实例化都要读环境变量和 .env 文件，
    而 `get_settings()` 会被 DI（`deps.py`）在每个请求里调用。
    不缓存的话每个请求都多一次磁盘 IO。

    【为什么用 lru_cache 而不是全局变量】测试要能 `get_settings.cache_clear()`
    换个环境重来。全局变量做不到这点。
    """
    return Settings()


def generate_dev_secret() -> str:
    """生成一个够用的开发密钥。

    【为什么这个函数存在，而不是在 .env.example 里写一个固定的假密钥】
    因为固定的假密钥会被复制到生产。这个函数的存在是为了让
    「我要在本地跑起来」有一个**明确的一步**：

        python -c "from app.config import generate_dev_secret as g; print(g())"

    把它粘进 `.env`。这样每个人本地都是不同的密钥，而 `.env` 不进 git。
    """
    return secrets.token_urlsafe(48)
