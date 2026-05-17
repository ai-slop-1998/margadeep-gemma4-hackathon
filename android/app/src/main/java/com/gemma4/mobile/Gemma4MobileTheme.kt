package com.gemma4.mobile

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Gemma4ColorScheme: ColorScheme = lightColorScheme(
    primary = Color(0xFF0B4B56),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFBFEAFE),
    onPrimaryContainer = Color(0xFF06333B),
    secondary = Color(0xFF4E9A60),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE8F4DC),
    onSecondaryContainer = Color(0xFF203D27),
    tertiary = Color(0xFFD85F37),
    onTertiary = Color.White,
    background = Color(0xFFF8F4EE),
    onBackground = Color(0xFF2C2822),
    surface = Color(0xFFFFFCF8),
    onSurface = Color(0xFF2C2822),
    surfaceVariant = Color(0xFFEDE3D8),
    onSurfaceVariant = Color(0xFF5A5147),
    outline = Color(0xFFD9CBBB),
)

@Composable
fun Gemma4MobileTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = Gemma4ColorScheme,
        typography = MaterialTheme.typography,
        content = content,
    )
}
