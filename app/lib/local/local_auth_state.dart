// ── LOCAL ONLY — this file has no upstream equivalent ──
// In-memory flag tracking whether the user is signed in via local JWT auth.
// Set to true during _init() (session restoration) and after successful sign-in.
// Set to false when LocalAuthStorage.clear() is called during sign-out.

class LocalAuthState {
  static bool _isSignedIn = false;

  static bool get isSignedIn => _isSignedIn;

  static void setSignedIn(bool value) {
    _isSignedIn = value;
  }
}
