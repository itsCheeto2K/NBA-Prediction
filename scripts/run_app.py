import sys
from pathlib import Path
import uvicorn

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    print("================================================================")
    print("🏀 Starting NBA Props Prediction Web Dashboard (Linear Theme)...")
    print("📍 URL: http://localhost:8000")
    print("📖 API Documentation: http://localhost:8000/docs")
    print("================================================================")
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=False)
