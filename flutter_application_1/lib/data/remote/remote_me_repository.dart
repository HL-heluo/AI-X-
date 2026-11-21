import '../../core/constants/api_paths.dart';
import '../../core/network/api_client.dart';
import '../../models/me_profile.dart';
import '../../repositories/me_repository.dart';

/// [MeRepository] 的真实实现
class RemoteMeRepository implements MeRepository {
  RemoteMeRepository(this._client);

  final ApiClient _client;

  @override
  Future<MeProfile> fetchProfile() async {
    final json = await _client.get(ApiPaths.me);
    return MeProfile.fromJson(json);
  }
}
