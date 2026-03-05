#!/usr/bin/env python3
"""
Helper to measure crop coordinates from a TradingView screenshot.
Usage: python measure_crop.py <screenshot.png>
"""
import sys
from PIL import Image

if len(sys.argv) < 2:
    print("Usage: python measure_crop.py <screenshot.png>")
    sys.exit(1)

img_path = sys.argv[1]
img = Image.open(img_path)
width, height = img.size

print(f"Screenshot dimensions: {width}x{height}")
print()
print("Based on typical TradingView layout:")
print("  Left toolbar: ~55px")
print("  Top header: ~114px")
print("  Right panel (if visible): ~300-400px")
print()

# Suggest crop for 1308x768 output
target_w, target_h = 1308, 768

# Calculate crop assuming left toolbar and top header
crop_x = 55
crop_y = 114

# Available space after removing left/top
available_w = width - crop_x
available_h = height - crop_y

print(f"Available chart area: {available_w}x{available_h}")
print()

if available_w >= target_w and available_h >= target_h:
    print(f"✓ Sufficient space for {target_w}x{target_h} crop")
    print(f"Suggested crop: x={crop_x}, y={crop_y}, w={target_w}, h={target_h}")
else:
    print(f"✗ Not enough space for {target_w}x{target_h}")
    print(f"  Need to adjust target size or window size")
    # Suggest max possible
    max_w = min(available_w, target_w)
    max_h = min(available_h, target_h)
    print(f"  Max possible crop: {max_w}x{max_h}")
    
print()
print("To verify, you can test the crop:")
print(f"  from PIL import Image")
print(f"  img = Image.open('{img_path}')")
print(f"  cropped = img.crop(({crop_x}, {crop_y}, {crop_x + target_w}, {crop_y + target_h}))")
print(f"  cropped.save('test_crop.png')")
