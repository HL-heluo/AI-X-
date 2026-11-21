/// 接口路径 —— **全项目唯一定义处**
///
/// 对应《工程文档.md》§12.1。这 13 个端点是 App 与后端的全部约定。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么路径写成一个类，而不是到处写字符串】
/// 路径写错是「编译能过、运行才炸」的典型：`'/task/1'` 少个 s，
/// analyze 一声不吭，跑到真机上给你一个 404。集中成常量后，
/// 打错字会变成「找不到这个符号」的编译错误，当场就发现。
///
/// ─────────────────────────────────────────────────────────
/// 【⚠️ 关于 `credits` 复数：这是**接口路径**，不是代码标识符】
///
/// 文档 §2「术语锁定」要求代码里一律用单数 `credit`，
/// 但 §12.1 的路径写的是 `/credits/ledger`。
///
/// 这两条不冲突，界限是：
/// · **网络上一根字符串** → 照抄契约，一个字都不能改（改了就和后端对不上）
/// · **代码里的名字**（类名/变量/字段/枚举）→ 一律单数 `credit`
///
/// 所以下面你会看到 `creditLedger = '/credits/ledger'`：
/// 常量名是 `creditLedger`（单数，守 §2），值是 `/credits/ledger`（复数，守 §12.1）。
/// 这不是笔误，是两条规矩各自的边界。
/// ─────────────────────────────────────────────────────────
class ApiPaths {
  /// 私有构造：这个类只用来装常量，不该被 new 出来。
  ///
  /// 【一个小习惯，值得说明】Dart 里 `class` 默认能被 `new`，
  /// 于是 `ApiPaths()` 这种没意义的写法会通过编译。
  /// 加一个私有构造就把它堵死了 —— 和项目里 `AppColors._()` 是同一个套路。
  ApiPaths._();

  // ── 认证 §12.1 ───────────────────────────────────────────

  /// `POST /auth/register` —— 注册。新用户赠 50 积分（后端记账）。
  static const String register = '/auth/register';

  /// `POST /auth/login` —— 登录，返回 token。
  static const String login = '/auth/login';

  // ── 用户与积分 ───────────────────────────────────────────

  /// `GET /me` —— 当前用户信息 + 积分总览（余额 / 冻结 / 可用）。
  static const String me = '/me';

  /// `GET /credits/ledger` —— 积分流水（分页）。
  ///
  /// 值里的 `credits` 是复数，照抄契约；常量名保持单数 —— 见类注释。
  static const String creditLedger = '/credits/ledger';

  /// `GET /credits/chain` —— 影子链凭证（钱包地址 / 合约 / 链上余额 / 最近上链记录）
  static const String creditChain = '/credits/chain';

  // ── 上传与生成 ───────────────────────────────────────────

  /// `POST /uploads/image` —— 上传参考图，返回 asset_id。
  ///
  /// 【为什么要先上传、不能直传 provider】
  /// 因为 provider 的产物 URL 只活 1 小时，参考图若直传过去，
  /// 我们这边就没留下任何可追溯的凭证。先落我们的 OSS，拿到永久 asset_id。
  static const String uploadImage = '/uploads/image';

  /// `POST /generation/image` —— 文生图。
  static const String generateImage = '/generation/image';

  /// `POST /generation/video` —— 图生视频 / 文生视频。
  static const String generateVideo = '/generation/video';

  /// `GET /generation/cost` —— 下单前问价，返回 `{min, max, freeze}`。
  ///
  /// 【⚠️ 契约缺口的处理】
  /// §12.1 只写了返回值，**没写要传什么参数**。不传参数后端就不知道问的是哪种、多长、什么比例的价。
  /// 这里按最自然的方式**拍板冻结**为查询参数：
  ///   `GET /generation/cost?kind=<image_to_video>&duration=<5>&ratio=<16:9>`
  /// 其中 `kind` 取 [TaskKind] 的 wire 值，`duration` 单位秒，`ratio` 如 `16:9`。
  /// 图片问价只需 `kind`。**Mock 先按这个实现，接真后端前需与后端确认一次。**
  static const String generationCost = '/generation/cost';

  // ── 任务 ────────────────────────────────────────────────

  /// `GET /tasks?status=active|done` —— 任务列表，按状态筛选。
  static const String tasks = '/tasks';

  /// `GET /tasks/{id}` —— 任务详情（含排队位次）。
  static String taskDetail(String id) => '/tasks/$id';

  /// `POST /tasks/{id}/cancel` —— 取消任务（退回冻结积分）。
  static String taskCancel(String id) => '/tasks/$id/cancel';

  // ── 资产 ────────────────────────────────────────────────

  /// `GET /assets` —— 我的资产列表（永久 URL）。
  static const String assets = '/assets';

  /// `DELETE /assets/{id}` —— 删除资产。
  static String assetDetail(String id) => '/assets/$id';
  static String assetEvidence(String id) => '/assets/$id/evidence';

  // ── 列表筛选值 ───────────────────────────────────────────

  /// `GET /tasks` 的 `status` 查询参数取值。
  ///
  /// 【为什么用这两个词而不是 true/false】
  /// 因为「进行中」在文档里对应的是**一组**状态（pending/queued/submitted），
  /// 不是一个布尔。用 `active|done` 表达，将来后端细分状态时这个参数不用改。
  static const String statusActive = 'active';
  static const String statusDone = 'done';
}
