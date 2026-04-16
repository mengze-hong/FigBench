"""Start AcademicFigureGallery server."""
import sys
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent / "backend"
os.chdir(str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR))

if __name__ == "__main__":
    import uvicorn
    print("AcademicFigureGallery")
    print(f"http://localhost:8765\n")
    uvicorn.run("server:app", host="0.0.0.0", port=8765, log_level="info")
