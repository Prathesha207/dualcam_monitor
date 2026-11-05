import depthai as dai
import time
import numpy as np

print("===================================================================")
print("  LUXONIS OAK4 (SONY IMX586) COMPLETE HARDWARE LIMITS BENCHMARK   ")
print("===================================================================\n")

with dai.Device() as device:
    pipeline = dai.Pipeline(device)
    cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
    
    raw_out = cam.requestOutput((1280, 720), type=dai.ImgFrame.Type.NV12, fps=30)
    q_out = raw_out.createOutputQueue(maxSize=2, blocking=False)
    q_ctrl = cam.inputControl.createInputQueue(maxSize=4, blocking=False)
    
    pipeline.start()
    time.sleep(1.0)
    print("Camera initialized and streaming!\n")

    # Helper function to send control and get fresh frame
    def send_and_get(ctrl_obj):
        q_ctrl.send(ctrl_obj)
        time.sleep(0.35)
        q_out.tryGetAll()  # Drain old frames
        return q_out.get() # Get latest frame

    # =========================================================================
    # 1. ISO GAIN (Extreme Low -> Extreme High)
    # =========================================================================
    print("┌──────────────────────────────────────────────────────────────┐")
    print("│ 1. ISO GAIN LIMITS TEST (50 to 25,600)                       │")
    print("├──────────────────┬──────────────────┬────────────────────────┤")
    print("│  Requested ISO   │ Sensor Accepted  │ Status                 │")
    print("├──────────────────┼──────────────────┼────────────────────────┤")
    for iso in [50, 100, 200, 400, 800, 1600, 3200, 6400, 10000, 12800, 25600]:
        ctrl = dai.CameraControl()
        ctrl.setManualExposure(10000, iso)
        pkt = send_and_get(ctrl)
        actual_iso = pkt.getSensitivity()
        status = "Accepted" if actual_iso == iso else (f"Clamped to {actual_iso}" if actual_iso < iso else f"Shifted ({actual_iso})")
        print(f"│  {iso:<15} │  {actual_iso:<15} │ {status:<22} │")
    print("└──────────────────┴──────────────────┴────────────────────────┘\n")

    # Reset to baseline exposure
    ctrl = dai.CameraControl()
    ctrl.setManualExposure(10000, 400)
    send_and_get(ctrl)

    # =========================================================================
    # 2. EXPOSURE TIME (0.01 ms to 1000 ms) & FPS Impact
    # =========================================================================
    print("┌──────────────────────────────────────────────────────────────┐")
    print("│ 2. EXPOSURE TIME TEST (10 µs to 1,000,000 µs)                │")
    print("├────────────────────┬────────────────────┬────────────────────┤")
    print("│ Requested Exposure │  Sensor Reported   │ Behavior           │")
    print("├────────────────────┼────────────────────┼────────────────────┤")
    for us in [10, 100, 500, 1000, 5000, 10000, 20000, 33000, 50000, 100000, 250000, 500000, 1000000]:
        ctrl = dai.CameraControl()
        ctrl.setManualExposure(us, 400)
        pkt = send_and_get(ctrl)
        actual_us = int(pkt.getExposureTime().total_seconds() * 1_000_000)
        ms_req = us / 1000.0
        ms_act = actual_us / 1000.0
        note = "Fast shutter" if actual_us <= 10000 else ("Max for 30 FPS" if actual_us <= 33333 else "Long exp (drops FPS)")
        print(f"│ {ms_req:>7.2f} ms ({us:>6} µs) │ {ms_act:>7.2f} ms ({actual_us:>6} µs) │ {note:<18} │")
    print("└────────────────────┴────────────────────┴────────────────────┘\n")

    # Reset to baseline exposure
    ctrl = dai.CameraControl()
    ctrl.setManualExposure(10000, 400)
    send_and_get(ctrl)

    # =========================================================================
    # 3. LENS FOCUS (Out-of-range & in-range testing)
    # =========================================================================
    print("┌──────────────────────────────────────────────────────────────┐")
    print("│ 3. LENS FOCUS TEST (-10 to 300)                              │")
    print("├──────────────────┬──────────────────┬────────────────────────┤")
    print("│ Requested Focus  │ Lens Position    │ Driver Result          │")
    print("├──────────────────┼──────────────────┼────────────────────────┤")
    for f in [-10, 0, 30, 64, 100, 128, 180, 220, 255, 270, 300]:
        ctrl = dai.CameraControl()
        try:
            ctrl.setManualFocus(f)
            pkt = send_and_get(ctrl)
            pos = pkt.getLensPosition()
            print(f"│  {f:<15} │  {pos:<15} │ Accepted (8-bit VCM)   │")
        except Exception as err:
            err_short = str(err).split(":")[0].strip() or "Rejected by API"
            print(f"│  {f:<15} │  {'Rejected':<15} │ {err_short[:22]:<22} │")
    print("└──────────────────┴──────────────────┴────────────────────────┘\n")

    # =========================================================================
    # 4. HARDWARE BRIGHTNESS (-100 to +100)
    # =========================================================================
    print("┌──────────────────────────────────────────────────────────────┐")
    print("│ 4. HARDWARE BRIGHTNESS TEST (-100 to +100)                   │")
    print("├──────────────────┬──────────────────┬────────────────────────┤")
    print("│ Requested Value  │ Mean Pixel Luma  │ Hardware Response      │")
    print("├──────────────────┼──────────────────┼────────────────────────┤")
    for b in [-100, -50, -20, -10, -5, 0, 5, 10, 20, 50, 100]:
        ctrl = dai.CameraControl()
        try:
            ctrl.setBrightness(b)
            pkt = send_and_get(ctrl)
            luma = float(np.mean(pkt.getCvFrame()))
            print(f"│  {b:+4d}            │  {luma:6.1f} / 255    │ Luma measured          │")
        except Exception as err:
            print(f"│  {b:+4d}            │  {'Error':<15} │ Rejected by driver     │")
    print("└──────────────────┴──────────────────┴────────────────────────┘\n")

    # Reset brightness
    ctrl = dai.CameraControl()
    ctrl.setBrightness(0)
    send_and_get(ctrl)

    # =========================================================================
    # 5. HARDWARE CONTRAST (-100 to +100)
    # =========================================================================
    print("┌──────────────────────────────────────────────────────────────┐")
    print("│ 5. HARDWARE CONTRAST TEST (-100 to +100)                     │")
    print("├──────────────────┬──────────────────┬────────────────────────┤")
    print("│ Requested Value  │ Contrast (StdDev)│ Hardware Response      │")
    print("├──────────────────┼──────────────────┼────────────────────────┤")
    for c in [-100, -50, -20, -10, -5, 0, 5, 10, 20, 50, 100]:
        ctrl = dai.CameraControl()
        try:
            ctrl.setContrast(c)
            pkt = send_and_get(ctrl)
            std_dev = float(np.std(pkt.getCvFrame()))
            print(f"│  {c:+4d}            │  {std_dev:6.1f}          │ Contrast measured      │")
        except Exception as err:
            print(f"│  {c:+4d}            │  {'Error':<15} │ Rejected by driver     │")
    print("└──────────────────┴──────────────────┴────────────────────────┘\n")

    print("Benchmark complete!")
