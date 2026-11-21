"""B0 依赖闸门 —— 「全都装得上，而且真的能用」。

运行：`.venv/Scripts/python.exe scripts/check_deps.py`

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么这个脚本存在，而不是 `pip install` 成功就完事】

`pip install` 成功只说明**包被下载并解压到了磁盘上**。它不说明：

  · C 扩展真的加载起来了。Pillow 在没有 `_imaging` 的情况下能以
    「纯 Python 垫片」的形式 import 成功，然后在**第一次打开图片时**炸。
  · 版本之间彼此兼容。bcrypt 4.x 和某些 passlib 版本组合会打印一行
    版本读取错误，然后照常工作 —— 或者在某些组合下不照常工作。
  · 关键路径真的能跑。`sqlalchemy` import 成功和「能对着一个 SQLite
    建表并查询」之间隔着方言、驱动、连接池三层。

前端的教训（《工程文档.md》§4.4）是同一件事：`pub.dev` 不通这件事
**必须在 C0 就发现**，不能等写到一半。B5 写到一半才发现 `bcrypt` 装不上，
要换的是**密码哈希方案**，不是换一个包 —— 那时已经有一片代码了。

所以：**先证明全都装得上、而且真的能用，再动第一行业务代码。**

【为什么每条都要做一次真动作而不是 `import`】
一个只做 `import` 的检查会在「包坏了」时显示绿灯。本项目的工作约定里
有一条：**守卫测试要故意改坏跑一遍，确认它真的会红**。这里同理 ——
下面每一项都是「让它干一件真活，看它交不交得出来」。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 允许从仓库根目录跑：`python scripts/check_deps.py` 时把根加进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK = "  [ok]  "
FAIL = "  [!!]  "

failures: list[str] = []
# 【为什么数出来而不是写死】`total = 14` 那种写法会在有人加/删一项检查后
# 继续打印「全过（14 项）」—— 一个会撒谎的计数和真的一样有说服力。
passed = 0


def check(name: str, why: str, run) -> None:  # noqa: ANN001
    """跑一项检查。`run()` 返回值会被打印；抛异常即失败。"""
    global passed
    try:
        detail = run()
    except Exception as exc:  # noqa: BLE001 - 这里就是要抓住一切
        failures.append(f"{name}: {type(exc).__name__}: {exc}")
        print(f"{FAIL}{name:<22} {why}")
        print(f"         └─ 失败：{type(exc).__name__}: {exc}")
        return
    passed += 1
    print(f"{OK}{name:<22} {why}")
    if detail:
        print(f"         └─ {detail}")


# 反证用的 JWT 密钥。**长度必须合格** —— 短了的话失败会来自
# 「密钥太短」，而不是我们要证的那件事，反证因为错的理由通过 = 没测。
PROBE_SECRET = "dep-gate-not-a-real-secret-just-for-local"


@contextlib.contextmanager
def _without_env(*names: str):
    """临时把这几项从 `os.environ` 里摘掉。

    ─────────────────────────────────────────────────────────
    【为什么闸门需要它 —— 一个真踩过的坑】

    下面有几条是**反证**：配置缺一块时，`Settings` 必须起不来。
    它们原本的写法是「构造 `Settings(provider="jimeng")`，看它抛不抛」，
    而这在 `.env` **还是空的**时候是对的 —— 那正是写这些代码的那天。

    后来 `HANDOFF` §2.6 那份真凭据清单被走完了，`.env` 里有了真的
    AK/SK 与桶名。于是这五条**同时变红**，而红的原因是：

        `Settings` 的取值顺序是「init 参数 > 环境变量 > `.env`」，
        只往 init 里塞 `provider="jimeng"`、把 `.env` 留着不动，
        于是 `jimeng_ak` **照样从 `.env` 读到了真值** ——
        「这个人忘了配 AK/SK」这件事根本模拟不出来。

    糟糕的是失败信息：「配了 jimeng 却没给密钥，居然构造成功了」——
    读起来像**密钥防线有洞**，而实际上防线好好的，洞在闸门自己身上。
    更糟的是时机：闸门唯一真正该跑的时刻，就是**配好凭据的机器上**。

    所以：反证必须**同时**做到两件事 —— `Settings(_env_file=None)`
    挡掉 `.env`，这个上下文管理器挡掉环境变量。少任何一个，
    反证都会在某种部署形态下静默失效。
    ─────────────────────────────────────────────────────────
    """
    saved = {n: os.environ.pop(n, None) for n in names}
    try:
        yield
    finally:
        for n, v in saved.items():
            if v is not None:
                os.environ[n] = v


def main() -> int:
    print()
    print("=" * 68)
    print("  B0 依赖闸门 —— 每一项都要交出一件真活")
    print("=" * 68)
    print(f"  Python: {sys.version.split()[0]}  ({sys.executable})")
    print()

    # ── Web 框架 ──────────────────────────────────────────
    def _fastapi() -> str:
        import fastapi

        app = fastapi.FastAPI()

        @app.get("/x")
        def _x() -> dict[str, int]:
            return {"n": 1}

        # 【为什么要真的建一次 app】`import fastapi` 成功不代表它的
        # 路由装饰器、依赖注入、pydantic 集成都是好的。
        routes = [r.path for r in app.routes]  # type: ignore[attr-defined]
        assert "/x" in routes, routes
        return f"fastapi {fastapi.__version__}，建了一个 app 并注册了路由"

    check("fastapi", "§4.1 定稿的 Web 框架", _fastapi)

    def _uvicorn() -> str:
        import uvicorn

        # 【为什么不真起一个服务器】那需要选端口、等就绪、再关掉，
        # 在 CI 里是 flaky 的来源。这里只确认它的 CLI 配置对象能建起来。
        cfg = uvicorn.Config("app.main:app", log_level="critical")
        assert cfg.port is not None
        return f"uvicorn {uvicorn.__version__}，能构造 Config（含 --reload 用的 watchfiles）"

    check("uvicorn", "ASGI 服务器 + --reload", _uvicorn)

    # ── 数据库 ────────────────────────────────────────────
    def _sqlalchemy() -> str:
        import sqlalchemy as sa
        from sqlalchemy import create_engine, text

        # 【为什么这两行要这么写】两条都是 sqlalchemy 2.x 的既定行为，
        # 且都会在**写 app/models.py 时**原样再撞一次，所以钉在这里：
        #
        # 1. `import sqlalchemy` **不会**自动把子模块 `sqlalchemy.orm`
        #    挂上去 —— 于是 `sa.orm.DeclarativeBase` 抛
        #    `AttributeError: module 'sqlalchemy' has no attribute 'orm'`。
        #
        # 2. 更要命的是注解解析：2.0 的 `Mapped[int]` 是**按模块级名字**
        #    去查的。写成 `orm.Mapped[int]` 会抛
        #    `ArgumentError: Could not interpret annotation orm.Mapped[int]`
        #    —— 报错说「检查它在模块级被正确导入」，字面意思就是必须
        #    `from sqlalchemy.orm import Mapped`，不能走属性访问。
        #
        # 所以 `app/models.py` 的抬头就照这个形状来。
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

        # 3. 名字光 import 进来还不够，**必须落在模块级**。
        #    SQLAlchemy 解析注解时去的是 `sys.modules[类的模块].__dict__`
        #    —— 也就是**模块的全局命名空间**，不是函数的局部作用域。
        #    下面那个 `_T` 类写在函数里，`Mapped` 若只存在于这个函数的
        #    局部变量里，SQLAlchemy 就找不到它，抛的还是那句
        #    「Check that it uses names that are correctly imported at
        #    the module level」—— 字面意思就是「给我放到模块级去」。
        #
        #    真实的 `app/models.py` 里表都是模块级定义的，所以那边天然
        #    不会撞。这里为了**照真实写法验一遍**，把名字放进本模块全局。
        globals().update(
            DeclarativeBase=DeclarativeBase, Mapped=Mapped, mapped_column=mapped_column
        )

        # 【为什么是内存库真查一次】这条能同时验到：方言加载、
        # DBAPI 驱动存在、连接池能建连接、SQL 能执行。
        engine = create_engine("sqlite://")
        with engine.connect() as conn:
            n = conn.execute(text("select 1")).scalar()
        assert n == 1, n

        # 再验一次 2.0 风格的声明式写法（§4.1 要求用 Mapped[] 而不是 Column()）
        class _Base(DeclarativeBase):
            pass

        class _T(_Base):
            __tablename__ = "t"
            id: Mapped[int] = mapped_column(primary_key=True)

        _Base.metadata.create_all(engine)
        return f"sqlalchemy {sa.__version__}，内存库查询 + 2.0 风格建表都通"

    check("sqlalchemy", "ORM（2.0 风格）", _sqlalchemy)

    def _alembic() -> str:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        ini = Path(__file__).resolve().parent.parent / "alembic.ini"

        # 【为什么先自己按 UTF-8 读一遍】这条检查踩过一次坑，值得留个记号。
        #
        # Alembic 内部用 configparser 读这个文件，而 configparser 在没指定
        # 编码时用的是**系统区域编码**。这台机器是中文 Windows，也就是
        # GBK —— 于是 alembic.ini 里只要出现一个中文注释，Alembic 会在
        # 读配置阶段就抛 `UnicodeDecodeError: 'gbk' codec can't decode
        # byte 0x80`，**报错位置和病因完全无关**。
        #
        # 现在 alembic.ini 是纯 ASCII 的，中文说明搬去了 env.py（Python
        # 源码本身就是按 UTF-8 读的，安全）。这里先探一下，好让将来有人
        # 把中文加回去时，报错直接说清楚是编码问题而不是别的。
        raw = ini.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise AssertionError(
                f"alembic.ini 里有非 ASCII 字符（偏移 {exc.start}）。"
                "Alembic 用系统区域编码读它，中文注释会让它读配置就崩。"
                "请把说明写进 alembic/env.py。"
            ) from exc

        cfg = Config(str(ini))
        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()
        return f"alembic {__import__('alembic').__version__}，读到 alembic.ini，当前 head={head!r}"

    check("alembic", "迁移工具", _alembic)

    # ── 配置与校验 ────────────────────────────────────────
    def _pydantic() -> str:
        import pydantic

        class M(pydantic.BaseModel):
            n: int

        # 【为什么试一次「该失败的失败」】pydantic 的**全部价值**就是
        # 拒绝不合形状的数据。如果它只是「能 import」，那它等于没用。
        try:
            M(n="不是数字")
        except pydantic.ValidationError:
            pass
        else:
            raise AssertionError("pydantic 没有拒绝一个明显不合法的输入")
        assert M(n="7").n == 7, "字符串数字应当被转成 int"
        return f"pydantic {pydantic.VERSION}，校验会拒绝坏数据、也会做类型转换"

    check("pydantic", "请求/响应模型", _pydantic)

    def _settings() -> str:
        import pydantic_settings

        from app.config import ProviderKind, Settings

        # 【为什么要真的构造一次 Settings】这一步同时验证了契约值
        # 与前端逐字一致（详见 app/config.py 的注释）。
        #
        # ⚠️ `_env_file=None` 不能省：这条断的是「**零配置**启动时是
        # 离线的 fake」。留着 `.env` 的话，一个配成 jimeng 的部署会让
        # 这条红掉 —— 而它真正想抓的是「默认值被改成了真 provider」
        # （那会让一台新机器**碰巧**开始花钱），那是**代码默认值**的问题，
        # 不是 `.env` 的问题。见 `_without_env` 的说明。
        s = Settings(_env_file=None, jwt_secret=PROBE_SECRET)  # type: ignore[arg-type]
        assert s.provider is ProviderKind.fake, "默认必须是离线可跑的 fake"
        assert s.credits_per_image == 4, s.credits_per_image
        assert s.credits_per_sec_720 == 4, s.credits_per_sec_720
        assert s.duration_slack_sec == 3, s.duration_slack_sec
        assert s.signup_grant == 50, s.signup_grant
        assert s.max_prompt_len == 2000, s.max_prompt_len
        assert s.max_image_bytes == 20 * 1024 * 1024, s.max_image_bytes

        # 冻结额必须真的是 32 —— 这是前端测试里写死的那个数（§7.2）
        freeze = (5 + s.duration_slack_sec) * s.credits_per_sec_720
        assert freeze == 32, f"5 秒 720P 应当冻结 32，算出来是 {freeze}"

        return (
            f"pydantic-settings {pydantic_settings.__version__}；"
            "且计价/配额默认值与前端常量逐字一致（图 4 / 720P 4每秒 / 余量 3 / 赠送 50）"
        )

    check("pydantic-settings", "环境变量配置（密钥防线）", _settings)

    def _settings_rejects_missing_secret() -> str:
        """反证：没给 JWT_SECRET 时必须起不来。

        【为什么这条要单独做】因为「缺密钥就启动失败」是这个项目
        密钥防线的核心，而**它只在真的失败时才成立**。
        一个永远返回配置对象、密钥为空也照跑的 `Settings`，
        会让「忘了配 JWT_SECRET」变成线上用空密钥签发 token 的事故。
        """
        from pydantic import ValidationError

        from app.config import Settings

        try:
            # 环境变量与 `.env` 都要挡掉 —— 部署时 JWT_SECRET 常常是
            # 从环境变量注入的，只挡 `.env` 的话这条在容器里会假红。
            with _without_env("JWT_SECRET"):
                Settings(_env_file=None)  # type: ignore[call-arg]
        except ValidationError:
            return "故意不传 JWT_SECRET → 确实起不来（密钥防线成立）"
        raise AssertionError(
            "没给 JWT_SECRET 却成功构造了 Settings —— 密钥防线失效，必须修"
        )

    check("密钥必填", "缺 JWT_SECRET 必须启动失败", _settings_rejects_missing_secret)

    def _settings_rejects_jimeng_without_keys() -> str:
        """反证：选了真 provider 却没给 AK/SK，也要起不来。

        ⚠️ 这里必须给一把**长度合格**的 JWT_SECRET。
        第一版写的是 `jwt_secret="x"`，在加上密钥强度校验之后，
        它仍然会抛异常 —— 但抛的是「密钥太短」，不是「缺 AK/SK」。
        **反证测试因为错的理由通过，等于没测**，所以这里的密钥必须是合法的，
        好让失败唯一的来源就是缺 AK/SK。

        ⚠️ 必须同时挡掉环境变量与 `.env`，否则 `.env` 里那对真 AK/SK
        会喂饱这条反证 —— 详见 `_without_env` 的说明。
        """
        from app.config import Settings

        try:
            with _without_env("JIMENG_AK", "JIMENG_SK"):
                Settings(  # type: ignore[arg-type]
                    _env_file=None,
                    jwt_secret=PROBE_SECRET,
                    provider="jimeng",
                )
        except Exception as exc:  # noqa: BLE001
            assert "ak" in str(exc).lower() or "sk" in str(exc).lower(), (
                f"配 jimeng 无密钥时起不来是对的，但原因是「{exc}」，"
                "不是缺 AK/SK —— 反证因为错的理由通过"
            )
            return f"PROVIDER=jimeng 且无 AK/SK → 确实起不来（{type(exc).__name__}）"
        raise AssertionError("配了 jimeng 却没给密钥，居然构造成功了")

    check("provider 必填", "选即梦就必须有 AK/SK", _settings_rejects_jimeng_without_keys)

    def _settings_rejects_weak_secret() -> str:
        """反证：空的 / 纯空白的 / 太短的密钥都必须起不来。

        【为什么这三种要一起测】因为「必填」只保证**提供了**字段，
        不保证提供的东西有用。实测中空的、纯空格的、`abc` 三种都是
        `str` 类型的合法值 —— 服务会带着一把谁都猜得到的密钥正常启动。
        见 `app/config.py` 里 `_jwt_secret_must_be_strong` 的说明。
        """
        from pydantic import ValidationError

        from app.config import Settings

        accepted: list[str] = []
        for bad in ("", "   ", "abc", "short-secret"):
            try:
                Settings(jwt_secret=bad)  # type: ignore[arg-type]
            except ValidationError:
                continue
            accepted.append(repr(bad))

        if accepted:
            raise AssertionError(f"这些弱密钥居然被接受了：{', '.join(accepted)}")
        return "空 / 纯空白 / 过短 的 JWT_SECRET 全部被拒（密钥强度校验生效）"

    check("密钥强度", "弱密钥必须启动失败", _settings_rejects_weak_secret)

    # ── 网络 ──────────────────────────────────────────────
    def _httpx() -> str:
        import asyncio

        import httpx

        # 【为什么要验 ASGITransport】B2 的契约测试靠它直接打 FastAPI app，
        # 不起真服务器、不占端口。这条不通的话，那套测试的形态要重设计。
        #
        # ⚠️⚠️ **构造 app 之前必须把 worker 关掉。**
        # `create_app()` 会按配置起一个**真的后台 worker 线程**，而它的
        # 职责是「把库里的 `queued` 任务出队交给 provider」。
        # 以前 PROVIDER 恒为 fake，这条线程无害，所以没人注意到；
        # 配成 `jimeng` 之后，它会**真的花钱** —— 一个本该是只读的
        # 依赖闸门，顺手就把钱发出去了。跑闸门的那台机器通常正是
        # 配了真凭据、库里也真有任务的那台。
        #
        # 关它的方式只能是环境变量（`create_app` 内部读配置），
        # 所以这里改 env + 清一次 `get_settings` 的 lru_cache，
        # 跑完再把两边都还原 —— 后面的检查还要靠当前配置。
        from app.config import get_settings
        from app.main import create_app

        get_settings.cache_clear()
        os.environ["WORKER_ENABLED"] = "0"
        try:
            app = create_app()
        finally:
            os.environ.pop("WORKER_ENABLED", None)
            get_settings.cache_clear()

        async def _go() -> dict:
            # 【为什么必须是 AsyncClient】httpx 0.28 起 `ASGITransport`
            # **只实现异步接口**。同步的 `httpx.Client(transport=...)` 会在
            # 进上下文时抛 `AttributeError: 'ASGITransport' object has no
            # attribute '__enter__'` —— 那条路已经被删了。
            #
            # 这不只是这个脚本的写法问题：**B2 的整套契约测试都要长这样**
            # （async 用例 + AsyncClient）。在这里先撞一次，好过在 B2 写了
            # 三十个同步用例之后才发现。
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as c:
                r = await c.get("/health")
            assert r.status_code == 200, r.status_code
            return r.json()

        body = asyncio.run(_go())

        # 【为什么这里比对的是**当前配置**，不是写死的 "fake"】
        # 这条要证明的是「/health 如实上报进程真正连着的那个 provider」——
        # 运维第一眼就是看它，而它撒谎（配了 jimeng 却回 fake）比不报还坏。
        # 写死 "fake" 只在零配置的机器上成立，配好凭据的机器上会假红，
        # 而**配好凭据的机器正是这个闸门唯一该跑的地方**。
        configured = get_settings().provider.value
        assert body["provider"] == configured, (
            f"/health 说 provider 是 {body['provider']!r}，"
            f"而配置里是 {configured!r} —— 它没如实上报"
        )
        return f"httpx {httpx.__version__}；且真的用 ASGITransport 打了一次 /health → {body}"

    check("httpx", "打即梦 + 打自己的 app", _httpx)

    # ── 鉴权 ──────────────────────────────────────────────
    def _bcrypt() -> str:
        import bcrypt

        h = bcrypt.hashpw(b"pw123456", bcrypt.gensalt(rounds=4))
        assert bcrypt.checkpw(b"pw123456", h), "正确的密码没通过校验"
        assert not bcrypt.checkpw(b"wrong", h), "错误的密码居然通过了校验"
        return f"bcrypt {bcrypt.__version__}；哈希 + 正确密码过 + 错误密码不过"

    check("bcrypt", "§6.1 禁止明文密码", _bcrypt)

    def _pyjwt() -> str:
        import jwt

        token = jwt.encode({"sub": "1"}, "k", algorithm="HS256")
        claims = jwt.decode(token, "k", algorithms=["HS256"])
        assert claims["sub"] == "1", claims

        # 【为什么要试一次过期】因为「过期即 401，让前端登出」是
        # §6.1 的会话方案，而它靠的就是这个库真的会抛 ExpiredSignatureError。
        import time

        stale = jwt.encode({"sub": "1", "exp": int(time.time()) - 10}, "k", algorithm="HS256")
        try:
            jwt.decode(stale, "k", algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            pass
        else:
            raise AssertionError("过期 token 居然通过了校验")
        return f"PyJWT {jwt.__version__}；签发/校验/过期拒绝都通"

    check("pyjwt", "JWT 签发与过期", _pyjwt)

    # ── 上传与媒体 ────────────────────────────────────────
    def _multipart() -> str:
        import multipart

        # 【为什么专门盯这个包】因为它是个「不装就报一句奇怪的错」的依赖：
        # FastAPI 遇到 UploadFile 时会说「安装 python-multipart 以支持表单」，
        # 而那行错误出现在**运行时**、在某个你没在调的接口上。
        assert multipart.__version__, "没有 __version__"
        return f"python-multipart {multipart.__version__}（UploadFile 依赖它）"

    check("python-multipart", "上传参考图（§12.1）", _multipart)

    def _pillow() -> str:
        from io import BytesIO

        from PIL import Image

        # 【为什么要真的 encode/decode 一张图】这条能验到 C 扩展
        # （`_imaging`）真的加载了 —— 只 import 的话，坏掉的 Pillow
        # 会以纯 Python 垫片的形式「成功」，然后在第一次开图时炸。
        buf = BytesIO()
        Image.new("RGB", (32, 18), (200, 40, 60)).save(buf, format="PNG")
        raw = buf.getvalue()
        img = Image.open(BytesIO(raw))
        assert img.size == (32, 18), img.size

        # 【为什么还要试一次坏数据】B4 的「这根本不是图片」这条路
        # 就是靠 Image.open 抛异常实现的。它不抛的话，我们会把
        # 一个任意文件当图片收下并上传。
        try:
            Image.open(BytesIO("这根本不是图片".encode()))
        except Exception:  # noqa: BLE001
            pass
        else:
            raise AssertionError("Pillow 没拒绝一个非图片文件")

        return f"Pillow {Image.__version__}；PNG 编码/解码 + 拒绝非图片文件都通"

    check("pillow", "缩略图 + 图片合法性校验", _pillow)

    # ── 对象存储与真 provider（B6）────────────────────────
    #
    # 这三项和上面那些的差别是：它们验的**不是包本身装没装上**，
    # 而是「B6 接进来的那两件外部东西，在我们这条路上真的转得起来」。
    # 放在这里而不是放进 `pytest`，理由和本文件开头那段一样 ——
    # 这一类失败必须在**动手之前**看到，而不是写到一半才发现。

    def _boto3() -> str:
        """一条**真的** S3 往返。

        ─────────────────────────────────────────────────────
        【为什么不是 `import boto3` 了事】

        因为「包装上了」和「能对着一个桶把字节写进去、head 得到、
        读得回来、删得掉」之间隔着三层：签名器、寻址风格、连接池。
        而这三层里任何一层不对，报出来的都不是「boto3 没装」。

        【这里的边界在哪 —— 别把它读成「OSS 通了」】
        `before-send.s3.*` 是 boto3 留的最后一处缝：消息已经造好、
        **已经签好**，只是还没上线路。所以能证的是一直到线路之前的
        全部（动词、参数名、签名形状、地址形状），**不能证**的是
        真桶接不接受这个桶名/区域/权限。后者要等 AK/SK 与桶名
        （§18-2），那部分在 `HANDOFF.md` 的清单里。
        ─────────────────────────────────────────────────────
        """
        import io

        import boto3
        from botocore.awsrequest import AWSResponse
        from botocore.config import Config

        from app.services.storage import S3Storage

        objects: dict[str, bytes] = {}
        seen: list[str] = []
        auth: list[str] = []

        class _Raw:
            """`AWSResponse.raw` 的替身：botocore 会调 `.read()` 与 `.stream()`。

            【为什么不能塞 `io.BytesIO`】它只有 `read()`。非流式响应
            走 `.content` → `.stream()`，于是第一次 PUT 就会抛
            `AttributeError: ... has no attribute 'stream'` ——
            而那个报错长得像「boto3 装坏了」。
            """

            def __init__(self, data: bytes) -> None:
                self._buf = io.BytesIO(data)

            def read(self, amt: int | None = None) -> bytes:
                return self._buf.read() if amt is None else self._buf.read(amt)

            def stream(self, amt: int = 65536, decode_content: object = None):
                del decode_content
                while True:
                    chunk = self._buf.read(amt)
                    if not chunk:
                        return
                    yield chunk

            def close(self) -> None:
                pass

        def send(request, **_kwargs: object) -> AWSResponse:
            url = str(request.url)
            seen.append(f"{request.method} {url}")
            raw = request.headers.get("Authorization", "")
            auth.append(raw.decode("latin-1") if isinstance(raw, bytes) else str(raw))

            key = url.split("/dep-gate-bucket/", 1)[-1].split("?", 1)[0]
            if request.method == "PUT":
                body = request.body
                objects[key] = body.read() if hasattr(body, "read") else body
                return AWSResponse(url, 200, {}, _Raw(b""))
            if request.method in ("GET", "HEAD"):
                if key not in objects:
                    # 真 S3 对 HEAD 的 404 回的是**空 body**，botocore 只能
                    # 把错误码合成成字面量 "404"。`S3Storage.exists` 认的
                    # 就是这一种 —— 拿 XML 那种形状替掉它，那条分支会
                    # 在**本地全绿**、到了真桶上才炸。
                    return AWSResponse(url, 404, {}, _Raw(b""))
                payload = objects[key]
                headers = {"content-length": str(len(payload))}
                if request.method == "HEAD":
                    return AWSResponse(url, 200, headers, _Raw(b""))
                return AWSResponse(url, 200, headers, _Raw(payload))
            if request.method == "DELETE":
                objects.pop(key, None)
                return AWSResponse(url, 204, {}, _Raw(b""))
            raise AssertionError(f"实现里多了一次 {request.method} —— 替身没料到它")

        client = boto3.client(
            "s3",
            endpoint_url="http://s3.invalid",
            region_name="cn-hangzhou",
            aws_access_key_id="AK-DEP-GATE-NOT-REAL",
            aws_secret_access_key="SK-DEP-GATE-NOT-REAL",
            config=Config(s3={"addressing_style": "path"}),
        )
        client.meta.events.register("before-send.s3.*", send)
        store = S3Storage(
            bucket="dep-gate-bucket", public_base_url="https://cdn.invalid", client=client
        )

        store.put_bytes("t/1/probe.png", b"\x89PNG-dep-gate", content_type="image/png")
        assert store.exists("t/1/probe.png"), "put 完 head 不到 —— 写和读的键不是一个"
        assert store.read_bytes("t/1/probe.png") == b"\x89PNG-dep-gate"
        url = store.url_for("t/1/probe.png")
        # 【两次必须一模一样】预签名地址带时间（`X-Amz-Date` 至少到秒），
        # 所以「两次相等」正好卡在预签名的定义性特征上 —— 而
        # `public_url` 在契约里是**永久**的。见 `storage.py::url_for`。
        assert url == store.url_for("t/1/probe.png") == "https://cdn.invalid/t/1/probe.png"
        store.delete("t/1/probe.png")
        assert not store.exists("t/1/probe.png"), "删完还在 —— 那 DELETE 根本没发出去"

        assert seen[0] == "PUT http://s3.invalid/dep-gate-bucket/t/1/probe.png", seen[0]
        assert auth[0].startswith("AWS4-HMAC-SHA256 "), f"没签上名：{auth[0][:60]}"
        # 【密钥不许出现在请求的任何一处】签名把密钥**派生**成了签名，
        # 原始 SK 不该上线。这条在本地替身里没人管，而它是这里唯一
        # 不可挽回的错误。
        assert "SK-DEP-GATE-NOT-REAL" not in " ".join(auth + seen)

        return (
            f"boto3 {boto3.__version__}；真走了一轮 put/head/get/delete"
            f"（{len(seen)} 次调用），路径风格 + AWS4-HMAC-SHA256 都对"
        )

    check("boto3", "STORAGE=oss 的字节怎么进出（§9.1）", _boto3)

    def _settings_rejects_oss_without_bucket() -> str:
        """反证：`STORAGE=oss` 却没给桶名/密钥，必须**启动就炸**。

        ⚠️ 同下面 `provider 必填` 那条的纪律：`jwt_secret` 必须是一把
        **长度合格**的，否则失败会来自「密钥太短」——反证因为错的
        理由通过，等于没测。这里断言失败信息里真的提到桶名。
        """
        from app.config import Settings

        try:
            with _without_env(
                "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"
            ):
                Settings(  # type: ignore[arg-type]
                    _env_file=None,
                    jwt_secret=PROBE_SECRET,
                    storage="oss",
                )
        except Exception as exc:  # noqa: BLE001
            assert "s3_bucket" in str(exc).lower(), (
                f"配 oss 无桶名时起不来是对的，但原因是「{exc}」，不是缺桶名"
            )
            return "STORAGE=oss 且无桶名/密钥 → 确实起不来（不会等到第一次转存才炸）"
        raise AssertionError("配了 oss 却没给桶名，居然构造成功了")

    check("oss 配置必填", "STORAGE=oss 就必须有桶名与密钥", _settings_rejects_oss_without_bucket)

    def _settings_rejects_jimeng_without_req_key() -> str:
        """反证：配了即梦、密钥也给了，但**没给 `req_key`**，也要起不来。

        ─────────────────────────────────────────────────────
        【为什么这条要单独存在】

        `AK/SK 必填` 那道守卫挡不住它：一个配了密钥却没配 `req_key`
        的部署会**正常启动**，然后在第一次生成时花掉一次真调用
        换回一句「不支持的 req_key」。那笔钱不多，但它是**在能事前
        拦下来的情况下花掉的**。

        同理，这里 `jwt_secret` 与 AK/SK 都给足 —— 好让失败唯一的
        来源就是缺 `req_key`。

        ⚠️ `_env_file=None` + `_without_env`：`.env` 里那两个真 `req_key`
        会让这条反证**因为错的理由通过**（上游那条 AK/SK 守卫会更早
        看到「都配齐了」而放行）。这正是它自己在上面警告的那种事。
        ─────────────────────────────────────────────────────
        """
        from app.config import Settings

        try:
            with _without_env("JIMENG_REQ_KEY_IMAGE", "JIMENG_REQ_KEY_VIDEO"):
                Settings(  # type: ignore[arg-type]
                    _env_file=None,
                    jwt_secret=PROBE_SECRET,
                    provider="jimeng",
                    jimeng_ak="AK-DEP-GATE-NOT-REAL",
                    jimeng_sk="SK-DEP-GATE-NOT-REAL",
                )
        except Exception as exc:  # noqa: BLE001
            assert "req_key" in str(exc).lower(), (
                f"配 jimeng 无 req_key 时起不来是对的，但原因是「{exc}」，不是缺 req_key"
            )
            return "PROVIDER=jimeng 且无 req_key → 确实起不来（不会花一次真调用去换报错）"
        raise AssertionError("配了 jimeng 却没给 req_key，居然构造成功了")

    check("req_key 必填", "选即梦就必须有能力的路由键", _settings_rejects_jimeng_without_req_key)

    # ── 外部二进制 ────────────────────────────────────────
    def _ffmpeg() -> str:
        exe = shutil.which("ffmpeg")
        if not exe:
            # 【为什么这里是失败而不是跳过】见下面 warning 段的说明。
            raise FileNotFoundError(
                "PATH 里没有 ffmpeg（§16 的人工步骤之一，装完重开终端）"
            )
        out = subprocess.run(  # noqa: S603
            [exe, "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert out.returncode == 0, out.stderr[:200]
        first = out.stdout.splitlines()[0]
        return f"{first}（{exe}）"

    check("ffmpeg", "视频抽封面帧（§4.1 / §16）", _ffmpeg)

    # ── 汇总 ──────────────────────────────────────────────
    print()
    total = passed + len(failures)
    print("=" * 68)
    if not failures:
        # 【为什么这句话不带批次号】它原来写的是「可以开始 B1 了」，
        # 而 B1 早就过去了 —— 一句会撒谎的输出和真的一样有说服力。
        print(f"  ✅ 全过（{total} 项）。依赖这边没问题。")
        print("=" * 68)
        print()
        return 0

    print(f"  ❌ {len(failures)}/{total} 项没过：")
    for f in failures:
        print(f"     · {f}")
    print("=" * 68)
    print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
