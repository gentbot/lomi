// ── LOCAL ONLY — this file has no upstream equivalent ──
import 'package:flutter/material.dart';
import 'package:omi/local/auth/local_auth_service.dart';

class LocalSignInPage extends StatefulWidget {
  final VoidCallback onSignedIn;
  const LocalSignInPage({super.key, required this.onSignedIn});

  @override
  State<LocalSignInPage> createState() => _LocalSignInPageState();
}

class _LocalSignInPageState extends State<LocalSignInPage> {
  final _emailCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  bool _showRegister = false;

  Future<void> _submit() async {
    final email = _emailCtrl.text.trim();
    final pass = _passCtrl.text;
    if (email.isEmpty || pass.isEmpty) {
      setState(() => _error = 'Email and password are required.');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });

    final result = _showRegister
        ? await LocalAuthService.register(email, pass)
        : await LocalAuthService.signIn(email, pass);

    if (!mounted) return;
    if (result.success) {
      widget.onSignedIn();
    } else {
      setState(() {
        _loading = false;
        _error = result.error ?? 'Unknown error. Check that the backend is running.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        title: Text(
          _showRegister ? 'Create account' : 'Sign in',
          style: const TextStyle(fontFamily: 'Manrope', fontWeight: FontWeight.w600),
        ),
        elevation: 0,
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 16),
              const Text(
                'Omi · Local',
                style: TextStyle(color: Colors.white, fontSize: 28, fontWeight: FontWeight.bold, fontFamily: 'Manrope'),
              ),
              const SizedBox(height: 6),
              Text(
                _showRegister ? 'Create a local account on this backend.' : 'Sign in with your local backend account.',
                style: const TextStyle(color: Colors.white54, fontSize: 14, fontFamily: 'Manrope'),
              ),
              const SizedBox(height: 36),
              TextField(
                controller: _emailCtrl,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                textInputAction: TextInputAction.next,
                style: const TextStyle(color: Colors.white),
                decoration: _inputDecoration('Email'),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _passCtrl,
                obscureText: true,
                textInputAction: TextInputAction.done,
                style: const TextStyle(color: Colors.white),
                decoration: _inputDecoration('Password'),
                onSubmitted: (_) => _submit(),
              ),
              if (_error != null) ...[
                const SizedBox(height: 14),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.red.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.red.withOpacity(0.4)),
                  ),
                  child: Text(
                    _error!,
                    style: const TextStyle(color: Colors.redAccent, fontSize: 13, fontFamily: 'Manrope'),
                  ),
                ),
              ],
              const SizedBox(height: 28),
              SizedBox(
                height: 56,
                child: ElevatedButton(
                  onPressed: _loading ? null : _submit,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.white,
                    foregroundColor: Colors.black,
                    disabledBackgroundColor: Colors.white24,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(28)),
                  ),
                  child: _loading
                      ? const SizedBox(
                          height: 22,
                          width: 22,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black54),
                        )
                      : Text(
                          _showRegister ? 'Create account' : 'Sign in',
                          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600, fontFamily: 'Manrope'),
                        ),
                ),
              ),
              const SizedBox(height: 20),
              TextButton(
                onPressed: _loading ? null : () => setState(() {
                      _showRegister = !_showRegister;
                      _error = null;
                    }),
                child: Text(
                  _showRegister ? 'Already have an account? Sign in' : 'No account yet? Register',
                  style: const TextStyle(color: Colors.white54, fontFamily: 'Manrope'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  InputDecoration _inputDecoration(String label) => InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: Colors.white54),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Colors.white24),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Colors.white70),
        ),
        filled: true,
        fillColor: Colors.white.withOpacity(0.06),
      );

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }
}
