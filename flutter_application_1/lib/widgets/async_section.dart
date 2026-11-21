import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../theme/app_theme.dart';

/// 把一个 [AsyncValue] 渲染成三种样子：**还在拉 / 拉失败 / 拿到了**。
///
/// 【为什么要抽这个组件】「我的」「积分」「作品」「任务详情」
/// 四个屏都要处理这三态，各写一遍的话，四处的**错误文案**和**重试行为**
/// 一定会漂移成四种（有一处忘了给重试按钮是常事）。三态是数据屏的骨架，
/// 骨架只该有一份。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么加载态是静态骨架块，不是转圈】
///
/// 两个理由，第二个是硬约束：
///
/// 1. 设计系统里**没有**整页 loading 组件（见 `splash_page.dart` 里那段），
///    而且转圈在快网下一次都看不见、慢网下又会被一直盯着。
///    用与最终内容同形的灰块占位，加载完成时布局不会「跳一下」。
///
/// 2. **转圈是永不停止的动画**。只要屏幕上有一个 `CircularProgressIndicator`，
///    `tester.pumpAndSettle()` 就会一直等它停下来 —— 也就是等到超时。
///    这个项目里所有 widget 测试都靠 `pumpAndSettle` 推进，
///    所以一个「永远在转」的加载态足以让整个测试套挂掉。
///    静态骨架没有这个问题。
/// ─────────────────────────────────────────────────────────
class AsyncSection<T> extends StatelessWidget {
  const AsyncSection({
    super.key,
    required this.value,
    required this.builder,
    this.onRetry,
    this.loading,
  });

  /// 要渲染的异步值。
  final AsyncValue<T> value;

  /// 拿到数据后怎么画。
  final Widget Function(BuildContext context, T data) builder;

  /// 失败时「重试」按钮要干的事。传 null 就只显示错误文案、不给重试。
  final Future<void> Function()? onRetry;

  /// 自定义骨架。不传则用默认的几行灰条。
  final Widget? loading;

  @override
  Widget build(BuildContext context) {
    return value.when(
      data: (data) => builder(context, data),
      loading: () => loading ?? const SkeletonLines(),
      error: (error, _) => ErrorBox(error: error, onRetry: onRetry),
    );
  }
}

/// 加载中的占位骨架：几根宽度不一的灰条。
///
/// 【为什么宽度故意不一样】等宽的三条看起来像表格的加载态，
/// 参差一点更像「这里将会有文字」。这是纯观感，不承载任何信息。
class SkeletonLines extends StatelessWidget {
  const SkeletonLines({super.key, this.rows = 3});

  final int rows;

  @override
  Widget build(BuildContext context) {
    // 交替的宽度，让骨架看起来像段落而不是表格
    const widths = <double?>[null, 0.78, 0.55, 0.88, 0.4];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < rows; i++) ...[
          if (i > 0) const SizedBox(height: 12),
          FractionallySizedBox(
            alignment: Alignment.centerLeft,
            widthFactor: widths[i % widths.length],
            child: Container(
              height: 14,
              decoration: BoxDecoration(
                color: AppColors.sunken,
                borderRadius: BorderRadius.circular(AppRadius.lg),
              ),
            ),
          ),
        ],
      ],
    );
  }
}

/// 加载失败的提示 + 重试。
///
/// 【为什么用 [AppException.userMessage] 而不是 `'$error'`】
/// 因为能到这里的错误里，用户唯一能看懂的那一类已经被翻译过了
/// （401 →「登录已过期，请重新登录」）。剩下的应该是人话。
/// 直接把异常对象打出来是给开发者看的 —— 而用户看到
/// 「DioException [connection error]」除了截图投诉什么也做不了。
class ErrorBox extends StatelessWidget {
  const ErrorBox({super.key, required this.error, this.onRetry});

  final Object error;
  final Future<void> Function()? onRetry;

  @override
  Widget build(BuildContext context) {
    final message =
        error is AppException ? (error as AppException).userMessage : '出错了，请稍后重试';

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.only(top: 1),
          child: Icon(Icons.error_outline, size: 15, color: AppColors.danger),
        ),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            message,
            style: const TextStyle(
              fontSize: 12.5,
              height: 1.4,
              color: AppColors.danger,
            ),
          ),
        ),
        if (onRetry != null)
          TextButton(
            key: const Key('async.retry'),
            onPressed: () => onRetry!(),
            style: TextButton.styleFrom(
              minimumSize: Size.zero,
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
            child: const Text(
              '重试',
              style: TextStyle(
                fontSize: 12.5,
                fontWeight: FontWeight.w600,
                color: AppColors.sage,
              ),
            ),
          ),
      ],
    );
  }
}
