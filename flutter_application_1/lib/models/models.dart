/// 数据模型统一出口
///
/// 【为什么要这个文件】
/// 因为一个页面通常要同时用三四个模型，`import` 会堆成一片：
///
/// ```dart
/// import '../../../models/asset.dart';
/// import '../../../models/credit_account.dart';
/// import '../../../models/paged.dart';
/// import '../../../models/task.dart';
/// ```
///
/// 有了这个出口就变成一行：
///
/// ```dart
/// import '../../../models/models.dart';
/// ```
///
/// 【顺带一个好处】`export` 让「模型层有哪些东西」一眼可见。
/// 想知道有哪些模型，看这个文件就行，不用去翻目录。
///
/// 【注意这里只导出模型，不导出 core/ 下的其它常量】
/// `ApiPaths`、`ApiErrorCode` 那些住在 `core/constants/`，各自是独立领域的唯一出处，
/// 混进来会让人分不清「什么是数据、什么是契约」。
///
/// **例外是 `TaskStatus`**：它不是普通常量，而是 `Task` 这个类型的**组成部分**——
/// 任何拿到 `Task` 的地方都要 `switch` 它的状态，不 re-export 的话每个页面都得
/// 多写一行 import。所以它跟着 `Task` 一起从出口走。
library;

export '../core/constants/task_status.dart';
export 'asset.dart';
export 'auth_session.dart';
export 'credit_account.dart';
export 'credit_ledger_entry.dart';
export 'me_profile.dart';
export 'paged.dart';
export 'task.dart';
export 'task_cost_estimate.dart';
export 'user.dart';
