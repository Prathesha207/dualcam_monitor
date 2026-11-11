import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models.camera_model import Camera
from app.schemas.camera_schema import CameraCreate, CameraResponse, CameraUpdate
from app.services import camera_service
from app.schemas.camera_live_control_schema import CameraLiveControl
from app.services.oak_camera_service import oak_camera_service
from app.services.realtime_log_service import realtime_log_service
from app.services.camera_limits_service import compute_camera_control_limits

logger = logging.getLogger("camera-api")

router = APIRouter()


@router.post("/create", response_model=CameraResponse)
def create_camera(data: CameraCreate, db: Session = Depends(get_db)):
    try:
        return camera_service.create_camera(db, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API ERROR] POST /camera/create: {e}", exc_info=True)
        realtime_log_service.add_log("camera", "CRASH", f"Create camera failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Internal error creating camera: {e}")


@router.put("/update/{camera_id}", response_model=CameraResponse)
def update_camera(camera_id: int, data: CameraUpdate, db: Session = Depends(get_db)):
    try:
        inst = oak_camera_service.get_instance(camera_id)
        is_rec = bool(getattr(inst, "is_recording", False) or getattr(inst, "_active_recording", None) is not None)
        if is_rec:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot edit camera settings while recording is active on camera {camera_id}. Stop recording first."
            )
        return camera_service.update_camera_partial(db, camera_id, data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API ERROR] PUT /camera/update/{camera_id}: {e}", exc_info=True)
        realtime_log_service.add_log("camera", "CRASH", f"Update camera {camera_id} failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Internal error updating camera: {e}")


@router.post("/enable/{camera_id}", response_model=CameraResponse)
def enable_camera(camera_id: int, db: Session = Depends(get_db)):
    try:
        return camera_service.enable_camera(db, camera_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API ERROR] POST /camera/enable/{camera_id}: {e}", exc_info=True)
        realtime_log_service.add_log("camera", "CRASH", f"Enable camera {camera_id} failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Internal error enabling camera: {e}")


@router.post("/disable/{camera_id}", response_model=CameraResponse)
async def disable_camera(camera_id: int, db: Session = Depends(get_db)):
    try:
        try:
            await oak_camera_service.stop(camera_id=camera_id)
        except Exception as stop_err:
            logger.warning(f"[DISABLE] Hardware stop failed on disable {camera_id}: {stop_err}")
        return camera_service.disable_camera(db, camera_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API ERROR] POST /camera/disable/{camera_id}: {e}", exc_info=True)
        realtime_log_service.add_log("camera", "CRASH", f"Disable camera {camera_id} failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Internal error disabling camera: {e}")


@router.delete("/{camera_id}")
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    try:
        return camera_service.delete_camera(db, camera_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API ERROR] DELETE /camera/{camera_id}: {e}", exc_info=True)
        realtime_log_service.add_log("camera", "CRASH", f"Delete camera {camera_id} failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Internal error deleting camera: {e}")


@router.get("/", response_model=List[CameraResponse])
def get_cameras(db: Session = Depends(get_db)):
    try:
        return camera_service.get_cameras(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API ERROR] GET /camera/: {e}", exc_info=True)
        realtime_log_service.add_log("camera", "CRASH", f"Get cameras failed: {e}", "error")
        raise HTTPException(status_code=500, detail=f"Internal error fetching cameras: {e}")


@router.get("/{camera_id}/limits")
def get_camera_limits_endpoint(camera_id: int, db: Session = Depends(get_db)):
    """Return dynamic three-zone limits for camera controls based on configured FPS and resolution."""
    try:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        fps = camera.fps if camera else 30
        resolution = camera.resolution if camera else "1920x1080"
        inst = oak_camera_service.get_instance(camera_id)
        if inst and getattr(inst, "_configured_fps", 0) > 0:
            fps = inst._configured_fps
        return compute_camera_control_limits(camera_id=camera_id, configured_fps=fps, resolution=resolution)
    except Exception as e:
        logger.error(f"[API ERROR] GET /camera/limits/{camera_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to compute limits: {e}")


@router.patch("/live-controls/{camera_id}")
def update_live_controls(
    camera_id: int,
    data: CameraLiveControl,
    db: Session = Depends(get_db)
):
    logger.info(
        f"[LIVE CONTROLS] camera_id={camera_id} | "
        f"exposure={data.exposure}, gain={data.gain}, focus={data.focus}, "
        f"brightness={data.brightness}, contrast={data.contrast}"
    )

    inst = oak_camera_service.get_instance(camera_id)
    is_rec = bool(getattr(inst, "is_recording", False) or getattr(inst, "_active_recording", None) is not None)
    if is_rec:
        logger.warning(f"[LIVE CONTROLS] Rejected — camera {camera_id} controls are locked while recording is active")
        return {"status": "error", "message": f"Camera {camera_id} controls are disabled while recording is active"}

    try:
        af = data.auto_focus if data.auto_focus is not None else data.autoFocus
        ae = data.auto_exposure if data.auto_exposure is not None else data.autoExposure

        # 1. If camera pipeline is running (streaming), apply controls live to hardware sensor!
        if inst.is_running:
            inst.update_controls(
                exposure=data.exposure,
                gain=data.gain,
                focus=data.focus,
                brightness=data.brightness,
                contrast=data.contrast,
                auto_focus=af,
                auto_exposure=ae,
                control_mode=data.control_mode,
            )

        # 2. Persist controls to DB so settings are remembered
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if camera:
            if data.exposure is not None:
                camera.exposure = data.exposure
            if data.gain is not None:
                camera.gain = data.gain
            if data.focus is not None:
                camera.focus = data.focus
            if data.brightness is not None:
                camera.brightness = data.brightness
            if data.contrast is not None:
                camera.contrast = data.contrast
            if data.control_mode is not None:
                camera.control_mode = data.control_mode
            if af is not None:
                camera.auto_focus = af
            if ae is not None:
                camera.auto_exposure = ae
            db.commit()

        logger.info("[LIVE CONTROLS] Applied and saved to database successfully")
        return {"status": "success", "message": "Controls applied and saved to database"}

    except Exception as e:
        logger.error(f"[LIVE CONTROLS] Failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


class StoragePathUpdate(BaseModel):
    path: Optional[str] = None


class StoragePathResponse(BaseModel):
    storage_path: str
    default_path: str
    status: str = "success"


class BrowseFolderRequest(BaseModel):
    initial_dir: Optional[str] = None


@router.get("/storage-path", response_model=StoragePathResponse)
def get_storage_path():
    try:
        from app.core.app_paths import get_configured_storage_dir, get_desktop_dir
        return StoragePathResponse(
            storage_path=str(get_configured_storage_dir()),
            default_path=str(get_desktop_dir()),
            status="success",
        )
    except Exception as e:
        logger.error(f"[API ERROR] GET /camera/storage-path: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/storage-path", response_model=StoragePathResponse)
def set_storage_path(data: StoragePathUpdate):
    try:
        from app.core.app_paths import set_configured_storage_dir, get_desktop_dir
        final_path = set_configured_storage_dir(data.path)
        realtime_log_service.add_log(
            "camera",
            "CONFIG",
            f"Storage path updated: {final_path}",
            "success",
        )
        return StoragePathResponse(
            storage_path=final_path,
            default_path=str(get_desktop_dir()),
            status="success",
        )
    except Exception as e:
        logger.error(f"[API ERROR] POST /camera/storage-path: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/browse-folder")
def browse_folder(data: Optional[BrowseFolderRequest] = None):
    try:
        import os
        import sys
        import subprocess
        from app.core.app_paths import get_configured_storage_dir, get_desktop_dir

        req_dir = data.initial_dir if data and data.initial_dir else None
        start_dir = req_dir or str(get_configured_storage_dir()) or str(get_desktop_dir())

        selected_path = None

        # 1. Primary: Run Tkinter in an isolated STA Python subprocess (never freezes FastAPI or hangs COM)
        py_code = (
            "import sys, os\n"
            "try:\n"
            "    import tkinter as tk\n"
            "    from tkinter import filedialog\n"
            "    root = tk.Tk()\n"
            "    root.withdraw()\n"
            "    root.wm_attributes('-topmost', 1)\n"
            "    root.lift()\n"
            "    root.focus_force()\n"
            f"    chosen = filedialog.askdirectory(initialdir={repr(start_dir)}, title='Select Directory for Recordings')\n"
            "    root.destroy()\n"
            "    if chosen:\n"
            "        sys.stdout.write(os.path.normpath(chosen))\n"
            "except Exception:\n"
            "    pass\n"
        )

        try:
            proc = subprocess.run(
                [sys.executable, "-c", py_code],
                capture_output=True,
                text=True,
                timeout=120,
            )
            out = proc.stdout.strip()
            if out and os.path.exists(out):
                selected_path = out
        except Exception as py_err:
            logger.warning(f"[BROWSE] Python dialog subprocess error: {py_err}")

        # 2. Windows Fallback: Native Windows Forms FolderBrowserDialog via PowerShell
        if not selected_path and sys.platform == "win32":
            try:
                ps_script = (
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                    f"$d.SelectedPath = '{start_dir}'; "
                    "$d.Description = 'Select Directory for Camera Recordings'; "
                    "$d.ShowNewFolderButton = $true; "
                    "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $d.SelectedPath }"
                )
                proc = subprocess.run(
                    ["powershell", "-NoProfile", "-STA", "-Command", ps_script],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                out = proc.stdout.strip()
                if out and os.path.exists(out):
                    selected_path = out
            except Exception as ps_err:
                logger.warning(f"[BROWSE] PowerShell dialog fallback error: {ps_err}")

        # 3. Linux Native Dialogs: zenity (GNOME/Ubuntu) or kdialog (KDE Plasma)
        if not selected_path and sys.platform.startswith("linux"):
            import shutil
            if shutil.which("zenity"):
                try:
                    proc = subprocess.run(
                        [
                            "zenity",
                            "--file-selection",
                            "--directory",
                            f"--filename={start_dir.rstrip('/')}/",
                            "--title=Select Directory for Recordings",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    out = proc.stdout.strip()
                    if out and os.path.exists(out):
                        selected_path = out
                except Exception as z_err:
                    logger.warning(f"[BROWSE] Linux zenity dialog error: {z_err}")
            elif shutil.which("kdialog"):
                try:
                    proc = subprocess.run(
                        [
                            "kdialog",
                            "--getexistingdirectory",
                            start_dir,
                            "--title",
                            "Select Directory for Recordings",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    out = proc.stdout.strip()
                    if out and os.path.exists(out):
                        selected_path = out
                except Exception as k_err:
                    logger.warning(f"[BROWSE] Linux kdialog dialog error: {k_err}")

        if selected_path:
            norm_path = os.path.normpath(selected_path)
            return {"path": norm_path, "canceled": False}
        return {"path": None, "canceled": True}
    except Exception as e:
        logger.error(f"[API ERROR] POST /camera/browse-folder: {e}", exc_info=True)
        return {"path": None, "canceled": True, "error": str(e)}
