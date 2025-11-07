import logging
import sys
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]
NETWORK_OPT_ROOT = REPO_ROOT / "5g-network-optimization"
SERVICES_ROOT = NETWORK_OPT_ROOT / "services"

for path in (NETWORK_OPT_ROOT, SERVICES_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from services.logging_config import configure_logging

logger = logging.getLogger(__name__)

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


def find_assets(directory: Path, extensions: List[str]) -> List[Path]:
    assets = []
    for ext in extensions:
        assets.extend(sorted(directory.rglob(f"*.{ext}")))
    return assets


def add_image_page(c: canvas.Canvas, image_path: Path, caption: str):
    width, height = letter
    margin = 0.5 * inch
    available_height = height - 2 * margin - 0.5 * inch  # space for caption

    c.setFont("Helvetica", 12)
    c.drawCentredString(width / 2.0, margin / 2.0, caption)

    img_width, img_height = c.drawImage(
        str(image_path),
        margin,
        margin + 0.5 * inch,
        width=width - 2 * margin,
        preserveAspectRatio=True,
        anchor='n',
        mask='auto',
    )
    c.showPage()


def build_presentation_pdf():
    script_dir = Path(__file__).resolve().parents[1]
    assets_dir = script_dir / "presentation_assets"
    output_pdf = assets_dir / "overview.pdf"

    if not assets_dir.is_dir():
        logging.error("Presentation assets directory not found: %s", assets_dir)
        return

    image_extensions = ["png", "jpg", "jpeg"]
    images = find_assets(assets_dir, image_extensions)

    if not images:
        logging.error("No images found in %s", assets_dir)
        return

    c = canvas.Canvas(str(output_pdf), pagesize=letter)

    for image in images:
        caption_file = image.with_suffix(".txt")
        caption = caption_file.read_text().strip() if caption_file.exists() else ""
        add_image_page(c, image, caption)

    c.save()
    logger.info("Created %s", output_pdf)


if __name__ == "__main__":
    configure_logging()
    logger.info("Building presentation PDF")
    build_presentation_pdf()
