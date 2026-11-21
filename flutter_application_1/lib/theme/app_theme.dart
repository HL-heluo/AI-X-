import 'package:flutter/material.dart';

class AppColors {
  AppColors._();

  static const bgWarm = Color(0xFFF4F7F5);
  static const bgPeach = Color(0xFFFBEAE1);
  static const bgCream = Color(0xFFF5EEE1);
  static const sageLight = Color(0xFFDDEDE4);
  static const sage = Color(0xFF22594A);
  static const sageSoft = Color(0xFF4E806F);
  static const sageTint = Color(0x1422594A);
  static const gold = Color(0xFF896123);
  static const goldSoft = Color(0xFFE9D4AF);

  static const charcoal = Color(0xFF142923);
  static const textBody = Color(0xFF374D44);
  static const taupe = Color(0xFF5F7169);
  static const danger = Color(0xFFAE382F);
  static const divider = Color(0xFFDDE6DF);
  static const amber = Color(0xFFA16414);
  static const sunken = Color(0xFFEAF0EC);
}

class AppGlass {
  AppGlass._();

  static const normal = Color(0xFAFFFFFF);
  static const strong = Colors.white;
  static const border = AppColors.divider;
  static const panel = Color(0xFFF6F9F7);
  static const tile = Color(0xFFEFF5F1);
  static const borderSoft = Color(0xFFE0E8E2);
  static const borderBright = Color(0xFFE8EEE9);
}

class AppRadius {
  AppRadius._();

  static const hero = 24.0;
  static const card = 18.0;
  static const lg = 12.0;
  static const pill = 999.0;
}

class AppTheme {
  AppTheme._();

  static ThemeData get light {
    const fieldBorder = OutlineInputBorder(
      borderRadius: BorderRadius.all(Radius.circular(AppRadius.lg)),
      borderSide: BorderSide(color: AppColors.divider),
    );
    final buttonShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(AppRadius.lg),
    );
    const colorScheme = ColorScheme.light(
      primary: AppColors.sage,
      onPrimary: Colors.white,
      primaryContainer: AppColors.sageLight,
      onPrimaryContainer: AppColors.charcoal,
      secondary: AppColors.gold,
      onSecondary: Colors.white,
      surface: Colors.white,
      onSurface: AppColors.charcoal,
      onSurfaceVariant: AppColors.taupe,
      surfaceContainerHighest: AppColors.sunken,
      outline: AppColors.taupe,
      outlineVariant: AppColors.divider,
      error: AppColors.danger,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: AppColors.bgWarm,
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: true,
        foregroundColor: AppColors.charcoal,
        titleTextStyle: TextStyle(
          color: AppColors.charcoal,
          fontSize: 18,
          fontWeight: FontWeight.w700,
        ),
      ),
      textTheme: const TextTheme(
        headlineMedium: TextStyle(
          fontSize: 30,
          color: AppColors.charcoal,
          fontWeight: FontWeight.w800,
          letterSpacing: -0.5,
        ),
        headlineSmall: TextStyle(
          fontSize: 23,
          color: AppColors.charcoal,
          fontWeight: FontWeight.w700,
        ),
        titleLarge: TextStyle(
          fontSize: 19,
          color: AppColors.charcoal,
          fontWeight: FontWeight.w700,
        ),
        titleMedium: TextStyle(
          fontSize: 16,
          color: AppColors.charcoal,
          fontWeight: FontWeight.w600,
        ),
        bodyMedium: TextStyle(
          color: AppColors.textBody,
          fontSize: 14,
          height: 1.45,
        ),
        bodySmall: TextStyle(color: AppColors.taupe, fontSize: 12, height: 1.4),
      ),
      inputDecorationTheme: InputDecorationThemeData(
        filled: true,
        fillColor: AppGlass.panel,
        labelStyle: const TextStyle(color: AppColors.taupe),
        floatingLabelStyle: const TextStyle(color: AppColors.sage),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 14,
        ),
        border: fieldBorder,
        enabledBorder: fieldBorder,
        focusedBorder: fieldBorder.copyWith(
          borderSide: const BorderSide(color: AppColors.sage, width: 1.6),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          shape: buttonShape,
          minimumSize: const Size(0, 44),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          shape: buttonShape,
          side: const BorderSide(color: AppColors.divider),
          minimumSize: const Size(0, 44),
        ),
      ),
      tabBarTheme: const TabBarThemeData(
        labelColor: AppColors.sage,
        unselectedLabelColor: AppColors.taupe,
        labelStyle: TextStyle(fontSize: 14, fontWeight: FontWeight.w700),
        indicatorColor: AppColors.sage,
        dividerColor: AppColors.divider,
      ),
      navigationBarTheme: NavigationBarThemeData(
        indicatorColor: AppColors.sageLight,
        iconTheme: WidgetStateProperty.resolveWith(
          (states) => IconThemeData(
            size: 22,
            color: states.contains(WidgetState.selected)
                ? AppColors.sage
                : AppColors.taupe,
          ),
        ),
        labelTextStyle: WidgetStateProperty.resolveWith(
          (states) => states.contains(WidgetState.selected)
              ? const TextStyle(
                  fontSize: 12,
                  color: AppColors.sage,
                  fontWeight: FontWeight.w700,
                )
              : const TextStyle(
                  fontSize: 12,
                  color: AppColors.taupe,
                  fontWeight: FontWeight.w500,
                ),
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.hero),
        ),
      ),
      snackBarTheme: const SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: AppColors.charcoal,
        contentTextStyle: TextStyle(color: Colors.white),
      ),
      dividerTheme: const DividerThemeData(color: AppColors.divider, space: 1),
    );
  }
}
