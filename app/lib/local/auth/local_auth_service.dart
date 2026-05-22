// ── LOCAL ONLY — this file has no upstream equivalent ──
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:omi/env/env.dart';

import 'local_auth_storage.dart';

class LocalAuthResult {
  final bool success;
  final String? uid;
  final String? error;
  const LocalAuthResult({required this.success, this.uid, this.error});
}

class LocalAuthService {
  static String get _base {
    final url = Env.apiBaseUrl ?? 'http://localhost:8088';
    return url.endsWith('/') ? url.substring(0, url.length - 1) : url;
  }

  static Future<LocalAuthResult> signIn(String email, String password) async {
    try {
      final resp = await http
          .post(
            Uri.parse('$_base/v1/auth/login'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'email': email, 'password': password}),
          )
          .timeout(const Duration(seconds: 15));

      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        final token = data['access_token'] as String?;
        if (token == null) {
          return const LocalAuthResult(success: false, error: 'No access_token in response');
        }
        final uid = await _fetchUid(token);
        await LocalAuthStorage.save(token, uid ?? email);
        return LocalAuthResult(success: true, uid: uid);
      }

      String? detail;
      try {
        detail = (jsonDecode(resp.body) as Map<String, dynamic>)['detail'] as String?;
      } catch (_) {}
      return LocalAuthResult(success: false, error: detail ?? 'Login failed (${resp.statusCode})');
    } catch (e) {
      return LocalAuthResult(success: false, error: e.toString());
    }
  }

  static Future<LocalAuthResult> register(String email, String password) async {
    try {
      final resp = await http
          .post(
            Uri.parse('$_base/v1/auth/register'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'email': email, 'password': password}),
          )
          .timeout(const Duration(seconds: 15));

      if (resp.statusCode == 200 || resp.statusCode == 201) {
        return signIn(email, password);
      }

      String? detail;
      try {
        detail = (jsonDecode(resp.body) as Map<String, dynamic>)['detail'] as String?;
      } catch (_) {}
      return LocalAuthResult(success: false, error: detail ?? 'Registration failed (${resp.statusCode})');
    } catch (e) {
      return LocalAuthResult(success: false, error: e.toString());
    }
  }

  static Future<String?> _fetchUid(String token) async {
    try {
      final resp = await http
          .get(
            Uri.parse('$_base/v1/auth/me'),
            headers: {'Authorization': 'Bearer $token'},
          )
          .timeout(const Duration(seconds: 10));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        return data['user_id'] as String?;
      }
    } catch (_) {}
    return null;
  }

  static Future<void> signOut() => LocalAuthStorage.clear();
}
