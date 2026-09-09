import 'package:flutter/material.dart';

/// Shadow-Farbkonstanten gemäß Spezifikation.
class ShadowColors {
  ShadowColors._();

  /// Standard-Highlight-Farbe (Shadow-Grün).
  static const Color defaultHighlight = Color(0xFF16C916);
  static const Color darkBackground = Color(0xFF000000);
  static const Color lightBackground = Color(0xFFFFFFFF);
}

/// Theme-Modus: dark | light | system.
enum ShadowThemeMode { dark, light, system }

/// Baut das Material-Theme für Shadow.
///
/// Hintergrund: Dark = #000000, Light = #ffffff.
/// Highlight-Farbe ist pro Benutzer änderbar (RGB / Hex / Farbrad)
/// und wird als `seedColor` für das ColorScheme verwendet, sodass die
/// gesamte Oberfläche konsistent das Grün (oder eine Wunschfarbe) nutzt.
class ShadowTheme {
  static ThemeData build(ShadowThemeMode mode, Color highlight) {
    final brightness = mode == ShadowThemeMode.light
        ? Brightness.light
        : (mode == ShadowThemeMode.dark ? Brightness.dark : _systemBrightness());

    final isDark = brightness == Brightness.dark;
    final base = ColorScheme.fromSeed(
      seedColor: highlight,
      brightness: brightness,
    );

    final backgroundColor =
        isDark ? ShadowColors.darkBackground : ShadowColors.lightBackground;

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: base.copyWith(
        surface: backgroundColor,
      ),
      scaffoldBackgroundColor: backgroundColor,
      appBarTheme: AppBarTheme(
        backgroundColor: backgroundColor,
        foregroundColor: isDark ? Colors.white : Colors.black,
        elevation: 0,
        centerTitle: false,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: isDark
            ? const Color(0xFF0E0E0E)
            : const Color(0xFFF4F4F4),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: highlight, width: 1.5),
        ),
      ),
      floatingActionButtonTheme:
          FloatingActionButtonThemeData(backgroundColor: highlight),
      progressIndicatorTheme:
          ProgressIndicatorThemeData(color: highlight),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: highlight),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: highlight,
          foregroundColor: Colors.black,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
        ),
      ),
      dividerTheme: DividerThemeData(
        color: isDark ? const Color(0xFF1C1C1C) : const Color(0xFFE0E0E0),
      ),
    );
  }

  static Brightness _systemBrightness() {
    return WidgetsBinding.instance.platformDispatcher.platformBrightness;
  }

  /// Parst eine Hex-Farbe (#RRGGBB oder RRGGBB). null bei Fehler.
  static Color? parseHex(String input) {
    var hex = input.trim();
    if (hex.startsWith('#')) hex = hex.substring(1);
    if (hex.length == 6) hex = 'FF$hex';
    try {
      return Color(int.parse(hex, radix: 16));
    } catch (_) {
      return null;
    }
  }

  static String toHex(Color c) {
    final v = c.toARGB32();
    return '#${((v >> 16) & 0xFF).toRadixString(16).padLeft(2, '0')}'
        '${((v >> 8) & 0xFF).toRadixString(16).padLeft(2, '0')}'
        '${(v & 0xFF).toRadixString(16).padLeft(2, '0')}';
  }
}

/// Konvertiert String <-> ShadowThemeMode.
extension ShadowThemeModeX on ShadowThemeMode {
  String get name => switch (this) {
        ShadowThemeMode.dark => 'dark',
        ShadowThemeMode.light => 'light',
        ShadowThemeMode.system => 'system',
      };

  static ShadowThemeMode fromString(String? s) {
    return switch (s) {
      'dark' => ShadowThemeMode.dark,
      'light' => ShadowThemeMode.light,
      _ => ShadowThemeMode.system,
    };
  }
}
