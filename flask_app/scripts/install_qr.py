"""
Install a QR image into the Flask app static images folder as 'gcash_qr.png'.
Usage:
    python scripts\install_qr.py path\to\your_qr_image.png

This will copy the provided image to:
    flask_app/static/images/gcash_qr.png

If the destination folder doesn't exist it will be created.
"""
import sys
import os
import shutil

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts\\install_qr.py <path-to-qr-image>")
        sys.exit(1)

    src = sys.argv[1]
    if not os.path.exists(src):
        print(f"Source file does not exist: {src}")
        sys.exit(1)

    dst_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'images')
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, 'gcash_qr.png')

    try:
        shutil.copy2(src, dst)
        print(f"Copied {src} -> {dst}")
    except Exception as e:
        print(f"Failed to copy: {e}")
        sys.exit(2)

if __name__ == '__main__':
    main()
