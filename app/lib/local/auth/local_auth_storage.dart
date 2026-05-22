// ── LOCAL ONLY — this file has no upstream equivalent ──
import 'package:shared_preferences/shared_preferences.dart';

import '../local_auth_state.dart';

const _kToken = 'local_auth_token';
const _kExpiry = 'local_auth_expiry';
const _kUid = 'local_auth_uid';

// JWT TTL on the backend defaults to LOCAL_JWT_TTL_SECONDS=2592000 (30 days).
// We mirror that here so sessions survive app restarts without re-auth.
const _kDefaultTtlDays = 30;

class LocalAuthStorage {
  static Future<void> save(String token, String uid, {int ttlDays = _kDefaultTtlDays}) async {
    final prefs = await SharedPreferences.getInstance();
    final expiry = DateTime.now().add(Duration(days: ttlDays)).millisecondsSinceEpoch;
    await prefs.setString(_kToken, token);
    await prefs.setInt(_kExpiry, expiry);
    await prefs.setString(_kUid, uid);
    LocalAuthState.setSignedIn(true);
  }

  /// Returns the stored JWT if it exists and has not expired, otherwise null.
  static Future<String?> getValidToken() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(_kToken);
    if (token == null || token.isEmpty) return null;
    final expiry = prefs.getInt(_kExpiry) ?? 0;
    if (DateTime.now().millisecondsSinceEpoch > expiry) {
      await clear();
      return null;
    }
    return token;
  }

  static Future<String?> getUid() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_kUid);
  }

  static Future<bool> isSignedIn() async => (await getValidToken()) != null;

  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kToken);
    await prefs.remove(_kExpiry);
    await prefs.remove(_kUid);
    LocalAuthState.setSignedIn(false);
  }
}
