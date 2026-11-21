import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// 阶段 0 的临时占位内容
///
/// 【为什么要做这个组件】
/// 4 个页面现在都还没内容。与其复制 4 遍一样的「施工中」界面，
/// 不如抽成一个组件，每个页面传不同的文字进去。
///
/// 【前端类比】这就是你的 `<EmptyState title="..." subtitle="..." />` 公共组件。
///
/// 阶段 1 会把它逐个替换成原型里的真页面 —— 到时候把这个文件删掉就行，
/// 所以现在别往里面堆任何业务逻辑。
class PlaceholderBody extends StatelessWidget {
  const PlaceholderBody({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    // 从全局主题里取文字样式，而不是在这里写死字号颜色。
    // 这样以后改主题，这里会自动跟着变。
    final textTheme = Theme.of(context).textTheme;

    return Center(
      child: Padding(
        // 左右留 40，避免长文案贴着屏幕边
        padding: const EdgeInsets.symmetric(horizontal: 40),
        child: Column(
          // min：让 Column 只占内容需要的高度，而不是撑满整屏。
          // 因为外层已经用 Center 居中了，撑满的话 Column 里的
          // mainAxisAlignment 才有意义；min 更符合这里「一小坨居中」的意图。
          mainAxisSize: MainAxisSize.min,
          children: [
            // 圆形浅绿底 + 图标
            Container(
              width: 72,
              height: 72,
              decoration: const BoxDecoration(
                color: AppColors.sageTint,
                shape: BoxShape.circle,
              ),
              child: Icon(icon, size: 32, color: AppColors.sage),
            ),
            const SizedBox(height: 20),
            Text(title, style: textTheme.headlineSmall),
            const SizedBox(height: 8),
            Text(
              subtitle,
              textAlign: TextAlign.center,
              style: textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}
