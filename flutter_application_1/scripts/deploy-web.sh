#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# 一键部署：把打包好的网站文件铺到宝塔站点目录里
#
# 【这个脚本想消掉的三件事】
#   1. 「解压多了一层 web/ → 白屏」 —— 它不猜目录结构，只找哪一层有 index.html；
#   2. 「传漏了 canvaskit/ → 白屏」   —— 铺之前先体检，缺文件就直接停，不做半成品部署；
#   3. 「http 上登录转圈查不出来」     —— 结尾把 https 这件事按面板路径说清楚。
#
# 它**不会**替你做的事（都要在宝塔面板上点，脚本碰不到）：
#   · 建站点、放行端口、签发证书。见仓库根的《部署说明.md》。
#
# 用法（在服务器上，宝塔 → 终端里跑）：
#   bash deploy-web.sh --dry-run              # 先看它打算干什么，不落地
#   bash deploy-web.sh                        # 自动找站点根目录
#   bash deploy-web.sh --site-root /www/wwwroot/xxx
#   bash deploy-web.sh --patch-nginx          # 顺手加「版本入口不缓存」的规则
#   bash deploy-web.sh --zip /root/xxx.zip    # 直接从 zip 读（不改当前目录）
# ─────────────────────────────────────────────────────────
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ZIP=""
FROM=""
SITE_ROOT=""
PATCH_NGINX=0
DRY_RUN=0

die()  { echo "❌ $*" >&2; exit 1; }
warn() { echo "⚠️  $*"; }
step() { echo; echo "── $*"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --zip)         ZIP="${2:-}"; shift 2 ;;
    --from)        FROM="${2:-}"; shift 2 ;;
    --site-root)   SITE_ROOT="${2:-}"; shift 2 ;;
    --patch-nginx) PATCH_NGINX=1; shift ;;
    --dry-run)     DRY_RUN=1; shift ;;
    -h|--help)     sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "不认识的参数：$1（用 --help 看用法）" ;;
  esac
done

[[ "$DRY_RUN" -eq 1 ]] && echo "🔍 dry-run：只做检查和打印，不写任何文件。"

# ── 1. 找到「网站文件在哪一层」 ───────────────────────────
step "定位网站文件"
TMP_EXTRACT=""
cleanup() { [[ -n "$TMP_EXTRACT" ]] && rm -rf "$TMP_EXTRACT"; }
trap cleanup EXIT

find_payload() {  # $1=起点目录 → 打印「看起来就是 Flutter web 产物」的那一层
  local hit dir
  # 【为什么不能只认 index.html】因为它太松了：服务器上任何一份说明页、
  # 另一个站点、甚至宝塔自己的默认首页都可能有一个 index.html，
  # 脚本就会把那个无关目录当成产物，然后在体检那步报「缺 canvaskit/」——
  # 看起来像包坏了，其实是找错了地方（这一步是真机上踩到的：
  # 当前目录的兜底把 /tmp 下一个残留测试目录吞了）。
  # Flutter 的 Web 产物一定同时有 flutter_bootstrap.js，用这个来认。
  hit="$(find "$1" -maxdepth 3 -name flutter_bootstrap.js -print -quit 2>/dev/null || true)"
  if [[ -z "$hit" ]]; then
    hit="$(find "$1" -maxdepth 3 -name main.dart.js -print -quit 2>/dev/null || true)"
  fi
  [[ -n "$hit" ]] || return 0
  dir="$(dirname "$hit")"
  [[ -f "$dir/index.html" ]] && echo "$dir"
  return 0
}

if [[ -n "$FROM" ]]; then
  [[ -f "$FROM/index.html" ]] || die "--from $FROM 里没有 index.html"
  PAYLOAD="$FROM"
elif [[ -n "$ZIP" ]]; then
  [[ -f "$ZIP" ]] || die "找不到 zip：$ZIP"
  TMP_EXTRACT="$(mktemp -d)"
  echo "   解压 $(basename "$ZIP") …"
  if command -v unzip >/dev/null 2>&1; then
    unzip -qo "$ZIP" -d "$TMP_EXTRACT" || die "解压失败"
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
      "$ZIP" "$TMP_EXTRACT" || die "解压失败（python3 zipfile）"
  else
    die "服务器上没有 unzip。装一个：yum install -y unzip（或 apt install -y unzip）"
  fi
  PAYLOAD="$(find_payload "$TMP_EXTRACT")"
  [[ -n "$PAYLOAD" ]] || die "zip 里没有找到 index.html"
else
  # 【为什么按这个顺序找】包里是 web/ + deploy-web.sh，而人常常站在上一级跑脚本，
  # 所以先看脚本旁边的 web/，再看脚本旁边本身，最后才看当前目录。
  for cand in "$SCRIPT_DIR/web" "$SCRIPT_DIR" "$PWD/web" "$PWD"; do
    if [[ -d "$cand" ]]; then
      PAYLOAD="$(find_payload "$cand")"
      [[ -n "$PAYLOAD" ]] && break
    fi
  done
  if [[ -z "${PAYLOAD:-}" ]]; then
    # 站在包里跑脚本时 SCRIPT_DIR 和 PWD 常常是同一个，四个候选会缩成两个 ——
    # 去个重，免得提示里同一路径出现两遍看着像有 bug。
    searched="$(printf '%s\n' "$SCRIPT_DIR/web" "$SCRIPT_DIR" "$PWD/web" "$PWD" \
      | awk '!seen[$0]++' | paste -sd'、' -)"
    # 【为什么要把「找过哪儿」打出来】真机上第一次跑就撞上了这条错误，
    # 而原来的提示只说「没找到」—— 人第一反应是「我明明传上来了」，
    # 却不知道脚本到底在哪儿找、也就没法自查。把清单和一条能直接粘的
    # 命令给出来，这一步就不需要来回问。
    die "没找到网站文件（找过了：$searched）。
   多半是下面两种情况之一：

   ① 包还没解压 —— 先解压再跑：
        unzip -o /root/<包名>.zip -d /root/aivideo-deploy
        bash /root/aivideo-deploy/deploy-web.sh

   ② 解压到别处了 / 不想解压 —— 直接把包指给脚本，它自己会解压：
        bash $SCRIPT_DIR/deploy-web.sh --zip /root/<包名>.zip"
  fi
fi
echo "   ✅ 网站文件：$PAYLOAD"

# ── 2. 体检：缺一个就是白屏 ───────────────────────────────
step "体检（少一个文件，铺上去就是白屏）"
missing=()
for f in index.html main.dart.js flutter_bootstrap.js assets canvaskit; do
  [[ -e "$PAYLOAD/$f" ]] || missing+=("$f")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  die "网站文件里缺：${missing[*]} —— **不要部署**，白屏十有八九就是这么来的。
   重新打包（本机：bash scripts/build-web.sh），或确认 zip 完整传上来了。"
fi
for f in version.json manifest.json; do
  [[ -e "$PAYLOAD/$f" ]] || warn "没有 $f（不影响运行）"
done
echo "   ✅ 必需文件齐全"

BASE_HREF="$(grep -o '<base href="[^"]*"' "$PAYLOAD/index.html" | head -1 | sed 's/.*href="//; s/"//')"
echo "   ℹ️  base href = ${BASE_HREF:-（没读到）}"
if [[ -n "$BASE_HREF" && "$BASE_HREF" != "/" ]]; then
  echo "      这个包是给「子路径部署」打的（/xxx/ 那种）。站点根目录要和它对上。"
fi

# ── 3. 找站点根目录 ──────────────────────────────────────
step "定位宝塔站点目录"
if [[ -z "$SITE_ROOT" ]]; then
  CAND=()
  if [[ -d /www/wwwroot ]]; then
    while IFS= read -r d; do
      [[ -n "$d" ]] && CAND+=("$d")
    done < <(find /www/wwwroot -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort)
  fi
  if [[ ${#CAND[@]} -eq 0 ]]; then
    die "在 /www/wwwroot 下没找到任何站点目录。
   先去宝塔 → 网站 → 添加站点（域名填 你的IP:端口，PHP 选「纯静态」），
   或者手动指定：--site-root /www/wwwroot/你的目录"
  elif [[ ${#CAND[@]} -eq 1 ]]; then
    SITE_ROOT="${CAND[0]}"
    echo "   只有一个候选，就用它：$SITE_ROOT"
  else
    # 【为什么要停下来问】铺错目录的后果是「改了另一个站」，而且不报错。
    with_html=()
    for d in "${CAND[@]}"; do [[ -f "$d/index.html" ]] && with_html+=("$d"); done
    if [[ ${#with_html[@]} -eq 1 ]]; then
      SITE_ROOT="${with_html[0]}"
      echo "   只有 $SITE_ROOT 里已经有 index.html，认为就是它"
    else
      echo "   /www/wwwroot 下有多个站点，我不猜："
      for d in "${CAND[@]}"; do
        printf "     %s%s\n" "$d" "$([[ -f "$d/index.html" ]] && echo '   ← 已经有一个站在这里')"
      done
      die "请明确指定：--site-root /www/wwwroot/<上面的某个目录>"
    fi
  fi
fi

if [[ ! -d "$SITE_ROOT" ]]; then
  echo "   站点目录不存在，将新建：$SITE_ROOT"
  [[ "$DRY_RUN" -eq 0 ]] && mkdir -p "$SITE_ROOT"
fi
if [[ "$DRY_RUN" -eq 0 && ! -w "$SITE_ROOT" ]]; then
  die "$SITE_ROOT 不可写。用 root 跑（宝塔终端默认就是），或 chown 一下。"
fi
echo "   ✅ 站点目录：$SITE_ROOT"

# ── 4. 铺文件 ────────────────────────────────────────────
step "铺文件"
# 【为什么只删这几个名字，而不是清空目录】站点根目录是宝塔管的，里面可能有
# .user.ini、证书验证文件、宝塔自己放的东西。只删「上一版 Flutter 产物」，
# 既能让带 hash 的旧资源不留垃圾，又不会误伤别的。
ARTIFACTS=(index.html main.dart.js flutter.js flutter_bootstrap.js
           flutter_service_worker.js manifest.json version.json favicon.png
           assets canvaskit icons)
for a in "${ARTIFACTS[@]}"; do
  if [[ -e "$SITE_ROOT/$a" ]]; then
    echo "   清理旧文件：$a"
    [[ "$DRY_RUN" -eq 0 ]] && rm -rf "$SITE_ROOT/$a"
  fi
done

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "   （dry-run：把 $PAYLOAD/ 的内容复制到 $SITE_ROOT/）"
else
  cp -a "$PAYLOAD/." "$SITE_ROOT/" || die "复制失败"
  echo "   ✅ 已铺好（$(du -sh "$SITE_ROOT" 2>/dev/null | cut -f1)）"
fi

# ── 5. 权限 ──────────────────────────────────────────────
step "权限"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "   （dry-run：chown www:www + 目录 755 / 文件 644）"
elif [[ "$(id -u)" -eq 0 ]]; then
  OWNER="www"
  id "$OWNER" >/dev/null 2>&1 || OWNER="$(stat -c '%U' "$SITE_ROOT" 2>/dev/null || echo root)"
  chown -R "$OWNER:$OWNER" "$SITE_ROOT" 2>/dev/null || warn "chown 失败，不影响访问"
  find "$SITE_ROOT" -type d -exec chmod 755 {} + 2>/dev/null
  find "$SITE_ROOT" -type f -exec chmod 644 {} + 2>/dev/null
  echo "   ✅ 属主 $OWNER，目录 755 / 文件 644"
else
  warn "不是 root，跳过 chown/chmod（宝塔终端一般是 root；文件读不出来时再回来处理）"
fi

# ── 6. 可选：版本入口不缓存 ──────────────────────────────
if [[ "$PATCH_NGINX" -eq 1 ]]; then
  step "给站点加「版本入口不缓存」规则"
  # 【为什么允许用环境变量覆盖】这是全脚本唯一会改系统配置的地方，
  # 不改就只能在真服务器上试错。留出这两个口子，就能在别处用假 nginx
  # 把「插入位置对不对 / 备份有没有做 / 测不过有没有还原」整条跑一遍。
  # 不设环境变量时行为和在宝塔上完全一样。
  NGINX_BIN="${NGINX_BIN:-/www/server/nginx/sbin/nginx}"
  CONF_DIR="${CONF_DIR:-/www/server/panel/vhost/nginx}"
  if [[ ! -x "$NGINX_BIN" || ! -d "$CONF_DIR" ]]; then
    warn "没找到宝塔的 nginx（$NGINX_BIN / $CONF_DIR），跳过"
  else
    CONF="$(grep -l -- "root[[:space:]]\+$SITE_ROOT" "$CONF_DIR"/*.conf 2>/dev/null | head -1 || true)"
    if [[ -z "$CONF" ]]; then
      warn "没找到 root 指向 $SITE_ROOT 的站点配置，跳过（可以在面板里手动加）"
    elif grep -q 'flutter_service_worker' "$CONF" 2>/dev/null; then
      echo "   已经加过了，跳过"
    elif [[ "$DRY_RUN" -eq 1 ]]; then
      echo "   （dry-run：会往 $(basename "$CONF") 里插两条 location）"
    else
      BAK="$CONF.bak-$(date '+%Y%m%d-%H%M%S')"
      cp "$CONF" "$BAK"
      SNIPPET='    # [deploy-web.sh] 版本入口不缓存，否则用户一直拿到旧版本
    location = /index.html                { add_header Cache-Control "no-cache"; }
    location = /flutter_service_worker.js { add_header Cache-Control "no-cache"; }'
      # 插到 server 块最后一个 } 之前
      awk -v ins="$SNIPPET" '
        { lines[NR]=$0 }
        END {
          last=0
          for(i=NR;i>=1;i--) if (lines[i] ~ /^[[:space:]]*}[[:space:]]*$/) { last=i; break }
          if (last==0) { for(i=1;i<=NR;i++) print lines[i]; exit }
          for(i=1;i<=NR;i++) { if (i==last) print ins; print lines[i] }
        }' "$BAK" > "$CONF"

      if "$NGINX_BIN" -t >/dev/null 2>&1; then
        "$NGINX_BIN" -s reload 2>/dev/null || /etc/init.d/nginx reload >/dev/null 2>&1 || true
        echo "   ✅ 已加并 reload（备份：$BAK）"
        warn "注意：以后在宝塔面板里改这个站点的设置，面板可能重写配置文件、把这两行覆盖掉。改完回来 grep 一下 flutter_service_worker 确认还在。"
      else
        cp "$BAK" "$CONF"
        warn "nginx -t 没过，已还原配置文件。手动加这两行更稳妥。"
      fi
    fi
  fi
fi

# ── 7. 告诉你现在该干什么 ────────────────────────────────
URLS=""
CONF_ALL=/www/server/panel/vhost/nginx
CONF_MATCH="$(grep -l -- "root[[:space:]]\+$SITE_ROOT" "$CONF_ALL"/*.conf 2>/dev/null | head -1 || true)"
if [[ -n "$CONF_MATCH" ]]; then
  NAME="$(grep -o 'server_name[[:space:]]\+[^;]*' "$CONF_MATCH" | head -1 | sed 's/server_name[[:space:]]*//' | awk '{print $1}')"
  PORT="$(grep -o 'listen[[:space:]]\+[0-9]\+' "$CONF_MATCH" | head -1 | grep -o '[0-9]\+')"
  if [[ -n "$NAME" && "$NAME" != "_" ]]; then
    if [[ -n "$PORT" && "$PORT" != "80" && "$PORT" != "443" ]]; then
      URLS="http://$NAME:$PORT/   （https 见下）"
    else
      URLS="http://$NAME/"
    fi
  fi
fi

cat <<EOF

────────────────────────────────────────────────
铺好了。接下来**只剩一件事必须在面板上做，别跳过**：

⚠️ 上 https。否则登录/注册会**一直转圈、没有任何提示** —— 已实测：
   普通 http 的源不是「安全上下文」，浏览器的 WebCrypto 不暴露，
   token 存不进去，而异常又回不到 Dart，所以界面上连报错都没有。
   宝塔 → 网站 → 点这个站点 → 设置 → SSL：
     · 有域名 → Let's Encrypt，一键，然后开「强制 HTTPS」
     · 只有 IP → 选「自签证书」；浏览器第一次会警告，点「继续前往」即可
$( [[ -n "$URLS" ]] && printf '\n现在可以先访问（在 https 之前）：%s\n' "$URLS" )

**如果打开是白屏**，按这个顺序查：
   1. F12 → Console，看 404 的是哪个文件；
   2. 多半是 canvaskit/ 或 assets/ 没铺上去 —— 脚本第 2 步拦过，说明包本身有问题；
   3. 浏览器缓存：强制刷新一次（Ctrl+Shift+R）。

**如果登录转圈**：就是上面那条 https，九成不是 App 的问题。
────────────────────────────────────────────────
EOF
