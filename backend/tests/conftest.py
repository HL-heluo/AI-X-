"""pytest 全局夹具。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【为什么这个文件的第一件事是往环境里塞 JWT_SECRET】

`app/config.py` 里 `JWT_SECRET` 刻意**没有默认值**，缺了就启动失败。
那是密钥防线的核心：忘了配密钥时，宁可不启动，也不要拿空密钥签发 token。

但那条防线对「跑测试」是个障碍。测试如果依赖开发者本机 `.env`：

  · CI 上没有 `.env` → 全部测试在**导入阶段**就红，
    而那种红和被测代码一行关系都没有；
  · 更糟的是变成「本机绿、CI 红」，人开始怀疑代码而不是环境。

所以夹具在**导入 app 之前**塞一个明显是假的密钥进去。
顺序要紧：`get_settings()` 带 `lru_cache`，`Settings` 只在第一次
构造时读环境 —— 晚一步就来不及了。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import os

# ⚠️ 必须在 `import app.*` 之前，所以放在文件最顶部。
#
# 值故意写成这个形状，好让它在任何日志、报错、截图里一眼就是测试用的 ——
# 一个长得像真密钥的测试密钥，早晚会被人复制到别处去。
os.environ.setdefault("JWT_SECRET", "test-only-secret-not-for-any-real-use")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("BCRYPT_ROUNDS", "4")  # 默认 12 会让每条注册用例多付 ~250ms
os.environ.setdefault("TEST_MODE", "1")
# 【为什么要显式钉住 provider/storage】因为开发者本机的 `.env` 可能把
# PROVIDER 改成了 jimeng 在调真接口。测试必须**永远**跑假的，否则
# 某天有人在本地跑一次测试就花掉真钱，而且跑得很慢、还联网。
os.environ.setdefault("PROVIDER", "fake")
os.environ.setdefault("STORAGE", "local")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Engine]:
    """一个建好全部表的临时 SQLite 库，**每个用例一个**。

    ─────────────────────────────────────────────────────────
    【为什么用临时**文件**库，而不是 `sqlite://` 内存库】

    内存库每个连接是**不同的库**，所以它和真实运行时的差别恰好落在
    本项目最在意的地方：连接池、pragma、事务可见性。用它测出来的
    「约束生效了」可能只是「同一个连接看得见自己」而已。

    【为什么每个用例一个库，而不是共用一个再清表】
    因为「共用一个再清表」时，清表顺序要跟外键依赖一致，
    清不干净会**跨用例污染** —— 而污染的表现是随机失败、换个执行顺序
    就消失，极难定位。每个用例一个新文件，成本是几毫秒，买到的是
    「用例之间绝无可能互相影响」。
    ─────────────────────────────────────────────────────────
    """
    # 导入只为副作用：把 7 张表注册进 Base.metadata。
    import app.models  # noqa: F401

    from app.database import Base, build_engine

    engine = build_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(db: Engine) -> Iterator[Session]:
    """一个绑在上面那个临时库上的会话。"""
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db, autoflush=False, expire_on_commit=False)
    with factory() as s:
        yield s



@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """临时改一个配置项，并让 `get_settings()` **真的重新读一遍**。

    ─────────────────────────────────────────────────────────
    【为什么不能 `monkeypatch.setenv(...)` 了事】

    和 `make_app` 是同一个坑的另一半：`get_settings()` 带 `lru_cache`，
    所以 `setenv` 之后**已经构造过**的那份配置并不会变。于是

        monkeypatch.setenv("MODERATION_ENABLED", "0")
        assert screen_input("制作炸弹") is None     # ← 还是拿旧配置判的

    会在「上一个用例恰好没碰过配置」时**通过** —— 那种绿比红更坏，
    因为它只取决于执行顺序。

    【为什么不用 `make_app`】那个夹具是给「要造一个 app」的用例用的，
    它顺便做了建 app 这件事。纯单元测试（B5 的 moderation / marking
    大半是纯判断）不需要 app，只需要配置生效。

    【为什么收尾要再清一次】`monkeypatch` 会把环境变量还回去，但
    `lru_cache` 里还留着**被改过**的那一份。不还的话，下一个用例
    拿到的是这个用例的配置 —— 又是一次跨用例污染。
    ─────────────────────────────────────────────────────────
    """
    from app.config import get_settings

    def _set(**env: str) -> None:
        for key, value in env.items():
            monkeypatch.setenv(key.upper(), value)
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


@pytest.fixture
def make_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """按需覆盖环境变量后造一个 app。

    ─────────────────────────────────────────────────────────
    【为什么需要这个夹具，而不是直接 `create_app()`】

    因为 `get_settings()` 带 `lru_cache`，`create_app()` 读的永远是
    **第一次**构造出来的那份配置。于是想测「TEST_MODE=0 时
    `/__test/*` 根本不存在」这类事情时，天真的写法是：

        monkeypatch.setenv("TEST_MODE", "0")
        app = create_app()          # ← 拿到的还是 TEST_MODE=1 的那份

    测出来的结果是上一个用例的配置，而测试**照样是绿的**。
    这种「夹具本身在撒谎」的失败最难发现，所以把三步
    （改环境 → 清缓存 → 建 app）收进一个夹具里，让使用者
    不可能漏掉中间那步。
    ─────────────────────────────────────────────────────────
    """
    from fastapi import FastAPI

    def _make(**env: str) -> FastAPI:
        for key, value in env.items():
            monkeypatch.setenv(key.upper(), value)
        # 【这一步是整件事的关键】不清缓存的话，下面的 create_app()
        # 读到的还是上一次的配置。
        get_settings.cache_clear()
        return create_app()

    yield _make
    # 用例结束后恢复，免得缓存里留着被改过的那份污染下一个用例。
    get_settings.cache_clear()


@pytest.fixture
async def client(make_app: object) -> "httpx.AsyncClient":  # type: ignore[valid-type]
    """一个直接打 FastAPI app 的 HTTP 客户端。

    【为什么用 ASGITransport 而不是起真服务器】
    不起真服务器 = 不占端口、不用等就绪、不会因为端口被占而 flaky，
    而且每个用例拿到的是一个**干净的** app。代价是跳过了真实网络栈，
    所以 B0 的门禁另外真的起了一次 uvicorn（见 README）。

    ⚠️ httpx 0.28 起 `ASGITransport` **只有异步接口** ——
    同步的 `httpx.Client(transport=...)` 会抛
    `AttributeError: ... has no attribute '__enter__'`。
    所以整套契约测试都是 async 的，这不是风格选择。
    """
    app = make_app()  # type: ignore[operator]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ══════════════════════════════════════════════════════════════
# B2：打真数据库的 API 夹具
# ══════════════════════════════════════════════════════════════
#
# 上面那个 `client` 是 B0 留下的，它**不碰数据库** —— B0 的端点全都不读库，
# 所以它连 DATABASE_URL 都没改过。B2 的端点每一个都要读库，于是需要
# 另一套夹具，它比上面多做两件事：
#
#   1. 把 DATABASE_URL 指到一个临时文件库，并**丢掉进程级引擎**
#      （`reset_engine()`）—— 引擎是模块级全局，不丢的话即使换了
#      DATABASE_URL，请求用的还是上一个用例的那个库。
#   2. 造完 app 之后打一次 `POST /__test/reset`，让库里有那个
#      不限次的邀请码 `MOCK`。
#
# 【为什么 reset 由夹具做，而不是每个用例自己调】因为漏了它的表现是
# 注册时 400「邀请码 MOCK 不存在」—— 一个与用例真正要测的东西
# 毫无关系的失败。夹具做好这件事，用例里就只剩业务本身。


@pytest.fixture
def api_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """一个**连临时库**的 app。见上面那段说明。"""
    from fastapi import FastAPI

    from app.database import reset_engine

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    # 上传用例会往 MEDIA_ROOT 里写（B2 其实不写字节，但路径也别落到
    # 仓库根目录去 —— 那会留下一个 media/ 目录，还会让两次运行互相影响）。
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path / "media"))
    # 【B4：这一条是必需的，不是洁癖】fake provider 现在会**真的造字节**
    # （Pillow 渲图 / ffmpeg 合成 mp4），而产物是**按内容缓存在盘上**的。
    # 不钉住的话：产物会落进仓库根目录的 `.provider_spool/`，而那份缓存
    # 会**跨用例、跨整次运行**地留着 —— 于是「这个文件是新造的」这类
    # 断言会随执行顺序变化，那种红最难查（因为单独跑那个用例是绿的）。
    monkeypatch.setenv("PROVIDER_SPOOL_ROOT", str(tmp_path / "spool"))
    monkeypatch.setenv("TEST_MODE", "1")

    # ⚠️ 顺序不能反：先清配置缓存，再丢引擎。
    # 反过来的话，`reset_engine()` 之后 `get_settings()` 还是旧的那份，
    # 下面建出来的引擎会指向**上一个用例的库** —— 而测试照样是绿的，
    # 只是所有数据都写进了别处。
    get_settings.cache_clear()
    reset_engine()

    app: FastAPI = create_app()

    yield app

    # 用例结束后把全局状态还回去。不还的话，下一个用 `session` 夹具
    # （自己建引擎）的用例没事，但用 `client`（靠 get_settings() 建库）
    # 的用例会拿到这个临时库 —— 而那个库已经被删了。
    reset_engine()
    get_settings.cache_clear()


@pytest.fixture
async def api(api_app) -> "httpx.AsyncClient":  # type: ignore[valid-type]
    """打 B2 端点的客户端。库里已经有 `MOCK` 邀请码，**没有用户**。"""
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        res = await c.post("/__test/reset")
        assert res.status_code == 200, (
            f"夹具的 /__test/reset 失败了：{res.status_code} {res.text}"
        )
        assert res.json()["invite_code"] == "MOCK"
        yield c


# ══════════════════════════════════════════════════════════════
# B3：队列 / worker 用的两件夹具
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def api_session(api) -> Iterator[Session]:  # type: ignore[valid-type]
    """一个**绑在 `api` 那个库上**的会话 —— 直接摆数据用。

    ─────────────────────────────────────────────────────────
    【为什么不能直接用上面那个 `session`】

    因为 `session` 绑的是 `db` 夹具的库，`api` 绑的是 `api_app` 的库 ——
    **两个不同的临时文件**。往 `session` 里插一条 `user_id=7` 的任务，
    那边根本没有这个用户，外键（`PRAGMA foreign_keys=ON`）当场报错。
    而如果哪张表恰好没有外键，错误就变成「查不到数据」这种
    看起来像业务 bug 的东西。

    【为什么必须依赖 `api`，而不是只依赖 `api_app`】
    `api` 的夹具体里打了 `/__test/reset`（drop + create + 种邀请码）。
    如果 `api_session` 只依赖 `api_app`，pytest 可能先把它建好、
    再执行 reset —— 那么会话手里攥着的是**已经被 drop 掉**的表。
    依赖 `api` 就把顺序钉死了：reset 一定发生在建会话之前。
    ─────────────────────────────────────────────────────────
    """
    from app.database import get_session_factory

    with get_session_factory()() as s:
        yield s


# ── provider 替身 ─────────────────────────────────────────────
#
# 类在 `tests/_providers.py`，夹具必须在这儿（pytest 只从 conftest
# 和已注册插件里收夹具；那个文件里的说明写了为什么）。


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch):
    """把 `build_provider()` 换成剧本替身。见 `_providers.ScriptedProvider`。

    ─────────────────────────────────────────────────────────
    【为什么两处都要打补丁，而且必须用字符串目标】

    `generation.py` 和 `worker.py` 都是
    `from app.providers import build_provider` —— 名字在**导入时**
    就绑定了。所以 `monkeypatch.setattr(app.providers, "build_provider", ...)`
    **不起作用**：那两个模块手里还攥着原来那个函数对象。

    这个坑的表现是「用了假的 provider，但测试里跑的还是真 fake」——
    而它不会报错，只会让那些依赖「任务停在 submitted」的用例
    以一种莫名其妙的方式变绿或变红。用字符串目标能一次改对模块级名字。

    【B7.x：替身为什么收下 `kind` 却不用它】

    `build_provider` 长出了 `kind` 形参（图片与视频可以不是同一个
    provider，见 `providers/__init__.py`）。而**注入的替身对每一种
    kind 都有效** —— 它的用途是「让整条流水线不碰真网关」，
    按 kind 分只在从配置造的时候才有意义。

    所以这里是 `lambda kind: provider`：**收下**这个参数（不收会
    `TypeError`），但**每个 kind 都给同一个替身**。这样既有测试
    一个字不改，而「替身漏接 kind」这件事也不会静默通过。
    ─────────────────────────────────────────────────────────
    """
    from _providers import ScriptedProvider

    provider = ScriptedProvider()
    monkeypatch.setattr("app.services.generation.build_provider", lambda kind: provider)
    monkeypatch.setattr("app.worker.build_provider", lambda kind: provider)
    yield provider


@pytest.fixture
def instant_scripted(scripted):
    """一个「异步接口、但第一次问就有结果」的替身。

    它存在的意义是把两件事分开验：
    **「任务会不会经过队列」**（由 `polls_before_done` 决定）
    和 **「谁把它推到终态」**（请求路径还是 worker）。
    前者是 §8.2 的队列规则，后者是 §8.3 的分工 —— 混在一起测的话，
    一条用例红了看不出是哪一条坏了。
    """
    scripted.polls_before_done = 0
    return scripted
