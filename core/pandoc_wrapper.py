import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def run_pandoc(input_path: Path, output_path: Path, reference_doc: Path | None = None) -> None:
    """
    Execute Pandoc conversion from DOCX to HTML.
    """
    cmd = [
        "pandoc", 
        str(input_path), 
        "-f", "docx", 
        "-t", "html", 
        "--wrap=none", 
        "-s", 
        "-o", str(output_path)
    ]
    
    if reference_doc and reference_doc.exists():
        cmd.extend(["--reference-doc", str(reference_doc)])
        logger.info(f"Pandoc: Using reference doc {reference_doc.name}")

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"Pandoc: Converted {input_path.name} to HTML")
    except subprocess.CalledProcessError as e:
        logger.error(f"Pandoc failed: {e.stderr}")
        raise
