import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// 圆形头像：取用户名的首字。
///
/// 【为什么是首字而不是一张图】v1 没有头像上传（§11.2 的 `users` 表里没有头像字段），
/// 也没有默认头像图。用用户名首字是**不需要服务端配合**就能显示「这是谁」的做法，
/// 而且换个用户就换个字，比一个所有人共用的默认头像更有辨识度。
///
/// 【前端类比】CSS `.avatar`：浅绿→浅金渐变底 + 白色 2px 描边（像贴纸压在背景上）。
///
/// ─────────────────────────────────────────────────────────
/// 【和 home_header 里那个头像的关系】
/// `pages/create/widgets/home_header.dart` 里有一个私有 `_Avatar`，
/// 长得一样，但**字是写死的 'K'** —— 不管登录的是谁，首页都显示 K。
/// 那是 B1 视觉阶段的占位，不是数据 bug。
///
/// 本轮（B5）**故意没有顺手改它**：改它要么只换个图标（那是一次没经确认的视觉改动，
/// 而首页的视觉是用户已经验收过的），要么就得让 CreatePage 去 watch 用户资料
/// （那是 B6「数据接线」的活）。所以这个组件先在「我的」页用起来，
/// B6 接线时把 home_header 的 `_Avatar` 换成 `UserAvatar(name: ...)` 即可，
/// 那时顺手把写死的 'K' 一起删掉。
/// ─────────────────────────────────────────────────────────
class UserAvatar extends StatelessWidget {
  const UserAvatar({super.key, this.name, this.size = 38});

  /// 用户名。为 null 或空时退化成一个中性的人形图标。
  final String? name;

  /// 直径。
  final double size;

  @override
  Widget build(BuildContext context) {
    final initial = _initialOf(name);

    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [AppColors.sageSoft, AppColors.goldSoft],
        ),
        border: Border.all(color: Colors.white, width: 2),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0F000000),
            blurRadius: 8,
            offset: Offset(0, 2),
          ),
        ],
      ),
      child: initial == null
          // 名字还没拿到时**不编一个字**：随便挑一个字母会让人以为
          // 自己叫那个名字（首页写死 'K' 就是这么来的）。
          ? Icon(Icons.person_outline, size: size * 0.5, color: Colors.white)
          : Text(
              initial,
              style: TextStyle(
                fontSize: size * 0.37,
                fontWeight: FontWeight.w600,
                color: Colors.white,
              ),
            ),
    );
  }

  /// 取首字并大写。
  ///
  /// 【为什么用 runes 而不是 `name[0]`】`String.operator[]` 拿到的
  /// 是**一个 UTF-16 码元**。中文在基本平面里恰好占一个码元、碰巧没问题，
  /// 但 emoji 之类的增补字符占两个 —— 取出来会是个乱码半截。
  /// `runes` 按码点走，不会截断。
  static String? _initialOf(String? name) {
    if (name == null || name.isEmpty) return null;
    return String.fromCharCode(name.runes.first).toUpperCase();
  }
}
