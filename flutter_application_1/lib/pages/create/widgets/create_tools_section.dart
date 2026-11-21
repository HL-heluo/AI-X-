import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../../../widgets/section_title.dart';

/// 一个「创作场景 / 风格」
///
/// 【为什么 label 和 phrase 是两样东西】label 是卡片上那两三个字
/// （「电影感」），phrase 是真正会补进提示词里的那句话
/// （「电影感，浅景深，柔和的光」）。只写 label 的话，
/// 提示词里会出现「一只猫在沙滩上奔跑，电影感」——
/// 而「电影感」这三个字对模型来说几乎没有信息量，
/// 真正起作用的是后面那些具体的视觉描述。
class _SceneSpec {
  const _SceneSpec({
    required this.label,
    required this.icon,
    required this.phrase,
  });

  final String label;
  final IconData icon;
  final String phrase;
}

/// 「创作场景」区
///
/// 【前端类比】对应原型 `home()` 里的「创作工具」段（`.scene-scroll`）。
/// 标题右边一个「查看全部 ›」，下面一排 84×84 的卡片横向滑动。
///
/// 【为什么从「创作工具」改名成「创作场景」】
/// 原型那一排是**电商工具目录**：AI 抠图、模特上身、详情页长图、跨境翻译图……
/// 这些在 v1 里全都不做 —— 判断标准是「这个功能是否服务于『个人创作者做出视频』」。
/// 换成「创作场景 / 风格」后，这里承载的是提示词方向的选择
/// （比如「电影感」「治愈系」「国风」），服务于同一条主线。
///
/// ─────────────────────────────────────────────────────────
/// 【B6：这一排真的能点了】
///
/// 点一下 = 往首页那个提示词框里**追加**一句风格描述。
///
/// 【为什么是「追加」而不是「替换整个提示词」】
/// 因为用户往往已经写好了主体（「一只猫在沙滩上奔跑」），
/// 这时候想的是「再加个电影感」。替换掉就等于把他的输入删了 ——
/// 那是这个界面上最不能接受的一种行为。
/// 追加的规则（判重、用「，」连接、光标放到末尾）在 `CreatePage._appendPhrase`。
///
/// 【为什么没有「查看全部 ›」了】因为**没有第二个页面可去**：
/// 这六个风格就是全部，横向滑一下就能看完。
/// 留一个点了没反应的「查看全部」，等于在标题右边放一个假按钮。
/// （对比：「最近作品」的「全部 ›」是真的有地方去的 —— 作品页。）
///
/// 【样式为什么这么保守】卡片从左到右是「图标底 + 名字」，
/// 没有选中态。它不是多选控件，是**六个一按就走**的快捷按钮 ——
/// 点了之后字会出现在输入框里，那就是反馈本身。
/// 做成「选中高亮」反而会让人以为要选中了再点生成。
/// ─────────────────────────────────────────────────────────
class CreateToolsSection extends StatelessWidget {
  const CreateToolsSection({super.key, required this.onPick});

  /// 点某个场景时回调。参数是**要补进提示词的那句话**，不是卡片上的名字。
  final ValueChanged<String> onPick;

  /// 六个场景 / 风格。
  ///
  /// 【为什么是这六个】挑的是「和『做一段视频』这件事相关」的风格，
  /// 而且每个都能用几句具体的视觉描述说清楚。
  /// 不选「AI 抠图」「模特上身」那类 —— 那是功能，不是风格。
  static const List<_SceneSpec> _scenes = [
    _SceneSpec(
      label: '电影感',
      icon: Icons.movie_filter_outlined,
      phrase: '电影感，浅景深，柔和的自然光',
    ),
    _SceneSpec(
      label: '治愈系',
      icon: Icons.wb_sunny_outlined,
      phrase: '治愈系，温暖明亮的光线，柔和的色调',
    ),
    _SceneSpec(
      label: '国风',
      icon: Icons.brush_outlined,
      phrase: '国风水墨质感，留白，淡雅配色',
    ),
    _SceneSpec(
      label: '赛博朋克',
      icon: Icons.nightlight_outlined,
      phrase: '赛博朋克，霓虹灯，雨后的街道，蓝紫色调',
    ),
    _SceneSpec(
      label: '写实',
      icon: Icons.camera_alt_outlined,
      phrase: '写实摄影质感，自然光，细节清晰',
    ),
    _SceneSpec(
      label: '动漫',
      icon: Icons.auto_awesome_outlined,
      phrase: '日系动漫风格，色彩明快，干净的画面',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Padding(
      // CSS: .scene-scroll { margin: 0 -20px 24px }
      padding: const EdgeInsets.only(bottom: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 标题要跟着页面 20 的左右留白，不能跟着卡片一起出血
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 20),
            child: SectionTitle(title: '创作场景'),
          ),
          SizedBox(
            // 横向 ListView 在纵向必须有一个确定高度，否则会报「无界高度」。
            // 84 就是原型 .scene-card 的高度。
            height: 84,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              // 【关键】整页的左右留白是 20，但这里只把 20 做进内边距，
              // 而不是让外层把整条横向列表缩进去 ——
              // 这样卡片才能贴着屏幕边缘滑出去（CSS 用负 margin 达到同样效果）。
              padding: const EdgeInsets.symmetric(horizontal: 20),
              itemCount: _scenes.length,
              separatorBuilder: (context, index) => const SizedBox(width: 10),
              itemBuilder: (context, index) => _SceneCard(
                spec: _scenes[index],
                onTap: () => onPick(_scenes[index].phrase),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 一张场景卡
class _SceneCard extends StatelessWidget {
  const _SceneCard({required this.spec, required this.onTap});

  final _SceneSpec spec;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      // key 用 label：测试里点「电影感」比点「第 3 个」稳得多，
      // 以后调整顺序也不会莫名其妙地失败。
      key: Key('scene.${spec.label}'),
      onTap: onTap,
      // opaque：整张卡都可点，不只是图标和文字那几块
      behavior: HitTestBehavior.opaque,
      child: Container(
        // CSS: .scene-card { min-width: 84px; height: 84px; border-radius: 16px }
        width: 84,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: AppGlass.normal,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(color: AppGlass.border, width: 1),
          boxShadow: const [
            BoxShadow(
              color: Color(0x0A000000),
              blurRadius: 24,
              offset: Offset(0, 4),
            ),
          ],
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // 图标底：32×32、圆角 10、浅绿底（原型的占位块，现在真的装上图标了）
            Container(
              width: 32,
              height: 32,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: AppColors.sageTint,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(spec.icon, size: 17, color: AppColors.sage),
            ),
            const SizedBox(height: 6),
            Text(
              spec.label,
              style: const TextStyle(
                fontSize: 11.5,
                fontWeight: FontWeight.w500,
                color: AppColors.charcoal,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
