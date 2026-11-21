"""隐式标识 —— 把「这是 AI 生成的」写进文件本身（§10.1）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【这是法律义务，不是产品功能】

《人工智能生成合成内容标识办法》要求生成合成内容带**显式标识**
（用户看得见的那种）和**隐式标识**（写在文件元数据里的那种）。
前端负责前者（作品上的「AI 生成」角标），后端负责后者 ——
因为只有后端碰得到字节。

【为什么「隐式」比「显式」更要紧】

显式标识跟着**我们**走：用户把作品存到手机相册，角标就没了。
隐式标识跟着**文件**走：EXIF / XMP / MP4 元数据会被系统相册、
传输链路、审查工具读取，而且它不容易被无意抹掉。
所以「这个文件是 AI 生成的」这件事，最终是靠这一层留痕的。

【它和「打水印」不是一回事，别混】
水印改**像素**（用户看得见、也能裁掉），这里改的是**容器元数据**
（用户看不见、但要抹掉得专门动手）。两者互补，v1 只做这里这个 ——
水印会破坏画质，而 §10.1 要求的是标识，不是防盗。

【这一层只决定「写什么」，不决定「怎么写」】
真正的字节操作用 `services/transcode.py`（Pillow / ffmpeg 的唯一落点）。
分开的理由见那个文件的开头。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from app.config import get_settings
from app.services.transcode import (
    TranscodeError,
    remux_with_tags,
    write_image_marker,
)
from app.types import utcnow

logger = logging.getLogger(__name__)

# 写进标识的那句话。**中文和英文都给**：
# 中文是《标识办法》语境下的主张，英文是给不认中文的解析工具看的。
AI_LABEL = "AI 生成"
AI_LABEL_EN = "AI-generated"

# 视频元数据的键。选这三个是因为它们在 MP4 的原生 `ilst` 里**有对应原子**
# （`©nam` / `©cmt` / `desc`），所以不依赖 `use_metadata_tags` 的扩展原子
# 也能被大多数工具读出来 —— 多一条冗余，就多一个读得到的地方。
_VIDEO_TAG_KEYS = ("title", "comment", "description")


@dataclass(frozen=True, slots=True)
class MarkerPayload:
    """要写进标识里的东西。

    ─────────────────────────────────────────────────────────
    【为什么只有四个字段，而且**没有** provider / 模型名 / 提示词】

    因为标识要回答的问题是「**这段内容是不是 AI 生成的**」以及
    「**它属于哪一次生成**」。前者由 `AI_LABEL` 回答，
    后者由 `task_id` 回答。

    `task_id` 是一把**钥匙**，不是一份拷贝：拿它回库里查
    （`tasks.provider` / `params_json` / `created_at`）能拿到全部细节，
    而把细节抄进文件是三重浪费 —— 它会让标识变长、会因为库里改了
    而对不上、还会把用户的提示词写进一个会被到处转发的文件里
    （提示词是用户的内容，不是我们的元数据）。

    【为什么没有 `model`】即梦的模型 id 至今没在控制台确认过
    （`即梦API接入.md` §18 第 2 条）。一个字段如果只能填一个
    猜出来的值，那它比没有更坏 —— 事后没人分得清哪个是猜的。
    等 B6 确认了再往这里加，那时它是一个有出处的值。
    ─────────────────────────────────────────────────────────
    """

    task_id: int
    kind: str
    created_at: str
        # ISO-8601（UTC）。**字符串而不是 datetime** —— 它要进三种
        # 容器的三种编码，统一在构造时定成一个形态，比三处各自
        # `isoformat()` 少三个分歧点。
    creator: str
        # 生成服务提供者。取 `settings.marking_creator`。


def payload_for(*, task_id: int, kind: str) -> MarkerPayload:
    """按一次生成造一份标识内容。**不碰数据库。**

    【为什么它不需要 Task 对象】因为它调用的地方
    （`transfer.transfer_artifact`）是一段**纯 IO**，手里没有会话、
    也没有 ORM 对象。给它塞一个 Task 就等于把「这一段不碰数据库」
    这条边界拆掉了 —— 而那条边界正是转存层能被单独测试的原因。
    所以需要的东西在这里现算：时间取当下，提供者取配置。
    """
    return MarkerPayload(
        task_id=task_id,
        kind=kind,
        created_at=utcnow().isoformat(),
        creator=get_settings().marking_creator,
    )


def marker_text(payload: MarkerPayload) -> str:
    """完整的、人可读的一行标识（含中文）。

    去处：EXIF `UserComment`（UTF-16-BE）、XMP `dc:description`（UTF-8）、
    MP4 的 `title`/`comment`/`description`（UTF-8）——
    **这三个容器都装得下中文**，所以中文标识就写在这些地方。
    """
    return (
        f"{AI_LABEL}（{AI_LABEL_EN}）"
        f" · {payload.creator}"
        f" · task={payload.task_id}"
        f" · kind={payload.kind}"
        f" · {payload.created_at}"
    )


def marker_text_ascii(payload: MarkerPayload) -> str:
    """**纯 ASCII** 的一行标识。只给 EXIF `ImageDescription` 用。

    ─────────────────────────────────────────────────────────
    【为什么同一个标识要有两个版本】

    因为 EXIF 标签分**类型**，而类型决定了它能装什么：

      · `UserComment`（0x9286）是 UNDEFINED 型 —— 里面是什么编码由
        我们自己声明（`b"UNICODE\\x00"` + UTF-16-BE），中文进得去。
      · `ImageDescription`（0x010E）是 **ASCII 型** —— 只能装 ASCII，
        而 Pillow 碰上非 ASCII **不报错**，它换成 `?` 照常存盘。

    所以中文走前者、ASCII 走后者。这不是「兼容性考虑」，
    是「后者真的装不下」—— 实测写 "AI 生成" 进去读回来是 "AI ?? "。

    【为什么还要留 `ImageDescription` 这个字段，不干脆别写】
    因为它是最**通用**的一个：连只认最基础 EXIF 的老工具都能读它。
    一个英文标识写在最通用的字段里，一个完整标识写在富字段里，
    两边都问得到「这是 AI 生成的」。

    【creator 里混进中文怎么办】那就把它 ASCII 化成一个**明确的**记号，
    而不是让 Pillow 去换成一串问号（那会变成「读得出但看不出丢过东西」）。
    用反斜杠转义（`\\u4e2d`）而不是 `?`：转义是**可逆**的，
    看到它的人知道原文是什么；`?` 是不可逆的，等于把信息扔了。
    ─────────────────────────────────────────────────────────
    """
    creator = payload.creator
    if not creator.isascii():
        creator = creator.encode("unicode_escape").decode("ascii")
    return (
        f"{AI_LABEL_EN}"
        f" | {creator}"
        f" | task={payload.task_id}"
        f" | kind={payload.kind}"
        f" | {payload.created_at}"
    )


def xmp_packet(payload: MarkerPayload) -> bytes:
    """一个**最小**的 XMP 包（UTF-8）。

    ─────────────────────────────────────────────────────────
    【为什么要手写 XML，而不是引一个 XMP 库】

    XMP 是 RDF/XML，用库生成会得到一段正确但冗长、且带一堆命名空间的
    XML（几百行）。而这里要表达的只有两件事：**描述**（dc:description）
    和**生成工具**（xmp:CreatorTool）。手写一个二十行的包，
    读的人一眼能看全 —— 而将来真要读复杂的 XMP，读的是**别人的**
    文件，那是读路径的事，和这里无关。

    【`<?xpacket?>` 那两行是必需的】它是 XMP 的容器封装，
    让扫描工具能在文件里定位这个包。省掉它，Adobe 系的工具
    会把这段 XML 当成一段无关的文本。

    【文本为什么要 escape】`payload.creator` 来自配置，
    而配置是人写的。一个 `&` 就能让整个包变成非法 XML ——
    而症状是「所有工具都读不到标识」，看起来像没写进去。
    ─────────────────────────────────────────────────────────
    """
    text = escape(marker_text(payload))
    creator = escape(payload.creator)
    # ⚠️ `begin` 后面那个是 U+FEFF（零宽不换行空格），XMP 规范要求它。
    # 用转义写，别把那个字符直接打进源码 —— 看不见的字符在字符串
    # 字面量里，下一次编辑就可能被删掉而没人发现。
    return (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about=""\n'
        '    xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '    xmlns:xmp="http://ns.adobe.com/xap/1.0/">\n'
        "   <dc:description><rdf:Alt>\n"
        f'    <rdf:li xml:lang="x-default">{text}</rdf:li>\n'
        "   </rdf:Alt></dc:description>\n"
        f"   <xmp:CreatorTool>{creator}</xmp:CreatorTool>\n"
        "  </rdf:Description>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    ).encode("utf-8")


def apply_marker(path: Path, *, mime: str, payload: MarkerPayload) -> None:
    """就地给一个产物写标识。**失败就抛 —— 由调用方决定它意味着什么。**

    ─────────────────────────────────────────────────────────
    【为什么这里不「尽力而为」，而是让异常传出去】

    因为「写不上标识」在合规上等于「这份产物不该发布」。调用方
    （`transfer.transfer_artifact`）把它变成一次**可重试的转存失败**：
    重试几次，还不行就判任务失败并**全额退款** —— 用户损失的是时间，
    不是钱，而平台不会发出一份没有标识的 AI 内容。

    反过来的做法（记一条 warning，照常发布）看起来更「稳」，
    但它把一次**法律义务上的失败**降级成了一条日志。日志没人看。

    【`marking_enabled=False` 是唯一的例外通道】见 `config.py`
    那段：它存在的理由是「这台环境的元数据工具坏了，先让交付继续」，
    而打开它必须在 `git diff` 里看得见。

    ⚠️ 开关就设在这个函数里（而不是各调用方自己判）。因为「忘了判」
    的后果是**关掉开关以后仍然在标**，或者反过来 —— 两种都不会报错。
    收在一个咽喉点上，就没有第二个地方需要记得做对。
    ─────────────────────────────────────────────────────────
    """
    if not get_settings().marking_enabled:
        # 【为什么要留一条 warning】关掉标识是**合规上的例外**，
        # 不该安静地发生。运维在日志里翻得到「这台机器不发标识」，
        # 而不是等出事之后去读代码才发现有人关过。
        logger.warning(
            "隐式标识被 MARKING_ENABLED=false 关掉了 —— 本次产物**不带 AI 生成标识**"
            "（task=%s kind=%s）。这应当只在一台元数据工具坏了的机器上临时打开。",
            payload.task_id,
            payload.kind,
        )
        return

    text = marker_text(payload)
    if mime.startswith("image/"):
        write_image_marker(
            path,
            # ⚠️ 两个字段**故意不同**：`description` 必须纯 ASCII
            #（EXIF 的 ASCII 型标签，见 `marker_text_ascii`），
            # 中文那版进 `user_comment`。**别把这里统一成 `text`** ——
            # 那会让 Pillow 把中文静默换成 `?`，而写入仍然"成功"。
            description=marker_text_ascii(payload),
            user_comment=text,
            xmp=xmp_packet(payload),
        )
        return

    if mime == "video/mp4":
        # 【为什么要绕一个中间文件】`remux_with_tags` 是从 source 读、
        # 往 dest 写的，而这里是**就地**改。让 ffmpeg 直接读写同一个
        # 文件的话，它会在开始读之前就把目标截断 —— 结果是一段 0 字节
        # 的「视频」，而 ffmpeg 的退出码是 0。
        tmp = path.with_name(f".mark-{path.name}")
        tmp.unlink(missing_ok=True)
        try:
            remux_with_tags(
                path,
                tmp,
                {key: text for key in _VIDEO_TAG_KEYS},
            )
            if tmp.stat().st_size == 0:
                raise TranscodeError("ffmpeg 写元数据之后文件是空的")
            path.unlink()
            tmp.replace(path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return

    # mkv / ts / 其它容器：见下。
    raise TranscodeError(f"不支持给 {mime} 写隐式标识")


__all__ = [
    "AI_LABEL",
    "AI_LABEL_EN",
    "MarkerPayload",
    "apply_marker",
    "marker_text",
    "marker_text_ascii",
    "payload_for",
    "xmp_packet",
]
