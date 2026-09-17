// weather_GPT icon generator.
//
// Draws a sun + cloud + "GPT" badge icon and emits every app-icon target:
//   - assets/icon_source.png          (1024x1024 master)
//   - android .../mipmap-*/ic_launcher.png
//   - web/icons/Icon-*.png, Icon-maskable-*.png, web/favicon.png
//   - windows/runner/resources/app_icon.ico (multi-size, PNG-compressed)
//
// Run from mobile/flutter_app:  dart run tool/icon_gen.dart
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

const size = 1024;

// Palette
final Color skyTop = const Color(0xFF2563EB);
final Color skyBottom = const Color(0xFF60A5FA);
final Color sunOuter = const Color(0xFFFCD34D);
final Color sunInner = const Color(0xFFFBBF24);
final Color sunCore = const Color(0xFFFDE68A);
final Color cloud = const Color(0xFFFFFFFF);
final Color cloudShade = const Color(0xFFE0EAFF);
final Color badge = const Color(0xFF1E293B);
final Color badgeText = const Color(0xFFF8FAFC);

class Color {
  final int value;
  const Color(this.value);
  int get r => (value >> 16) & 0xFF;
  int get g => (value >> 8) & 0xFF;
  int get b => value & 0xFF;
  int get a => (value >> 24) & 0xFF;
}

void main() {
  final buf = Float32List(size * size * 4); // RGBA workspace

  // ---- Background: vertical gradient with rounded-square mask ----
  final radius = size * 0.18;
  for (int y = 0; y < size; y++) {
    for (int x = 0; x < size; x++) {
      final t = y / (size - 1);
      var c = lerpColor(skyTop, skyBottom, t);

      // Subtle radial glow near top-left behind the sun.
      final dx = (x - size * 0.32) / (size * 0.9);
      final dy = (y - size * 0.30) / (size * 0.9);
      final glow = max(0.0, 1.0 - sqrt(dx * dx + dy * dy));
      c = lerpColor(c, sunCore, glow * 0.25);

      final alpha = roundedRectAlpha(x + 0.5, y + 0.5, radius);
      final idx = (y * size + x) * 4;
      buf[idx + 0] = c.r / 255.0;
      buf[idx + 1] = c.g / 255.0;
      buf[idx + 2] = c.b / 255.0;
      buf[idx + 3] = alpha;
    }
  }

  // ---- Sun (top-left, partially behind cloud) ----
  const sunCx = 0.36 * size;
  const sunCy = 0.34 * size;
  const sunR = 0.17 * size;
  for (int i = 0; i < 12; i++) {
    drawRay(buf, sunCx, sunCy, sunR * 1.18, sunR * 1.55, i * pi / 6, sunOuter);
  }
  fillCircle(buf, sunCx, sunCy, sunR * 1.12, sunOuter);
  fillCircle(buf, sunCx, sunCy, sunR * 0.98, sunInner);
  fillCircle(buf, sunCx - sunR * 0.22, sunCy - sunR * 0.22, sunR * 0.6, sunCore);

  // ---- Cloud (foreground) ----
  const cx = 0.56 * size;
  const cy = 0.58 * size;
  const s = 0.16 * size; // scale unit
  final puffs = <(double, double, double)>[
    (cx - 1.35 * s, cy + 0.10 * s, 0.78 * s),
    (cx - 0.45 * s, cy - 0.42 * s, 0.92 * s),
    (cx + 0.55 * s, cy - 0.15 * s, 0.85 * s),
    (cx + 1.25 * s, cy + 0.15 * s, 0.62 * s),
  ];
  // Soft shadow puffs slightly offset down-right for depth.
  for (final (px, py, pr) in puffs) {
    fillCircle(buf, px + 0.035 * size, py + 0.045 * size, pr, cloudShade);
  }
  for (final (px, py, pr) in puffs) {
    fillCircle(buf, px, py, pr, cloud);
  }
  // Base rounded slab connecting puffs.
  fillRoundedRect(
      buf, cx - 2.0 * s, cy + 0.05 * s, 4.05 * s, 0.95 * s, 0.475 * s, cloud);

  // ---- GPT badge (bottom-center) ----
  const bw = 0.62 * size;
  const bh = 0.24 * size;
  const bx = (size - bw) / 2;
  const by = size - bh - 0.06 * size;
  fillRoundedRect(
      buf, bx + 3, by + 5, bw, bh, bh * 0.32, const Color(0x66000000));
  fillRoundedRect(buf, bx, by, bw, bh, bh * 0.32, badge);

  drawText(buf, 'GPT', bx + bw / 2, by + bh / 2, bh * 0.52, badgeText);

  // ---- Emit targets ----
  final outDir = Directory('assets');
  if (!outDir.existsSync()) outDir.createSync(recursive: true);
  writePng('assets/icon_source.png', buf);

  final androidSizes = {
    'mdpi': 48,
    'hdpi': 72,
    'xhdpi': 96,
    'xxhdpi': 144,
    'xxxhdpi': 192,
  };
  final src = decodePng('assets/icon_source.png')!;
  for (final entry in androidSizes.entries) {
    final dir =
        'android/app/src/main/res/mipmap-${entry.key}';
    Directory(dir).createSync(recursive: true);
    writePng('$dir/ic_launcher.png', resize(src, entry.value));
    stdout.writeln('Wrote $dir/ic_launcher.png (${entry.value}px)');
  }

  // Web icons: regular (bleed to edges) and maskable (80% safe zone).
  writePng('web/icons/Icon-192.png', resize(src, 192));
  writePng('web/icons/Icon-512.png', resize(src, 512));
  final masked = resize(src, 512, inset: 0.10, pad: true);
  writePng('web/icons/Icon-maskable-512.png', masked);
  writePng('web/icons/Icon-maskable-192.png', resize(masked, 192));
  writePng('web/favicon.png', resize(src, 32));
  stdout.writeln('Wrote web icons + favicon');

  // Windows .ico: multi-size, PNG-compressed entries (Vista+).
  final icoSizes = [16, 24, 32, 48, 64, 128, 256];
  writeIco('windows/runner/resources/app_icon.ico',
      [for (final s in icoSizes) resize(src, s)]);
  stdout.writeln('Wrote windows/runner/resources/app_icon.ico '
      '(${icoSizes.join(", ")})');
}

// ---------------- Geometry helpers ---------------- //

double roundedRectAlpha(double px, double py, double radius) {
  const half = size / 2;
  final dx = (px - half).abs() - (half - radius);
  final dy = (py - half).abs() - (half - radius);
  if (dx <= 0 || dy <= 0) return 1.0; // inside the cross region
  final dist = sqrt(dx * dx + dy * dy);
  return (radius - dist).clamp(0.0, 1.0); // 1px AA on the corner arc
}

void fillCircle(Float32List buf, double cx, double cy, double r, Color c) {
  final x0 = max(0, (cx - r - 2).floor());
  final x1 = min(size - 1, (cx + r + 2).ceil());
  final y0 = max(0, (cy - r - 2).floor());
  final y1 = min(size - 1, (cy + r + 2).ceil());
  for (int y = y0; y <= y1; y++) {
    for (int x = x0; x <= x1; x++) {
      final dx = x + 0.5 - cx;
      final dy = y + 0.5 - cy;
      final d = sqrt(dx * dx + dy * dy);
      final a = (r - d).clamp(0.0, 1.0);
      if (a > 0) blend(buf, x, y, c, a);
    }
  }
}

void fillRoundedRect(Float32List buf, double x, double y, double w, double h,
    double r, Color c) {
  for (int py = y.floor(); py <= (y + h).ceil(); py++) {
    for (int px = x.floor(); px <= (x + w).ceil(); px++) {
      if (px < 0 || py < 0 || px >= size || py >= size) continue;
      final qx = max(x - px - 1.0 + 0.5, px + 0.5 - (x + w));
      final qy = max(y - py - 1.0 + 0.5, py + 0.5 - (y + h));
      final dx = max(0.0, qx);
      final dy = max(0.0, qy);
      final d = sqrt(dx * dx + dy * dy);
      final a = (r - d).clamp(0.0, 1.0);
      if (a > 0) blend(buf, px, py, c, a);
    }
  }
}

void drawRay(Float32List buf, double cx, double cy, double r0, double r1,
    double ang, Color c) {
  const width = 0.035 * size; // half-width at base
  final dirX = cos(ang), dirY = sin(ang);
  final perpX = -dirY, perpY = dirX;
  final steps = ((r1 - r0) * 2).ceil();
  for (int i = 0; i <= steps; i++) {
    final rr = r0 + (r1 - r0) * i / steps;
    final halfW = width * (1 - 0.55 * (rr - r0) / (r1 - r0));
    for (double t = -halfW; t <= halfW; t += 0.5) {
      final px = (cx + dirX * rr + perpX * t).floor();
      final py = (cy + dirY * rr + perpY * t).floor();
      if (px >= 0 && py >= 0 && px < size && py < size) {
        blend(buf, px, py, c, 1.0);
      }
    }
  }
}

// ---------------- Tiny bitmap font for G/P/T ---------------- //

const Map<String, List<String>> font = {
  'G': [
    '01111',
    '10000',
    '10000',
    '10111',
    '10001',
    '10001',
    '01110',
  ],
  'P': [
    '11110',
    '10001',
    '10001',
    '11110',
    '10000',
    '10000',
    '10000',
  ],
  'T': [
    '11111',
    '00100',
    '00100',
    '00100',
    '00100',
    '00100',
    '00100',
  ],
};

void drawText(Float32List buf, String text, double cx, double cy,
    double glyphHeight, Color c) {
  final glyphW = glyphHeight * 5 / 7;
  final gap = glyphW * 0.35;
  final totalW = text.length * glyphW + (text.length - 1) * gap;
  var x = cx - totalW / 2;
  final y0 = cy - glyphHeight / 2;
  for (final ch in text.split('')) {
    final rows = font[ch];
    if (rows == null) {
      x += glyphW + gap;
      continue;
    }
    for (int row = 0; row < rows.length; row++) {
      for (int col = 0; col < rows[row].length; col++) {
        if (rows[row][col] == '1') {
          final sx = x + col * glyphW / 5;
          final sy = y0 + row * glyphHeight / 7;
          fillRoundedRect(buf, sx, sy, glyphW / 5 + 0.75,
              glyphHeight / 7 + 0.75, glyphHeight / 28, c);
        }
      }
    }
    x += glyphW + gap;
  }
}

// ---------------- Pixel blending ---------------- //

void blend(Float32List buf, int x, int y, Color c, double a) {
  final idx = (y * size + x) * 4;
  final dstA = buf[idx + 3];
  final srcA = a;
  final outA = srcA + dstA * (1 - srcA);
  if (outA <= 0) return;
  for (int k = 0; k < 3; k++) {
    buf[idx + k] =
        (buf[idx + k] * dstA * (1 - srcA) + (c.r / 255.0) * srcA) / outA;
  }
  buf[idx + 3] = outA;
}

Color lerpColor(Color a, Color b, double t) {
  t = t.clamp(0.0, 1.0);
  return Color(
    ((a.r + (b.r - a.r) * t).round() << 16) |
        ((a.g + (b.g - a.g) * t).round() << 8) |
        (a.b + (b.b - a.b) * t).round() |
        (0xFF << 24),
  );
}

// ---------------- Resampling (box filter, straight alpha) ---------------- //

Float32List resize(Float32List src, int dst,
    {double inset = 0.0, bool pad = false}) {
  final out = Float32List(dst * dst * 4);
  // Source is a square RGBA buffer; infer its dimension from the length.
  final srcDim = sqrt(src.length / 4).round();
  final margin = pad ? (dst * (1 - 1 / (1 + 2 * inset))).round() : 0;
  final inner = dst - 2 * margin;
  for (int y = 0; y < dst; y++) {
    for (int x = 0; x < dst; x++) {
      if (pad && (x < margin || y < margin || x >= margin + inner || y >= margin + inner)) {
        continue; // transparent padding for maskable icons
      }
      final sx0 = (((x - margin) * srcDim) ~/ inner).clamp(0, srcDim);
      final sy0 = (((y - margin) * srcDim) ~/ inner).clamp(0, srcDim);
      final sx1 = ((((x - margin + 1) * srcDim) / inner).ceil()).clamp(sx0 + 1, srcDim);
      final sy1 = ((((y - margin + 1) * srcDim) / inner).ceil()).clamp(sy0 + 1, srcDim);
      double r = 0, g = 0, b = 0, a = 0;
      int n = 0;
      for (int sy = sy0; sy < sy1; sy++) {
        for (int sx = sx0; sx < sx1; sx++) {
          final idx = (sy * srcDim + sx) * 4;
          r += src[idx + 0] * src[idx + 3];
          g += src[idx + 1] * src[idx + 3];
          b += src[idx + 2] * src[idx + 3];
          a += src[idx + 3];
          n++;
        }
      }
      final oidx = (y * dst + x) * 4;
      if (a > 0) {
        out[oidx + 0] = r / a;
        out[oidx + 1] = g / a;
        out[oidx + 2] = b / a;
        out[oidx + 3] = a / n;
      }
    }
  }
  return out;
}

// ---------------- Minimal PNG encode/decode (RGBA8) ---------------- //

void writePng(String path, Float32List buf) {
  // All buffers are square RGBA; infer the dimension from the length.
  File(path).writeAsBytesSync(encodePngBytes(buf, sqrt(buf.length / 4).round()));
}

List<int> encodePngBytes(Float32List buf, int n) {
  final raw = BytesBuilder();
  // One filter byte (0 = None) per ROW, then the row's RGBA bytes.
  final row = Uint8List(1 + n * 4);
  for (int y = 0; y < n; y++) {
    row[0] = 0;
    for (int x = 0; x < n; x++) {
      final idx = (y * n + x) * 4;
      final a = buf[idx + 3].clamp(0.0, 1.0);
      final o = 1 + x * 4;
      if (a > 0) {
        row[o + 0] = (buf[idx + 0] / a * 255).round().clamp(0, 255);
        row[o + 1] = (buf[idx + 1] / a * 255).round().clamp(0, 255);
        row[o + 2] = (buf[idx + 2] / a * 255).round().clamp(0, 255);
      } else {
        row[o + 0] = 0;
        row[o + 1] = 0;
        row[o + 2] = 0;
      }
      row[o + 3] = (a * 255).round();
    }
    raw.add(row);
  }

  final chunks = BytesBuilder();
  chunks.add(chunk('IHDR', ihdr(n)));
  chunks.add(chunk('IDAT', zlib.encoder.convert(raw.toBytes())));
  chunks.add(chunk('IEND', []));
  final png = BytesBuilder();
  png.add([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);
  png.add(chunks.toBytes());
  return png.toBytes();
}

List<int> ihdr(int n) {
  final b = BytesBuilder();
  b.add(u32(n));
  b.add(u32(n));
  b.addByte(8); // bit depth
  b.addByte(6); // color type: RGBA
  b.addByte(0); // compression
  b.addByte(0); // filter
  b.addByte(0); // interlace
  return b.toBytes();
}

List<int> chunk(String type, List<int> data) {
  final b = BytesBuilder();
  b.add(u32(data.length));
  final body = BytesBuilder()..add(type.codeUnits)..add(data);
  b.add(body.toBytes());
  b.add(u32(crc32(body.toBytes())));
  return b.toBytes();
}

List<int> u32(int v) => [
      (v >> 24) & 0xFF,
      (v >> 16) & 0xFF,
      (v >> 8) & 0xFF,
      v & 0xFF,
    ];

int crc32(List<int> bytes) {
  var c = 0xFFFFFFFF;
  for (final byte in bytes) {
    c ^= byte;
    for (int k = 0; k < 8; k++) {
      c = (c >> 1) ^ (0xEDB88320 & -(c & 1));
    }
  }
  return (c ^ 0xFFFFFFFF) & 0xFFFFFFFF;
}

/// Minimal PNG reader: 8-bit RGBA, non-interlaced, single IDAT assumed but
/// all IDATs are concatenated for safety.
Float32List? decodePng(String path) {
  final bytes = File(path).readAsBytesSync();
  if (bytes.length < 8) return null;
  var off = 8;
  int? w, h;
  List<int> idat = [];
  while (off + 8 <= bytes.length) {
    final len = (bytes[off] << 24) |
        (bytes[off + 1] << 16) |
        (bytes[off + 2] << 8) |
        bytes[off + 3];
    final type = String.fromCharCodes(bytes.sublist(off + 4, off + 8));
    final data = bytes.sublist(off + 8, off + 8 + len);
    if (type == 'IHDR') {
      w = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3];
      h = (data[4] << 24) | (data[5] << 16) | (data[6] << 8) | data[7];
      if (data[8] != 8 || data[9] != 6) return null;
    } else if (type == 'IDAT') {
      idat.addAll(data);
    } else if (type == 'IEND') {
      break;
    }
    off += 12 + len;
  }
  if (w == null || h == null || w != h) return null;
  final raw = zlib.decoder.convert(idat);
  final px = Float32List(w * h * 4);
  final stride = w * 4;
  var p = 0;
  for (int y = 0; y < h; y++) {
    final filter = raw[p++];
    if (filter != 0) return null; // this tool only writes filter type 0
    for (int i = 0; i < stride; i++) {
      px[y * stride + i] = raw[p++] / 255.0;
    }
  }
  return px;
}

// ---------------- ICO container (PNG-compressed entries) ---------------- //

void writeIco(String path, List<Float32List> images) {
  final b = BytesBuilder();
  b.add(u16(0)); // reserved
  b.add(u16(1)); // type: icon
  b.add(u16(images.length));
  final headerSize = 6 + 16 * images.length;
  var offset = headerSize;
  for (final img in images) {
    final dim = sqrt(img.length / 4).round();
    b.addByte(dim >= 256 ? 0 : dim); // width (0 = 256)
    b.addByte(dim >= 256 ? 0 : dim); // height
    b.addByte(0); // palette
    b.addByte(0); // reserved
    b.add(u16(1)); // planes
    b.add(u16(32)); // bpp
    final png = encodePngBytes(img, dim);
    b.add(u32(png.length));
    b.add(u32(offset));
    offset += png.length;
  }
  for (final img in images) {
    final dim = sqrt(img.length / 4).round();
    b.add(encodePngBytes(img, dim));
  }
  File(path).writeAsBytesSync(b.toBytes());
}

List<int> u16(int v) => [v & 0xFF, (v >> 8) & 0xFF];
