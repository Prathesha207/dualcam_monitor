import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.main import app
from app.services.oak_camera_service import oak_camera_service
from app.services.recording_service import active_recordings
from app.schemas.camera_schema import CameraResponse


def run_tests():
    print("1. Testing app routes via OpenAPI...")
    paths = list(app.openapi()["paths"].keys())
    print(f"   Total registered API paths: {len(paths)}")

    # Assert NO ML / training / inference / roi routes are present
    for p in paths:
        assert not p.startswith("/video"), f"Unexpected video route: {p}"
        assert not p.startswith("/roi"), f"Unexpected roi route: {p}"
        assert not p.startswith("/debug"), f"Unexpected debug route: {p}"
        assert "inference" not in p, f"Unexpected inference route: {p}"
        assert "train" not in p, f"Unexpected train route: {p}"

    print("   ✓ Zero ML/inference/training/ROI routes verified in API!")

    # Assert clean REST camera and recording routes ARE present
    expected_routes = [
        "/health",
        "/api/system/shutdown",
        "/camera/create",
        "/camera/update/{camera_id}",
        "/camera/enable/{camera_id}",
        "/camera/disable/{camera_id}",
        "/camera/{camera_id}",
        "/camera/",
        "/camera/live-controls/{camera_id}",
        "/camera/storage-path",
        "/camera/browse-folder",
        "/recording/start",
        "/recording/stop",
        "/recording/status",
        "/oak/start",
        "/oak/stop",
        "/oak/stream",
        "/oak/snapshot",
        "/oak/health",
        "/oak/devices",
        "/oak/controls",
        "/oak/calibration",
    ]
    for er in expected_routes:
        assert er in paths, f"Missing expected route: {er}"

    # Verify no duplicate aliases exist
    assert "/camera/delete/{camera_id}" not in paths, "Unexpected duplicate delete route!"
    assert "/camera/basic-config-update" not in paths, "Unexpected basic-config-update route!"
    assert "/camera/config" not in paths, "Unexpected config route!"

    print("   ✓ All clean REST Camera & Recording routes verified present (zero duplicates)!")

    # Test camera service health response
    print("2. Testing oak_camera_service.health()...")
    health = oak_camera_service.health()
    print(f"   ✓ Health output: {health}")
    assert "running" in health
    assert "connected" in health
    assert "streaming" in health
    assert "mjpeg_thread" in health
    assert "inference_thread" not in health
    assert "inference_watchdog_thread" not in health
    print("   ✓ Camera health check verified completely free of ML threads!")

    # Test recording status
    print("3. Testing recording service...")
    assert len(active_recordings) == 0
    assert oak_camera_service._active_recording is None
    print("   ✓ Recording service verified ready and idle!")

    # Test database camera resolution
    print("4. Testing database camera resolution...")
    from app.core.database import SessionLocal
    from app.services import camera_service
    db = SessionLocal()
    try:
        active_cam = camera_service.get_camera_config(db)
        print(f"   ✓ Active camera config from database: {active_cam}")
    finally:
        db.close()

    print("\n=======================================================")
    print("       ALL CAMERA SERVICE SMOKE TESTS PASSED!          ")
    print("=======================================================")


if __name__ == "__main__":
    run_tests()
