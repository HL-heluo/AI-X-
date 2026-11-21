#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# 后端一键部署（Linux + systemd；宝塔环境同样适用）
#
# 这个脚本做的是**后端**那半边：venv / 依赖 / 迁移 / systemd / nginx 反代。
# 前端静态站仍用 flutter_application_1/scripts/deploy-web.sh。
#
# 用法（在服务器上、仓库根目录执行）：
#   sudo bash scripts/deploy-backend.sh \
#       --public-url https://fabric.example.com \
#       --nginx-conf /www/server/panel/vhost/nginx/fabric.example.com.conf
#
#   sudo bash scripts/deploy-backend.sh --dry-run     # 只看要做什么，不落地
#   sudo bash scripts/deploy-backend.sh --skip-nginx  # 不碰 nginx（手工配）
#   sudo bash scripts/deploy-backend.sh --skip-deps   # 复用已装好的 venv
#
# 反复执行是安全的：每一步都先看状态再动手（幂等）。
#
# ── 它不会做的事（故意的）────────────────────────────────
#   · 不替你填 provider 密钥 —— .env 里没有就停，只报「缺哪几个键」
#   · 不种邀请码 —— 用 scripts/create_invite.py（线上库不种码=没人能注册）
#   · 不改对象存储的 CORS —— 那在云控制台，见脚本末尾的提示
#   · 不建站点、不签证书 —— 宝塔面板上点一次
#
# ── 两个硬约束（写死在脚本里，别绕过去）──────────────────
#   1. uvicorn **只能单进程**：后台 worker 是进程内线程，claim 是
#      「先查再改」，多 worker 会把同一任务问两次、甚至提交两次。
#   2. TEST_MODE 必须关：它挂的 /__test/* 能凭空发积分。
# ─────────────────────────────────────────────────────────
set -euo pipefail

# 服务器 locale 可能是 C/POSIX；Python 打中文日志会炸在编码上
export PYTHONIOENCODING=utf-8

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP_DIR="$ROOT"
DATA_DIR="/opt/aivideo/data"
SVC_USER="aivideo"
PORT=8000
PUBLIC_URL=""
NGINX_CONF=""
SKIP_NGINX=0
SKIP_DEPS=0
DRY_RUN=0
ENV_FILE="$APP_DIR/.env"
UNIT_PATH="/etc/systemd/system/aivideo-backend.service"
# 片段路径在确定 NGINX_CONF 之后再定（见 §8）。宝塔机器上**没有 /etc/nginx**，
# 写死这个绝对路径会得到 `No such file or directory`，而且是在 nginx 那一步
# 才炸——前面所有步骤都已经生效，很容易被误读成「后端有问题」。
SNIPPET_PATH=""

die()  { echo "❌ $*" >&2; exit 1; }
warn() { echo "⚠️  $*" >&2; }
step() { echo; echo "── $*"; }

usage() {
  sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --public-url) PUBLIC_URL="${2:-}"; shift 2 ;;
    --data-dir)   DATA_DIR="${2:-}"; shift 2 ;;
    --app-dir)    APP_DIR="${2:-}"; shift 2 ;;
    --user)       SVC_USER="${2:-}"; shift 2 ;;
    --port)       PORT="${2:-}"; shift 2 ;;
    --nginx-conf) NGINX_CONF="${2:-}"; shift 2 ;;
    --skip-nginx) SKIP_NGINX=1; shift ;;
    --skip-deps)  SKIP_DEPS=1; shift ;;
    --dry-run)    DRY_RUN=1; shift ;;
    -h|--help)    usage ;;
    *) die "不认识的参数：$1（用 --help 看用法）" ;;
  esac
done

# 路径类参数统一成绝对路径
APP_DIR="$(cd "$APP_DIR" 2>/dev/null && pwd)" || die "--app-dir 不存在：$APP_DIR"
ENV_FILE="$APP_DIR/.env"
# alembic.ini / scripts/check_deps.py / pydantic 的 .env 都按仓库根解析
cd "$APP_DIR"

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "   [dry-run] $*"
  else
    "$@"
  fi
}

write_file() {
  local path="$1"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "   [dry-run] 写入 $path"
    cat > /dev/null
  else
    cat > "$path"
  fi
}

# 以服务用户身份执行（alembic / 闸门脚本都要；root 跑出来的文件属主不对）
run_as() {
  local u="$1"; shift
  # 【为什么显式给 HOME】runuser 不带 -l 时会保留调用者的 HOME（这里是
  # /root），而服务用户通常进不去 /root。pip / alembic 都会往 ~/.cache 写，
  # 于是报一个和真正病因无关的 Permission denied。
  if command -v runuser >/dev/null 2>&1; then
    run runuser -u "$u" -- env HOME="$APP_DIR" PYTHONIOENCODING=utf-8 "$@"
  else
    run su -s /bin/sh -c "cd $(printf '%q' "$APP_DIR") && HOME=$(printf '%q' "$APP_DIR") PYTHONIOENCODING=utf-8 $(printf '%q ' "$@")" "$u"
  fi
}

reload_nginx() {
  # 宝塔不保证 nginx 是 systemd 单元（有的机器只有 /etc/init.d/nginx），
  # 所以三条路都试，别在最后一步因为「找不到服务」前功尽弃。
  systemctl reload nginx 2>/dev/null && return 0
  if [[ -x /etc/init.d/nginx ]]; then
    /etc/init.d/nginx reload 2>/dev/null && return 0
  fi
  "$NGINX_BIN" -s reload
}

# 从 .env 取一个键（后写的覆盖先写的；去掉首尾空白与引号）
get_env() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || { echo ""; return; }
  grep -E "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE" 2>/dev/null \
    | tail -1 \
    | cut -d= -f2- \
    | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' \
    | sed -E 's/^"(.*)"$/\1/; s/^'\''(.*)'\''$/\1/' || true
}

# ── 0. 前置检查 ──────────────────────────────────────────
step "前置检查"

[[ "$(uname -s)" == "Linux" ]] || die "这个脚本只跑 Linux。Windows 上开发请用 uvicorn --reload。"

if [[ "$(id -u)" -ne 0 ]]; then
  die "需要 root（要建系统用户、装 systemd unit、改 nginx）。用 sudo 执行。"
fi

PYTHON=""
for cand in python3.12 python3.13 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver="$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0.0)"
    if [[ "$ver" == "3.12" || "$ver" == "3.13" ]]; then PYTHON="$cand"; break; fi
  fi
done
[[ -n "$PYTHON" ]] || die "找不到 Python 3.12/3.13。Ubuntu: apt install python3.12 python3.12-venv"

for bin in ffmpeg ffprobe; do
  command -v "$bin" >/dev/null 2>&1 \
    || die "找不到 $bin —— 它是硬依赖（抽帧 / 合规标识）。Ubuntu: apt install ffmpeg"
done

command -v systemctl >/dev/null 2>&1 || die "没有 systemd，这个脚本不适用。"

# 宝塔的 nginx 通常不在 PATH 里（/www/server/nginx/sbin/nginx）。
NGINX_BIN="$(command -v nginx 2>/dev/null || true)"
if [[ -z "$NGINX_BIN" && -x /www/server/nginx/sbin/nginx ]]; then
  NGINX_BIN=/www/server/nginx/sbin/nginx
fi
if [[ "$SKIP_NGINX" -eq 0 && -z "$NGINX_BIN" ]]; then
  die "找不到 nginx。若你打算手工配反代，加 --skip-nginx。"
fi

# PUBLIC_URL：--public-url > .env 的 PUBLIC_BASE_URL > 报错
if [[ -z "$PUBLIC_URL" ]]; then
  PUBLIC_URL="$(get_env PUBLIC_BASE_URL)"
fi
if [[ -z "$PUBLIC_URL" || "$PUBLIC_URL" == http://127.0.0.1* ]]; then
  die "必须给 --public-url（例如 https://fabric.example.com）。
   后端要拿它拼对外地址；写成 127.0.0.1 的话，用户拿到的图全是裂的。"
fi
PUBLIC_HOST="${PUBLIC_URL#http://}"; PUBLIC_HOST="${PUBLIC_HOST#https://}"
PUBLIC_HOST="${PUBLIC_HOST%%/*}"

if [[ "$PUBLIC_URL" != https://* ]]; then
  warn "PUBLIC_URL 不是 https —— 前端是 https 页面，调 http 的 /media 会被浏览器
       当成混合内容拦掉。只有「纯 OSS 产物、完全不用 /media」时才勉强可以。"
fi

echo "   仓库      : $APP_DIR"
echo "   数据目录  : $DATA_DIR"
echo "   服务用户  : $SVC_USER"
echo "   监听      : 127.0.0.1:$PORT（只给 nginx 看）"
echo "   对外地址  : $PUBLIC_URL"
echo "   Python    : $PYTHON ($("$PYTHON" -V 2>&1))"

# ── 1. 服务用户与目录 ────────────────────────────────────
step "服务用户与目录"

if ! getent group "$SVC_USER" >/dev/null 2>&1; then
  run groupadd --system "$SVC_USER"
fi
if ! id "$SVC_USER" >/dev/null 2>&1; then
  run useradd --system --gid "$SVC_USER" --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SVC_USER"
  echo "   已创建系统用户 $SVC_USER"
else
  echo "   用户 $SVC_USER 已存在"
  # 代码搬过目录时（/root → /opt），家目录可能指向一个已经不存在的路径；
  # systemd 会把 HOME 设成它，某些库会因此写不了缓存。
  cur_home="$(getent passwd "$SVC_USER" | cut -d: -f6 || true)"
  if [[ -n "$cur_home" && ! -d "$cur_home" ]]; then
    run usermod -d "$APP_DIR" "$SVC_USER"
    echo "   家目录 $cur_home 已不存在，改为 $APP_DIR"
  fi
fi

run mkdir -p "$DATA_DIR/media" "$DATA_DIR/provider_spool"
run chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR"
run chmod 750 "$DATA_DIR"

# ── 2. .env ──────────────────────────────────────────────
step "检查 .env"

if [[ ! -f "$ENV_FILE" ]]; then
  warn ".env 不存在 —— 生成一个模板，填完再跑一次这个脚本。"

  secret="$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  {
    echo "# 由 deploy-backend.sh 生成于 $(date '+%Y-%m-%d %H:%M:%S')"
    echo "# ⚠️ 这个文件含密钥：不要提交、不要发给别人。权限 600。"
    echo
    echo "APP_ENV=prod"
    echo "TEST_MODE=0"
    echo "JWT_SECRET=$secret"
    echo
    echo "# SQLite 放在数据目录里（备份=拷这个文件，记得连 -wal/-shm 一起）"
    echo "DATABASE_URL=sqlite:///$DATA_DIR/aivideo.db"
    echo "PUBLIC_BASE_URL=$PUBLIC_URL"
    echo "MEDIA_ROOT=$DATA_DIR/media"
    echo "PROVIDER_SPOOL_ROOT=$DATA_DIR/provider_spool"
    echo
    echo "# ── 下面这些必须自己填（缺了服务起不来，守卫在 app/config.py）──"
    echo "PROVIDER=jimeng"
    echo "VIDEO_PROVIDER=minimax"
    echo "JIMENG_AK="
    echo "JIMENG_SK="
    echo "JIMENG_REQ_KEY_IMAGE="
    echo "JIMENG_REQ_KEY_VIDEO="
    echo "MINIMAX_API_KEY="
    echo "STORAGE=oss"
    echo "S3_ENDPOINT_URL="
    echo "S3_BUCKET="
    echo "S3_REGION="
    echo "S3_ACCESS_KEY_ID="
    echo "S3_SECRET_ACCESS_KEY="
    echo "S3_PUBLIC_BASE_URL="
    echo "# TOS/OSS 用 0（本仓库现有 TOS 配置实测可用）；MinIO 等才需要 1"
    echo "S3_FORCE_PATH_STYLE=0"
  } | write_file "$ENV_FILE"

  if [[ "$DRY_RUN" -eq 0 ]]; then
    chown "$SVC_USER:$SVC_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  fi
  echo
  echo "   模板已写入 $ENV_FILE"
  echo "   把 provider / 存储的密钥填进去后，重新执行本脚本。"
  exit 0
fi

run chown "$SVC_USER:$SVC_USER" "$ENV_FILE"
run chmod 600 "$ENV_FILE"

# ── 3. .env 的生产值校验 ─────────────────────────────────
step "校验 .env 的生产值"

problem=0
app_env="$(get_env APP_ENV)"
jwt="$(get_env JWT_SECRET)"
test_mode="$(get_env TEST_MODE)"
db_url="$(get_env DATABASE_URL)"
pub="$(get_env PUBLIC_BASE_URL)"

[[ "$app_env" == "prod" ]] \
  || { warn "APP_ENV=$app_env（生产应为 prod，否则错误响应会带堆栈）"; problem=1; }

[[ ${#jwt} -ge 32 ]] \
  || { warn "JWT_SECRET 为空或短于 32 字符（app/config.py 的守卫会拦，但先在这里说清楚）"; problem=1; }

case "$(echo "$test_mode" | tr '[:upper:]' '[:lower:]')" in
  ""|0|false|no) ;;
  *) warn "TEST_MODE=$test_mode —— /__test/* 会挂载，它能凭空发积分。线上必须关。"; problem=1 ;;
esac

if [[ -z "$db_url" ]]; then
  warn "DATABASE_URL 没写 —— 会退化成仓库根目录的 aivideo.db。生产建议写绝对路径：
       DATABASE_URL=sqlite:///$DATA_DIR/aivideo.db"
elif [[ "$db_url" != sqlite:* && "$db_url" != postgresql* ]]; then
  warn "DATABASE_URL 既不是 sqlite 也不是 postgresql：$db_url"; problem=1
fi

if [[ "${pub%/}" != "${PUBLIC_URL%/}" ]]; then
  warn "PUBLIC_BASE_URL=$pub 与 --public-url=$PUBLIC_URL 不一致。
       请把 .env 里的 PUBLIC_BASE_URL 改成 $PUBLIC_URL（否则产物地址可能指向错的地方）。"
  problem=1
fi

# 真 provider 的必填项：这里只做「有没有」，值对不对由 app/config.py 的守卫负责。
provider="$(get_env PROVIDER)"
video_provider="$(get_env VIDEO_PROVIDER)"
storage="$(get_env STORAGE)"
[[ -n "$(get_env VIDEO_PROVIDER)" ]] || video_provider="$provider"

if [[ "$provider" == "jimeng" ]]; then
  for k in JIMENG_AK JIMENG_SK JIMENG_REQ_KEY_IMAGE; do
    [[ -n "$(get_env "$k")" ]] || { warn "图片走即梦，但 $k 是空的"; problem=1; }
  done
fi
if [[ "$video_provider" == "jimeng" ]]; then
  for k in JIMENG_AK JIMENG_SK JIMENG_REQ_KEY_VIDEO; do
    [[ -n "$(get_env "$k")" ]] || { warn "视频走即梦，但 $k 是空的"; problem=1; }
  done
fi
if [[ "$video_provider" == "minimax" ]]; then
  [[ -n "$(get_env MINIMAX_API_KEY)" ]] || { warn "视频走 MiniMax，但 MINIMAX_API_KEY 是空的"; problem=1; }
fi
if [[ "$storage" == "oss" ]]; then
  for k in S3_BUCKET S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY S3_PUBLIC_BASE_URL; do
    [[ -n "$(get_env "$k")" ]] || { warn "STORAGE=oss，但 $k 是空的"; problem=1; }
  done
fi

if [[ "$problem" -eq 1 ]]; then
  die "上面这些先改好（改的是 $ENV_FILE），再跑一次。**不会带着半套配置启动。**"
fi
echo "   ✅ APP_ENV=prod / JWT_SECRET 长度够 / TEST_MODE 关 / provider 与存储配置齐全"

# ── 4. venv 与依赖 ───────────────────────────────────────
step "Python 依赖"

# 【为什么同时检查 pip】Ubuntu/Debian 上没装 python3.12-venv 时，
# `python -m venv` 可能留下一个只有 bin/python、没有 bin/pip 的半截目录。
# 只看 python 的话，下一次运行会「复用」它，然后在 pip install 那一步
# 报一个 `No such file or directory` —— 看起来像脚本坏了，其实是环境缺包。
# venv **不能整体搬目录**：bin/pip 的 shebang 里烧着创建时的绝对路径。
# 搬过之后 `-x` 仍然为真，执行却报 "cannot execute: required file not found"。
if [[ "$DRY_RUN" -eq 0 && -d "$APP_DIR/.venv" && -x "$APP_DIR/.venv/bin/pip" ]] \
   && ! "$APP_DIR/.venv/bin/pip" --version >/dev/null 2>&1; then
  echo "   venv 里的 pip 不能执行（大概率是整体搬过目录），删掉重建"
  rm -rf "$APP_DIR/.venv"
fi

if [[ ! -x "$APP_DIR/.venv/bin/python" || ! -x "$APP_DIR/.venv/bin/pip" ]]; then
  if [[ -d "$APP_DIR/.venv" ]]; then
    echo "   发现不完整的 venv（没有 pip），删掉重建"
    run rm -rf "$APP_DIR/.venv"
  fi
  run "$PYTHON" -m venv "$APP_DIR/.venv"
  echo "   已创建 venv"
else
  echo "   复用已有 venv"
fi

if [[ "$DRY_RUN" -eq 0 && ! -x "$APP_DIR/.venv/bin/pip" ]]; then
  die "venv 建好了却没有 pip —— 系统缺 venv 组件。
   Ubuntu/Debian : apt install -y python3.12-venv
   Alibaba/CentOS: dnf install -y python3.12-pip
   装完重新执行本脚本（它会自己删掉半截 venv 重建）。"
fi

if [[ "$SKIP_DEPS" -eq 0 ]]; then
  run "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
  run "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
  echo "   依赖已安装"
else
  echo "   --skip-deps：跳过 pip install"
fi

# 整个仓库归服务用户：SQLite 默认落在仓库根、media/spool 也在其下，
# 只 chown .venv 的话，迁移和产物写入会以「Permission denied」收场。
run chown -R "$SVC_USER:$SVC_USER" "$APP_DIR"

# ── 5. 依赖闸门 + 数据库迁移 ─────────────────────────────
step "依赖闸门"

# 不是 pip install 的替代：它证明每个依赖「真的能用」（ffmpeg 能跑、
# bcrypt 的 C 扩展能加载……）。和后端 README 的门禁是同一条。
run_as "$SVC_USER" "$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/check_deps.py"

step "数据库迁移"

# 应用启动**不会**自动建表（只有 TEST_MODE 的清库接口会），漏了这步是一片 500。
run_as "$SVC_USER" "$APP_DIR/.venv/bin/python" -m alembic upgrade head

# ── 6. systemd ───────────────────────────────────────────
step "安装 systemd 服务"

# 【为什么不用 EnvironmentFile】.env 里有行内注释和引号，systemd 的解析
# 规则和 pydantic-settings 不一样（行内 `#` 会被当成值的一部分）。
# 让 pydantic 自己读 .env，是唯一一处解析。
write_file "$UNIT_PATH" <<EOF
[Unit]
Description=AIVideo backend (FastAPI + in-process worker)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SVC_USER
Group=$SVC_USER
WorkingDirectory=$APP_DIR
# ⚠️ 单进程是硬约束：后台 worker 是进程内线程，多 worker 会重复提交任务。
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=3
TimeoutStopSec=30
# 日志进 journald：journalctl -u aivideo-backend -f
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

run systemctl daemon-reload
run systemctl enable aivideo-backend >/dev/null
run systemctl restart aivideo-backend
echo "   服务已安装并重启"

# ── 7. 健康检查 ──────────────────────────────────────────
step "健康检查"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "   [dry-run] 跳过"
else
  ok=0
  for _ in $(seq 1 30); do
    if health="$("$APP_DIR/.venv/bin/python" - "$PORT" <<'PY' 2>/dev/null
import json, sys, urllib.request
port = sys.argv[1]
with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
    print(r.read().decode())
PY
    )"; then ok=1; break; fi
    sleep 1
  done

  if [[ "$ok" -ne 1 ]]; then
    echo "   ❌ 30 秒内没起来。看日志："
    echo "      journalctl -u aivideo-backend -n 80 --no-pager"
    exit 1
  fi
  echo "   ✅ /health：$health"
  echo
  echo "   确认 provider 与 video_provider 是你要的那两路（它们可以是两家）。"
fi

# ── 8. nginx 反代 ────────────────────────────────────────
step "nginx 反代（/api → 127.0.0.1:$PORT）"

if [[ "$SKIP_NGINX" -eq 1 ]]; then
  echo "   --skip-nginx：跳过。手工配置时把下面这段放进 443 的 server{} 里："
  echo
  echo "   location /api/ { proxy_pass http://127.0.0.1:$PORT/; }"
  echo
else
  if [[ -z "$NGINX_CONF" ]]; then
    # 自动找：包含 PUBLIC_HOST 的宝塔站点配置
    candidates=()
    while IFS= read -r f; do candidates+=("$f"); done < <(
      grep -Fl -- "$PUBLIC_HOST" /www/server/panel/vhost/nginx/*.conf 2>/dev/null || true
    )
    if [[ ${#candidates[@]} -eq 1 ]]; then
      NGINX_CONF="${candidates[0]}"
      echo "   自动识别站点配置：$NGINX_CONF"
    else
      die "找不到唯一的站点配置（候选 ${#candidates[@]} 个）。
   请显式指定：--nginx-conf /www/server/panel/vhost/nginx/xxx.conf
   或者先手工配好，再用 --skip-nginx。"
    fi
  fi

  [[ -f "$NGINX_CONF" ]] || die "--nginx-conf 不存在：$NGINX_CONF"

  # 【片段放哪儿】不能写死 /etc/nginx：宝塔的 nginx 配置在
  # /www/server/nginx 与 /www/server/panel/vhost/nginx 下，/etc/nginx 根本不存在。
  # 放在站点配置**旁边的 snippets/ 子目录**里，原因有两个：
  #   1. 和站点配置同生共死（备份/迁移站点时一起走）；
  #   2. 宝塔的 nginx.conf 里有 `include .../vhost/nginx/*.conf;`，
  #      直接把片段放在 vhost/nginx/ 下会被当成**另一个站点**在 http 层 include，
  #      而 location 不允许出现在 http 层 —— nginx -t 直接失败。
  #      子目录不在 `*.conf` 这个 glob 的覆盖范围内，所以是安全的。
  SNIPPET_DIR="$(dirname "$NGINX_CONF")/snippets"
  SNIPPET_PATH="$SNIPPET_DIR/aivideo-api.conf"
  [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$SNIPPET_DIR"

  write_file "$SNIPPET_PATH" <<EOF
# 由 aivideo-backend 的 scripts/deploy-backend.sh 生成 / 覆盖。
# 前端与 API 同域：/api/ 反代到本机后端并剥掉前缀。
location = /api { return 301 /api/; }

location /api/ {
    proxy_pass http://127.0.0.1:$PORT/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    # 用户上传参考图的上限是 20MB（app/config.py），网关默认 1MB 会 413。
    client_max_body_size 25m;
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;
}

# STORAGE=local 时产物从这里出；=oss 时用不到，留着不碍事。
location /media/ {
    proxy_pass http://127.0.0.1:$PORT/media/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-Proto \$scheme;
    client_max_body_size 25m;
}
EOF

  echo "   snippet：$SNIPPET_PATH"

  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$APP_DIR/.venv/bin/python" - "$NGINX_CONF" "$SNIPPET_PATH" <<'PY'
"""把 include 行插进 443/ssl 那个 server{} 里（先备份，可重复执行）。

不整文件重写：宝塔会重写站点配置，所以只做一个可识别、可幂等的插入。
"""
import re
import shutil
import sys

conf_path, snippet_path = sys.argv[1], sys.argv[2]
marker = "# >>> aivideo-api >>>"
include_line = f"    include {snippet_path};  {marker}"

with open(conf_path, encoding="utf-8") as f:
    text = f.read()

if marker in text:
    print("   已包含反代 include，跳过修改")
    sys.exit(0)

# 找 server { ... } 块（花括号配对），优先选带 listen ... 443 / ssl 的
def server_blocks(s):
    out = []
    for m in re.finditer(r"\bserver\s*\{", s):
        start = m.end() - 1
        depth = 0
        i = start
        while i < len(s):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append((m.start(), start, i))
                    break
            i += 1
    return out

blocks = server_blocks(text)
if not blocks:
    raise SystemExit("❌ 这个配置文件里找不到 server{}，不敢改。")

def is_ssl(block):
    body = text[block[1]:block[2]]
    # 优先认 `listen ... ssl`；其次才是 listen 里带 443 的（有的宝塔配置
    # 把 ssl 写在 listen 行尾，两种都得认）。
    if re.search(r"listen\s+[^;]*\bssl\b", body):
        return True
    return bool(re.search(r"listen\s+[^;]*\b443\b", body))

chosen = next((b for b in blocks if is_ssl(b)), None)
if chosen is None:
    # 没有 SSL 块时不要往 80 里塞——那会让前端 https 调到 http（混合内容）
    raise SystemExit(
        "❌ 没找到监听 443 的 server{}。先在宝塔给站点开 SSL，再跑本脚本。\n"
        "   只有 80 的话，https 页面调 /api 会被浏览器拦成混合内容。"
    )

shutil.copy2(conf_path, conf_path + ".bak-aivideo")
insert_at = text.rfind("\n", 0, chosen[2]) + 1
new_text = text[:insert_at] + include_line + "\n" + text[insert_at:]
with open(conf_path, "w", encoding="utf-8") as f:
    f.write(new_text)
print("   已插入 include（备份：%s.bak-aivideo）" % conf_path)
PY
  else
    echo "   [dry-run] 跳过 nginx 配置修改"
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "   [dry-run] 跳过 nginx -t 与 reload"
  elif "$NGINX_BIN" -t; then
    reload_nginx
    echo "   ✅ nginx 配置测试通过并已 reload"
  else
    warn "nginx -t 失败，正在还原备份……"
    if [[ -f "$NGINX_CONF.bak-aivideo" ]]; then
      cp -a "$NGINX_CONF.bak-aivideo" "$NGINX_CONF"
    else
      # 没有备份可还原时，至少把刚插进去的那行删掉，别留个半坏配置。
      sed -i '/# >>> aivideo-api >>>/d' "$NGINX_CONF"
    fi
    "$NGINX_BIN" -t && reload_nginx
    die "已还原。请检查 $SNIPPET_PATH 与站点配置的兼容性。"
  fi
fi

# ── 9. 下一步 ────────────────────────────────────────────
cat <<EOF

────────────────────────────────────────────────
后端起来了。还剩三件**脚本不能替你点**的事：

1) 种邀请码（不种的话线上一个用户都注册不了）
     cd $APP_DIR
     sudo -u $SVC_USER .venv/bin/python scripts/create_invite.py \\
         --code AIV-2026-01 --uses 20 --note "内测第一批"

2) 对象存储的 CORS（只有浏览器看图会踩，curl 看不出来）
   源站：https://$PUBLIC_HOST
   把这条 origin 加进 TOS/OSS 桶的 CORS 规则，否则作品页只显示占位图。

3) 前端用真后端模式打包（地址必须同域）
     cd ../flutter_application_1
     bash scripts/build-web.sh --mode real --api-base-url $PUBLIC_URL/api

日常看日志：
     journalctl -u aivideo-backend -f
改完代码发版：
     git pull && sudo bash scripts/deploy-backend.sh --public-url $PUBLIC_URL --skip-nginx
────────────────────────────────────────────────
EOF
