#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# 一键打包：把前端打成一个 zip，里面装着「网站文件 + 部署脚本 + 打包信息」
#
# 【为什么不是一个「网站文件的 zip」】
# 因为部署时最容易翻车的两件事恰好都能被这个形状消掉：
#   · 解压出来多一层 `web/` 目录 → 白屏。现在由 deploy-web.sh 自动认路，
#     它只认「哪一层有 index.html」，不猜目录结构。
#   · 忘了把部署脚本传上去 → 上服务器才发现。现在它就在包里。
#
# 【为什么包里的说明文件叫 BUILD-INFO.txt 而不是中文名】
# 因为 zip 的条目名编码取决于打包器（Windows PowerShell 的 Compress-Archive
# 在中文系统上写的是 GBK），Linux 的 unzip 会解出乱码文件名。
# 包内文件名一律用 ASCII。
#
# 用法：
#   bash scripts/build-web.sh                    # 演示版（Mock），最常用
#   bash scripts/build-web.sh --skip-build       # 复用现有 build/web，只打包
#   bash scripts/build-web.sh --base-href /app/  # 部署在子路径
#   bash scripts/build-web.sh --mode real --api-base-url https://api.example.com
# ─────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE=mock
API_BASE_URL=""
BASE_HREF=""
OUT_DIR="$ROOT/dist"
SKIP_BUILD=0
NO_ZIP=0

die() { echo "❌ $*" >&2; exit 1; }
step() { echo; echo "── $*"; }

usage() {
  sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)         MODE="${2:-}"; shift 2 ;;
    --api-base-url) API_BASE_URL="${2:-}"; shift 2 ;;
    --base-href)    BASE_HREF="${2:-}"; shift 2 ;;
    --out)          OUT_DIR="${2:-}"; shift 2 ;;
    --skip-build)   SKIP_BUILD=1; shift ;;
    --no-zip)       NO_ZIP=1; shift ;;
    -h|--help)      usage ;;
    *) die "不认识的参数：$1（用 --help 看用法）" ;;
  esac
done

case "$MODE" in
  mock|real) ;;
  *) die "--mode 只能是 mock 或 real，收到：$MODE" ;;
esac
if [[ "$MODE" == real && -z "$API_BASE_URL" ]]; then
  die "--mode real 必须同时给 --api-base-url（App 在后端没配好时会退化成连不上的请求）"
fi
if [[ -n "$BASE_HREF" && "$BASE_HREF" != /* ]]; then
  die "--base-href 必须以 / 开头（例如 /app/）"
fi

# ── 1. 构建 ──────────────────────────────────────────────
if [[ "$SKIP_BUILD" -eq 1 ]]; then
  step "跳过构建，复用现有 build/web"
else
  step "构建 Web（模式：$MODE）"
  build_args=(build web --release)
  [[ -n "$BASE_HREF" ]] && build_args+=(--base-href "$BASE_HREF")
  # 【两个模式都显式传，谁都不靠默认值】2026-10-17 起 `AppConfig.forApp()`
  # 的 useMock 默认是 **false**（真后端）—— 于是 mock 这一支如果什么都不传，
  # 打出来的会是一个**真后端包**，而 zip 的名字和 BUILD-INFO 都写着 Mock。
  # 那种包到了客户手上就是「演示时连不上」，且没人会想到是打包参数的问题。
  # 反过来也一样：真后端那一支传全两个，env.dart 的默认值再变都不会漂。
  if [[ "$MODE" == real ]]; then
    build_args+=(--dart-define=USE_MOCK=false "--dart-define=API_BASE_URL=$API_BASE_URL")
  else
    build_args+=(--dart-define=USE_MOCK=true)
  fi
  echo "flutter ${build_args[*]}"
  flutter "${build_args[@]}" || die "flutter build web 失败，先把它修好再打包"
fi

[[ -f build/web/index.html ]] || die "build/web/index.html 不存在 —— 先跑一次 flutter build web"

# ── 2. 体检：少一个目录就是白屏 ───────────────────────────
step "检查构建产物"
missing=()
for f in index.html main.dart.js flutter_bootstrap.js assets canvaskit; do
  [[ -e "build/web/$f" ]] || missing+=("$f")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  die "build/web 里缺：${missing[*]} —— 传上去就是白屏，先别部署"
fi
# 【为什么这两样只警告不拦】它们不影响能不能跑起来，只是少了 PWA 清单和版本号，
# 而不同 Flutter 版本对 version.json 的处理有过变化 —— 不该因此挡住一次正常部署。
for f in version.json manifest.json; do
  [[ -e "build/web/$f" ]] || echo "   ⚠️  没有 build/web/$f（不影响运行）"
done
echo "   ✅ index.html / main.dart.js / flutter_bootstrap.js / assets / canvaskit 都在"

# ── 3. 组装 ──────────────────────────────────────────────
step "组装部署包"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

mkdir -p "$staging/web"
cp -r build/web/. "$staging/web/"
cp scripts/deploy-web.sh "$staging/deploy-web.sh"
chmod +x "$staging/deploy-web.sh"

BUILT_AT="$(date '+%Y-%m-%d %H:%M:%S %z')"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo '(不是 git 仓库)')"
if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then DIRTY="是"; else DIRTY="否"; fi
MAIN_SHA="$(sha256sum build/web/main.dart.js | cut -d' ' -f1)"
FLUTTER_VER="$(flutter --version 2>/dev/null | head -1 | sed 's/^Flutter //')"

cat > "$staging/BUILD-INFO.txt" <<EOF
打包时间 : $BUILT_AT
git      : $COMMIT  (工作区有未提交改动: $DIRTY)
模式     : $MODE$([[ "$MODE" == mock ]] && echo '  ← 演示版：默认走 Mock，数据存在浏览器内存里，刷新页面会掉登录')
后端地址 : ${API_BASE_URL:-（Mock，不连后端）}
base href: ${BASE_HREF:-/}
Flutter  : $FLUTTER_VER
main.dart.js sha256:
$MAIN_SHA

【上传后怎么核对包没坏】在服务器上跑：
  sha256sum /path/to/web/main.dart.js
和上面那串比，一样就说明文件完整传上去了。
EOF

mkdir -p "$OUT_DIR"
STAMP="$(date '+%Y%m%d-%H%M')"
ZIP="$OUT_DIR/aivideo-web-$MODE-$STAMP.zip"

if [[ "$NO_ZIP" -eq 1 ]]; then
  step "--no-zip：只构建，不打包"
  echo "网站文件在 build/web/，本次没有生成 zip。"
  exit 0
fi

# 【为什么要写三种打包器】这台 Windows 上没有 zip 命令，但自带 bsdtar
# （C:\Windows\System32\tar.exe，支持 -a 按后缀决定格式）；再兜底到 PowerShell。
if command -v zip >/dev/null 2>&1; then
  (cd "$staging" && zip -qr "$ZIP" .)
elif [[ -x /c/Windows/System32/tar.exe ]]; then
  ZIP_WIN="$(cygpath -w "$ZIP" 2>/dev/null || echo "$ZIP")"
  STAGE_WIN="$(cygpath -w "$staging" 2>/dev/null || echo "$staging")"
  /c/Windows/System32/tar.exe -a -c -f "$ZIP_WIN" -C "$STAGE_WIN" . || die "打包失败（bsdtar）"
elif command -v powershell >/dev/null 2>&1; then
  ZIP_WIN="$(cygpath -w "$ZIP" 2>/dev/null || echo "$ZIP")"
  STAGE_WIN="$(cygpath -w "$staging" 2>/dev/null || echo "$staging")"
  powershell -NoProfile -Command \
    "Compress-Archive -Path '$STAGE_WIN\\*' -DestinationPath '$ZIP_WIN' -Force" \
    || die "打包失败（Compress-Archive）"
else
  die "找不到任何打包器（zip / bsdtar / powershell 都没有）"
fi

SIZE="$(du -h "$ZIP" | cut -f1)"
echo "   ✅ $ZIP  ($SIZE)"

# 【为什么要转成 Windows 路径再打印】这个脚本是在 Git Bash 里跑的，
# 但它打印的路径要被人拿去「宝塔文件管理 → 上传」或者「scp 到服务器」，
# 而 `/g/AIVideo/...` 这两种场合都不认。给人看的一律用 G:\AIVideo\... 形式。
ZIP_SHOWN="$ZIP"
if command -v cygpath >/dev/null 2>&1; then
  ZIP_SHOWN="$(cygpath -w "$ZIP" 2>/dev/null || echo "$ZIP")"
fi

# ── 4. 下一步 ────────────────────────────────────────────
cat <<EOF

────────────────────────────────────────────────
包好了。下一步**二选一**，都只有两步：

【A. 用宝塔面板上传（不碰命令行）】
  1. 宝塔 → 文件 → 进 /root → 上传这个文件：
       $ZIP_SHOWN
  2. 宝塔 → 终端，粘这三行：
       cd /root
       unzip -o $(basename "$ZIP") -d aivideo-deploy
       bash aivideo-deploy/deploy-web.sh

【B. 本机直接 scp（服务器开了 22 端口的话更省事）】
  scp "$ZIP" root@<你的服务器IP>:/root/
  （这里用 /g/... 的形式是因为你就在 Git Bash 里跑；换成 G:\... 反而会被
    scp 当成 host:path 去解析）
  然后 SSH 上去跑同样的三行。

部署脚本会自己找站点根目录、校验文件、修权限，并把你该开的 SSL 说清楚。
先看看它打算干什么（不落地）：
  bash aivideo-deploy/deploy-web.sh --dry-run
────────────────────────────────────────────────
EOF
