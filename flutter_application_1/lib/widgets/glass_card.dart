import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// App 各页面共用的卡片表面。
class GlassCard extends StatelessWidget {
  const GlassCard({
    super.key,
    required this.child,
    this.padding,
    this.margin,
    this.radius = AppRadius.card,
    this.color = AppGlass.normal,
    this.border,
    this.boxShadow,
  });

  final Widget child;
  final EdgeInsetsGeometry? padding;
  final EdgeInsetsGeometry? margin;
  final double radius;
  final Color color;
  final BoxBorder? border;
  final List<BoxShadow>? boxShadow;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: margin,
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(radius),
        border: border ?? Border.all(color: AppGlass.border),
        boxShadow:
            boxShadow ??
            const [
              BoxShadow(
                color: Color(0x0C22594A),
                blurRadius: 20,
                offset: Offset(0, 6),
              ),
            ],
      ),
      clipBehavior: Clip.antiAlias,
      padding: padding,
      child: child,
    );
  }
}
