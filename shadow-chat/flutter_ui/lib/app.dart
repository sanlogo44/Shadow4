import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'state/app_state.dart';
import 'screens/login_screen.dart';
import 'screens/chat_screen.dart';

/// Entscheidet anhand des AppState, welcher Bildschirm gezeigt wird.
class ShadowRoot extends StatelessWidget {
  const ShadowRoot({super.key});

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();

    if (!state.initialized) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (!state.isLoggedIn) {
      return const LoginScreen();
    }
    if (state.mustChangePassword) {
      // First-Login: Default-Admin muss neuen Admin anlegen.
      return const LoginScreen(forceSetup: true);
    }
    return const ChatScreen();
  }
}
