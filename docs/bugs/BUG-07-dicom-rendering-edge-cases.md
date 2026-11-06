# BUG-07: Window Width Division-by-Zero Risk & Redundant Disk I/O in DICOM Decoding

**Severity:** P3 (Low)  
**Component:** `apps/api/src/radar_api/main.py` & `apps/api/src/radar_api/dicom_preprocessing.py`  
**Found in:** Sprint 2 Audit  
**Type:** Mathematical Robustness & Performance Inefficiency

---

## 1. Description

### A. Window Width Division-by-Zero Risk in Slice Rendering
In [`apps/api/src/radar_api/main.py`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/api/src/radar_api/main.py) line 484-495:

```python
width = float(window_width)
level = float(window_center)
if width <= 0:
    raise ValueError("Invalid window width")
low, high = level - width / 2, level + width / 2
pixels = np.clip((pixels - low) / (high - low), 0, 1)
```

If an atypical DICOM file contains a tiny subnormal window width (e.g. `width = 1e-15`), `width <= 0` evaluates to `False`. However, when subtracting floating-point values, `high - low` truncates to `0.0`, triggering a division by zero (`RuntimeWarning: divide by zero encountered in divide`) and generating `NaN` pixel arrays.

Furthermore, `str(getattr(dataset, "PhotometricInterpretation", ""))` should be stripped (`.strip()`) to prevent trailing space mismatch against `"MONOCHROME1"`.

### B. Redundant Disk Reads in `decode_and_window()`
In [`apps/api/src/radar_api/dicom_preprocessing.py`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/api/src/radar_api/dicom_preprocessing.py) lines 51-57:

```python
header = dcmread(path, force=False, stop_before_pixels=True)
# ... checks ...
dataset = dcmread(path, force=False)
```

The function reads the file from disk twice: first stopping before pixels, then reading the entire dataset again. In high-throughput inference batches across hundreds of CT series, this doubles the filesystem I/O load.

---

## 2. Impact Analysis

- **Edge-Case Crash**: Abnormal CT window values cause `NaN` pixel arrays and Pillow PNG conversion failure (`HTTP 422: Stored CT slice could not be rendered`).
- **I/O Overhead**: Unnecessary read amplification on disk and network-mounted storage volumes.

---

## 3. Recommended Remediation

1. Enforce a minimum window width:
   ```python
   if width < 1.0 or not math.isfinite(width):
       raise ValueError("Window width must be at least 1.0")
   ```
2. Strip string comparison:
   ```python
   if str(getattr(dataset, "PhotometricInterpretation", "")).strip() == "MONOCHROME1":
       pixels = 1 - pixels
   ```
3. Read dataset once:
   ```python
   dataset = dcmread(path, force=False)
   # Check rows, columns, frames from dataset directly
   ```

