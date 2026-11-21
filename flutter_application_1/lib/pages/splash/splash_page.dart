import 'package:flutter/material.dart';

import '../../core/constants/app_info.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_background.dart';

/// 启动过渡页
///
/// 【为什么需要它，以及它为什么不是「装饰」】
/// 冷启动时 App 要先做一件事：读出 token 并验证它还有效（见
/// `AuthController.build`）。这件事**必须发一次网络请求**，
/// 所以它一定需要时间。
///
/// 这段时间里如果没有这一页，界面会是什么？`AsyncValue` 还没拿到数据，
/// 只能先画登录页 —— 然后 200ms 后突然跳进主页。用户看到的是
/// **「登录页闪了一下」**，而且如果他手快，可能已经在输密码了，
/// 输入框却被整页换掉。
///
/// 【为什么这里没有转圈图标】见设计约定：设计系统里没有 loading 组件，
/// 而一个转圈在 200ms 内基本看不见、在网络慢时又会被盯很久。
/// 这里只放品牌名 —— 它至少在视觉上像是在「启动」，而不是「卡住了」。
class SplashPage extends StatelessWidget {
  const SplashPage({super.key});

  @override
  Widget build(BuildContext context) {
    return const AppBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        body: Center(
          child: Text(
            AppInfo.appTitle,
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w600,
              // 用炭黑而不是主色鼠尾草绿：启动页只是过渡，
              // 不该抢任何视觉注意力
              color: AppColors.charcoal,
              letterSpacing: 1.2,
            ),
          ),
        ),
      ),
    );
  }
}
