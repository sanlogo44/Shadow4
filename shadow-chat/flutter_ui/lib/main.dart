import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'state/app_state.dart';
import 'theme/shadow_theme.dart';
import 'app.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(
    ChangeNotifierProvider(
      create: (_) => AppState(),
      child: const ShadowApp(),
    ),
  );
}

/// Root-Widget. Wartet auf Initialisierung (Prefs laden, Token prüfen)
/// und entscheidet zwischen Setup/Login und der Haupt-App.
class ShadowApp extends StatefulWidget {
  const ShadowApp({super.key});

  @override
  State<ShadowApp> createState() => _ShadowAppState();
}

class _ShadowAppState extends State<ShadowApp> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<AppState>().init();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (context, state, _) {
        return MaterialApp(
          title: 'Shadow',
          debugShowCheckedModeBanner: false,
          theme: ShadowTheme.build(ShadowThemeMode.light, state.highlight),
          darkTheme: ShadowTheme.build(ShadowThemeMode.dark, state.highlight),
          themeMode: _materialThemeMode(state.themeMode),
          home: const ShadowRoot(),
        );
      },
    );
  }

  ThemeMode _materialThemeMode(ShadowThemeMode mode) {
    return switch (mode) {
      ShadowThemeMode.dark => ThemeMode.dark,
      ShadowThemeMode.light => ThemeMode.light,
      ShadowThemeMode.system => ThemeMode.system,
    };
  }
}
