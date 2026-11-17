"""
End-to-end verification script for simultaneous Color + 16-bit Depth recording.
Verifies that:
1. Normal video and depth video are written into the exact same session folder.
2. Formats (MP4, AVI, MKV) produce matching preview videos.
3. 16-bit Lossless Raw Depth video (FFV1 gray16le) preserves bit-exact millimeter Z values (max_diff == 0).
4. session.json correctly documents color and depth clips.
"""

import os
import shutil
import time
import av
import cv2
import numpy as np

from app.services.recording_service import start_recording, stop_recording, active_recordings


def run_test_for_format(fmt: str, test_root: str):
    print(f"\n=======================================================")
    print(f"Testing Color + Depth Recording for format: {fmt}")
    print(f"=======================================================")

    session_id = f"test_depth_{fmt.lower()}_{int(time.time())}"
    width, height = 640, 480
    fps = 30.0

    session_dir = start_recording(
        session_id=session_id,
        width=width,
        height=height,
        fps=fps,
        root_path=test_root,
        recording_format=fmt,
        camera_id=1,
        camera_name="TestCam",
        clip_duration_minutes=1,
        record_depth=True,
    )

    print(f"[1] Session started at: {session_dir}")
    session = active_recordings.get(session_id)
    assert session is not None, "Failed to get active recording session"

    # Generate synthetic color frame and known 16-bit depth pattern
    num_frames = 20
    # Depth pattern: values in millimeters from 500mm to 5500mm
    known_depth = np.zeros((height, width), dtype=np.uint16)
    known_depth[100:200, 100:200] = 1250  # 1.25 meters
    known_depth[250:350, 250:350] = 2780  # 2.78 meters
    known_depth[380:450, 380:450] = 4500  # 4.50 meters

    color_frame = np.zeros((height, width, 3), dtype=np.uint8)
    color_frame[:, :] = [40, 120, 200]

    for i in range(num_frames):
        session.add_dual_frame(color_frame, known_depth)
        time.sleep(0.01)

    print(f"[2] Pushed {num_frames} dual frames (color + depth)")
    time.sleep(0.5)

    res = stop_recording(session_id)
    print(f"[3] Session stopped: {res.get('filename')}")
    print(f"    Total color frames: {res.get('frames_written')}")
    print(f"    Total depth frames: {res.get('depth_frames_written')}")
    print(f"    Has depth: {res.get('has_depth')}")

    # Verify files inside session_dir
    files = os.listdir(session_dir)
    print(f"[4] Files in session folder: {files}")

    ext = ".avi" if fmt == "AVI" else (".mkv" if fmt == "FFV1" or fmt == "MKV" else ".mp4")

    color_files = [f for f in files if f.endswith(ext) and "depth" not in f and not f.endswith("_temp" + ext)]
    depth_raw_files = [f for f in files if "depth_raw" in f and f.endswith(".mkv")]
    depth_preview_files = [f for f in files if "depth_preview" in f and f.endswith(ext)]

    assert len(color_files) >= 1, f"Missing color video file with ext {ext} in {files}"
    assert len(depth_raw_files) >= 1, f"Missing 16-bit depth raw MKV file in {files}"
    assert len(depth_preview_files) >= 1, f"Missing depth preview file with ext {ext} in {files}"

    color_file = os.path.join(session_dir, color_files[0])
    depth_raw_file = os.path.join(session_dir, depth_raw_files[0])
    depth_prev_file = os.path.join(session_dir, depth_preview_files[0])

    print(f"    Color file        : {color_files[0]} ({os.path.getsize(color_file)} bytes)")
    print(f"    Depth Raw (16-bit): {depth_raw_files[0]} ({os.path.getsize(depth_raw_file)} bytes)")
    print(f"    Depth Preview     : {depth_preview_files[0]} ({os.path.getsize(depth_prev_file)} bytes)")

    # Decode Depth Raw file with PyAV and verify exact millimeters Z value preservation
    container = av.open(depth_raw_file)
    stream = container.streams.video[0]
    assert stream.pix_fmt == "gray16le", f"Expected pix_fmt gray16le, got {stream.pix_fmt}"

    decoded_frames = 0
    max_diff_seen = 0
    for frame in container.decode(video=0):
        depth_arr = frame.to_ndarray()
        assert depth_arr.dtype == np.uint16, f"Expected uint16 dtype, got {depth_arr.dtype}"
        assert depth_arr.shape == (height, width), f"Expected shape ({height}, {width}), got {depth_arr.shape}"

        diff = np.max(np.abs(known_depth.astype(int) - depth_arr.astype(int)))
        if diff > max_diff_seen:
            max_diff_seen = diff
        decoded_frames += 1

    container.close()
    print(f"[5] Decoded {decoded_frames} depth frames from {depth_raw_files[0]}")
    print(f"    Bit-exact difference between ground truth and recorded video: {max_diff_seen}")
    assert max_diff_seen == 0, f"Z-values were corrupted! Max diff: {max_diff_seen}"
    print(f"    >>> ZERO ERROR! All 16-bit millimeter Z values are 100% BIT-EXACT! <<<")

    # Verify session.json
    json_path = os.path.join(session_dir, "session.json")
    assert os.path.exists(json_path), "session.json missing"
    import json
    with open(json_path, "r", encoding="utf-8") as jf:
        meta = json.load(jf)
    assert meta.get("has_depth") is True
    assert "clips" in meta and len(meta["clips"]) > 0
    clip0 = meta["clips"][0]
    assert "depth_raw_filename" in clip0
    assert "depth_preview_filename" in clip0
    print(f"[6] Verified session.json metadata successfully!")
    print(f"[SUCCESS] Format {fmt} passed all depth recording tests!\n")


def main():
    test_root = os.path.join(os.path.dirname(__file__), "test_recordings_output")
    os.makedirs(test_root, exist_ok=True)
    try:
        # Test MP4
        run_test_for_format("MP4", test_root)

        # Test AVI
        run_test_for_format("AVI", test_root)

        # Test MKV (FFV1)
        run_test_for_format("MKV", test_root)

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED! Depth + Color recording verified in all formats!")
        print("=" * 60)
    finally:
        if os.path.exists(test_root):
            try:
                shutil.rmtree(test_root)
                print("[CLEANUP] Removed temporary test recordings directory.")
            except Exception:
                pass


if __name__ == "__main__":
    main()
