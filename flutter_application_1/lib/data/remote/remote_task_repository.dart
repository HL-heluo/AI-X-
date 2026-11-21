import '../../core/constants/api_paths.dart';
import '../../core/json_utils.dart';
import '../../core/network/api_client.dart';
import '../../models/task.dart';
import '../../repositories/task_repository.dart';

/// [TaskRepository] 的真实实现
class RemoteTaskRepository implements TaskRepository {
  RemoteTaskRepository(this._client);

  final ApiClient _client;

  @override
  Future<List<Task>> fetchActive() => _fetchList(ApiPaths.statusActive);

  @override
  Future<List<Task>> fetchDone() => _fetchList(ApiPaths.statusDone);

  @override
  Future<Task> fetchDetail(String id) async {
    final json = await _client.get(ApiPaths.taskDetail(id));
    return Task.fromJson(json);
  }

  @override
  Future<Task> cancel(String id) async {
    final json = await _client.post(ApiPaths.taskCancel(id));
    return Task.fromJson(json);
  }

  /// 拉列表并解包。
  ///
  /// 【为什么两个方法合成一个私有方法】因为差异只有一个查询参数的值，
  /// 写两遍就是两份会各自漂移的解析代码。
  Future<List<Task>> _fetchList(String status) async {
    final json = await _client.get(
      ApiPaths.tasks,
      query: <String, dynamic>{'status': status},
    );
    // 【为什么不用 Paged.fromJson 解包】因为 §12.1 里 `/tasks` 并没有分页参数，
    // 它不是分页接口，只是恰好把数组放在 `items` 里。
    // 借 Paged 来解包会让人误以为这里有翻页，读代码的人会去找
    // 一个根本不存在的 page 参数。
    return json
        .asJsonList(json['items'], field: 'items')
        .map(Task.fromJson)
        .toList(growable: false);
  }
}
