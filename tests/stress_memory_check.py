"""
Memory Profiling and Rapid UI Cycle Stress Test for Music Grabber.
Runs 50 full cycles of MainWindow initialization, scanning mock tracks,
filtering, inspector inspection, and disposal to verify leak-free performance.
"""

import os
import gc
import sys
import json
import psutil

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt

# Headless / offscreen if needed
os.environ["QT_QPA_PLATFORM"] = "offscreen"


def run_memory_stress_test():
    app = QApplication.instance() or QApplication(sys.argv)
    proc = psutil.Process()

    import config
    import gui
    from gui import MainWindow
    from tests.test_gui import MockDownloadThread

    gui.DownloadThread = MockDownloadThread
    gui.is_ffmpeg_available = lambda: True
    QMessageBox.warning = staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes)
    QMessageBox.critical = staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Ok)

    win = MainWindow()
    win.api_id_input.setText("12345")
    win.api_hash_input.setText("hash123")
    win.channel_input.setText("@stress_channel")

    gc.collect()
    app.processEvents()
    baseline_rss_mb = proc.memory_info().rss / (1024 * 1024)
    print(f"[*] Initial Baseline RSS (Window open): {baseline_rss_mb:.2f} MB")

    snapshots = []
    num_cycles = 75

    for i in range(1, num_cycles + 1):
        # 1. Trigger scan
        win.start_scan()

        # 2. Feed scan results (40 tracks each cycle)
        tracks = [
            {
                "id": idx + (i * 100),
                "performer": f"Artist {idx}",
                "title": f"Title {idx}",
                "date": "2026-10-08",
                "already_exists": idx % 2 == 0,
                "filepath": f"/fake/path/{idx}.mp3",
                "bpm": "124",
                "key": "8A",
            }
            for idx in range(1, 40)
        ]
        win._on_scan_results(tracks)

        # 3. Filter tracks
        win._filter_tracks_text("Artist 1")
        win._filter_tracks_text("")

        # 4. Trigger inspector
        if hasattr(win, "track_inspector"):
            win.track_inspector.display_track(tracks[0])

        app.processEvents()

        if i in (1, 10, 25, 40, 50, 60, 75):
            gc.collect()
            app.processEvents()
            current_rss = proc.memory_info().rss / (1024 * 1024)
            delta = current_rss - baseline_rss_mb
            snapshots.append({
                "cycle": i,
                "rss_mb": round(current_rss, 2),
                "delta_mb": round(delta, 2),
            })
            print(f"Cycle {i:02d}: RSS = {current_rss:.2f} MB (Delta: {delta:+.2f} MB)")

    # 5. Clean up window
    win._cleanup_on_exit()
    win.close()
    win.deleteLater()
    app.processEvents()
    del win

    final_rss = proc.memory_info().rss / (1024 * 1024)
    total_delta = final_rss - baseline_rss_mb
    is_healthy = total_delta < 150.0  # Under 150MB across 75 heavy data injection cycles is stable for PyQt6

    result = {
        "baseline_rss_mb": round(baseline_rss_mb, 2),
        "final_rss_mb": round(final_rss, 2),
        "total_delta_mb": round(total_delta, 2),
        "cycles_completed": num_cycles,
        "is_healthy": is_healthy,
        "snapshots": snapshots,
    }

    out_path = os.path.join("night_qa", "metrics", "memory_profile.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\n[+] Memory Profile written to: {out_path}")
    print(f"[+] Total delta: {total_delta:.2f} MB. Healthy: {is_healthy}")


if __name__ == "__main__":
    run_memory_stress_test()
