#!/usr/bin/env python3
"""
Deterministic Synthetic Brain CT DICOM Fixture Generator (RDA-4).

Generates 5 de-identified, synthetic axial cranial CT slices in DICOM Part 10
Explicit VR Little Endian format for the RADAR AI prototype viewer.

Contains ZERO real patient data. All pixel data is mathematically synthesized
using standard Hounsfield Unit (HU) attenuation profiles for cranial structures:
  - Air outside head:       -1000 HU
  - Scalp / soft tissue:      +30 HU
  - Calvarium (skull bone):  +950 HU
  - Diploe / trabecular:     +450 HU
  - Subarachnoid CSF ring:    +10 HU
  - Cerebral cortex (gray):   +38 HU
  - White matter:             +28 HU
  - Basal ganglia / thalami:  +36 HU
  - Ventricular system (CSF):  +8 HU
  - Falx cerebri / dura:      +50 HU
  - Simulated acute ICH:      +74 HU (with perihematomal edema rim at +20 HU)

Prototyping only — NOT FOR CLINICAL USE.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

LONG_LENGTH_VRS = {"OB", "OD", "OF", "OL", "OW", "SQ", "UC", "UN", "UR", "UT"}


def encode_element(group: int, element: int, vr: str, raw_value: bytes) -> bytes:
    """Encode a single DICOM Explicit VR Little Endian element."""
    if len(raw_value) % 2 != 0:
        pad_byte = b"\x00" if vr in ("UI", "OB", "OW", "UN") else b" "
        raw_value = raw_value + pad_byte

    header = struct.pack("<HH2s", group, element, vr.encode("ascii"))
    if vr in LONG_LENGTH_VRS:
        return header + struct.pack("<HI", 0, len(raw_value)) + raw_value
    return header + struct.pack("<H", len(raw_value)) + raw_value


def encode_str(group: int, element: int, vr: str, text: str) -> bytes:
    raw = text.encode("ascii")
    if len(raw) % 2 != 0:
        pad = b"\x00" if vr == "UI" else b" "
        raw += pad
    return encode_element(group, element, vr, raw)


def encode_us(group: int, element: int, value: int) -> bytes:
    return encode_element(group, element, "US", struct.pack("<H", value))


def encode_ul(group: int, element: int, value: int) -> bytes:
    return encode_element(group, element, "UL", struct.pack("<I", value))


def hu_to_stored(hu: float, intercept: float = -1024.0) -> int:
    """Convert Hounsfield Unit (HU) to unsigned 16-bit stored pixel value."""
    val = int(round(hu - intercept))
    return max(0, min(65535, val))


def pseudo_noise(x: int, y: int, slice_idx: int) -> float:
    """Deterministic spatial micro-texture (~ +/- 2.5 HU) for realistic CT grain."""
    v = math.sin(x * 12.9898 + y * 78.233 + slice_idx * 43.123) * 43758.5453
    frac = v - math.floor(v)
    return (frac - 0.5) * 5.0


def synthesize_axial_brain_slice(
    rows: int,
    cols: int,
    slice_idx: int,
    z_mm: float,
    has_ich: bool,
    ich_scale: float = 1.0,
) -> bytes:
    """Synthesize a 2D axial brain CT slice with calibrated HU structures."""
    cx = cols / 2.0
    cy = rows / 2.0

    # Cranial contour scales slightly with Z level
    z_factor = 1.0 - abs(z_mm) * 0.004
    rx_outer = cols * 0.38 * z_factor
    ry_outer = rows * 0.44 * z_factor

    skull_thickness = 0.085
    scalp_thickness = 0.035
    csf_rim_thickness = 0.035

    pixels = bytearray(rows * cols * 2)
    offset = 0

    for y in range(rows):
        dy = (y - cy) / ry_outer
        for x in range(cols):
            dx = (x - cx) / rx_outer
            # Slight anterior frontal tapering
            anterior_taper = 1.0 + 0.08 * dy
            r2 = (dx * anterior_taper) ** 2 + dy**2
            r = math.sqrt(r2)
            noise = pseudo_noise(x, y, slice_idx)

            if r > 1.0 + scalp_thickness:
                # Extracranial air
                hu = -1000.0
            elif r > 1.0:
                # Scalp / subcutaneous tissue
                hu = 32.0 + noise
            elif r > 1.0 - skull_thickness:
                # Calvarium bone (outer table, diploe, inner table)
                skull_pos = (1.0 - r) / skull_thickness
                if 0.35 < skull_pos < 0.65:
                    hu = 520.0 + noise * 4.0  # Diploic space
                else:
                    hu = 980.0 + noise * 6.0  # Cortical bone table
                # Frontal sinus air cell at lower Z slices anteriorly
                if z_mm <= -5.0 and dy < -0.75 and abs(dx) < 0.16 and 0.25 < skull_pos < 0.78:
                    hu = -920.0
            elif r > 1.0 - skull_thickness - csf_rim_thickness:
                # Subarachnoid CSF space + cortical sulci
                angle = math.atan2(dy, dx)
                sulcus_wave = math.sin(angle * 18.0 + slice_idx * 0.7)
                if sulcus_wave > 0.35:
                    hu = 11.0 + noise * 0.5  # Sulcal CSF
                else:
                    hu = 39.0 + noise  # Outer cortical ribbon
            else:
                # Intracranial brain parenchyma
                # Differentiate cortical gray matter ribbon vs deep white matter
                inner_r = r / (1.0 - skull_thickness - csf_rim_thickness)
                angle = math.atan2(dy, dx)
                gyral_mod = 0.06 * math.sin(angle * 16.0 + slice_idx)

                if inner_r > 0.80 + gyral_mod:
                    hu = 39.0 + noise  # Cerebral cortex (gray matter)
                else:
                    hu = 28.0 + noise  # White matter (centrum semiovale / corona radiata)

                # Deep gray nuclei (basal ganglia & thalami) around Z = -5 to +8 mm
                if -6.0 <= z_mm <= 8.0:
                    # Lentiform nucleus (left & right)
                    for side in (-1.0, 1.0):
                        bg_dx = (dx - side * 0.23) / 0.13
                        bg_dy = (dy - (-0.04)) / 0.18
                        if bg_dx**2 + bg_dy**2 <= 1.0:
                            hu = 36.5 + noise
                    # Thalamus (medial posterior to basal ganglia)
                    for side in (-1.0, 1.0):
                        th_dx = (dx - side * 0.12) / 0.10
                        th_dy = (dy - 0.12) / 0.13
                        if th_dx**2 + th_dy**2 <= 1.0:
                            hu = 36.0 + noise

                # Ventricular system (CSF ~ 8 HU)
                if -5.0 <= z_mm <= 9.0:
                    # Anterior horns & bodies of lateral ventricles
                    for side in (-1.0, 1.0):
                        v_dx = (dx - side * 0.095) / 0.065
                        v_dy = (dy - (-0.12)) / 0.16
                        # Slight outward curve
                        curve_dx = v_dx - side * 0.6 * (v_dy**2)
                        if curve_dx**2 + v_dy**2 <= 1.0:
                            hu = 8.0 + noise * 0.4
                        # Choroid plexus calcification focus posteriorly
                        cp_dx = (dx - side * 0.13) / 0.025
                        cp_dy = (dy - 0.18) / 0.025
                        if cp_dx**2 + cp_dy**2 <= 1.0 and z_mm <= 3.0:
                            hu = 165.0 + noise * 2.0

                    # Third ventricle (midline slit)
                    if abs(dx) < 0.018 and -0.02 < dy < 0.16 and z_mm <= 4.0:
                        hu = 8.0 + noise * 0.3

                # Posterior fossa / cerebellum structures on lower slices
                if z_mm <= -8.0:
                    if dy > 0.05:
                        # Fourth ventricle in midline
                        if (dx / 0.06) ** 2 + ((dy - 0.18) / 0.06) ** 2 <= 1.0:
                            hu = 8.0 + noise * 0.4
                        # Petrous temporal bone ridges laterally
                        if abs(dx) > 0.32 and -0.08 < dy < 0.22:
                            hu = 780.0 + noise * 5.0

                # Interhemispheric fissure & falx cerebri along midline
                if abs(dx) < 0.012 and (dy < -0.22 or dy > 0.25 or z_mm > 6.0):
                    hu = 48.0 + noise

                # Simulated Left Basal Ganglia / Parenchymal Acute Hemorrhage (Radiological right side of image = patient left, dx > 0)
                if has_ich:
                    # Radiological convention: patient's left is at positive X (viewer's right)
                    ich_cx = 0.24
                    ich_cy = -0.03
                    ich_rx = 0.135 * ich_scale
                    ich_ry = 0.165 * ich_scale

                    ldx = (dx - ich_cx) / ich_rx
                    ldy = (dy - ich_cy) / ich_ry
                    lesion_ang = math.atan2(ldy, ldx)
                    irregularity = 1.0 + 0.12 * math.sin(lesion_ang * 5.0) + 0.08 * math.cos(lesion_ang * 3.0)
                    lesion_r = math.sqrt(ldx**2 + ldy**2) / irregularity

                    if lesion_r <= 1.0:
                        # Acute clot core (68 to 82 HU)
                        core_profile = 78.0 - 10.0 * (lesion_r**2)
                        hu = core_profile + noise * 1.2
                    elif lesion_r <= 1.38:
                        # Perihematomal hypodense edema halo (~ 18-22 HU)
                        blend = (lesion_r - 1.0) / 0.38
                        edema_hu = 19.0 + noise * 0.8
                        hu = edema_hu * (1.0 - blend) + hu * blend

            stored = hu_to_stored(hu)
            struct.pack_into("<H", pixels, offset, stored)
            offset += 2

    return bytes(pixels)


def build_dicom_part10(
    slice_idx: int,
    z_mm: float,
    slice_id: str,
    image_asset_id: str,
    has_ich: bool,
    ich_scale: float,
    rows: int = 256,
    cols: int = 256,
) -> bytes:
    """Build a complete DICOM Part 10 byte stream for a single CT slice."""
    sop_class_uid = "1.2.840.10008.5.1.4.1.1.2"
    study_uid = "1.2.826.0.1.3680043.8.498.2026.101"
    series_uid = "1.2.826.0.1.3680043.8.498.2026.101.1"
    frame_uid = "1.2.826.0.1.3680043.8.498.2026.101.0"
    sop_instance_uid = f"1.2.826.0.1.3680043.8.498.2026.101.1.{slice_idx + 1}"
    transfer_syntax_uid = "1.2.840.10008.1.2.1"  # Explicit VR Little Endian

    # Group 0002 File Meta Information
    meta_body = b"".join(
        [
            encode_element(0x0002, 0x0001, "OB", b"\x00\x01"),
            encode_str(0x0002, 0x0002, "UI", sop_class_uid),
            encode_str(0x0002, 0x0003, "UI", sop_instance_uid),
            encode_str(0x0002, 0x0010, "UI", transfer_syntax_uid),
            encode_str(0x0002, 0x0012, "UI", "1.2.826.0.1.3680043.8.498.1"),
            encode_str(0x0002, 0x0013, "SH", "RADAR_AI_1_0"),
        ]
    )
    meta_group = encode_ul(0x0002, 0x0000, len(meta_body)) + meta_body

    pixel_bytes = synthesize_axial_brain_slice(
        rows=rows,
        cols=cols,
        slice_idx=slice_idx,
        z_mm=z_mm,
        has_ich=has_ich,
        ich_scale=ich_scale,
    )

    # Dataset elements in strictly ascending (group, element) order
    dataset = b"".join(
        [
            # Group 0008: Identification
            encode_str(0x0008, 0x0008, "CS", "ORIGINAL\\PRIMARY\\AXIAL"),
            encode_str(0x0008, 0x0016, "UI", sop_class_uid),
            encode_str(0x0008, 0x0018, "UI", sop_instance_uid),
            encode_str(0x0008, 0x0020, "DA", "20261026"),
            encode_str(0x0008, 0x0030, "TM", "141200.000"),
            encode_str(0x0008, 0x0050, "SH", "RADAR-0101"),
            encode_str(0x0008, 0x0060, "CS", "CT"),
            encode_str(0x0008, 0x0070, "LO", "RADAR AI SYNTHETIC PHANTOM"),
            encode_str(0x0008, 0x1030, "LO", "Research Non-Contrast Cranial CT Fixture"),
            encode_str(0x0008, 0x103E, "LO", "Non-Contrast Axial Brain CT (5.0mm)"),
            # Group 0010: De-identified Patient
            encode_str(0x0010, 0x0010, "PN", "ANONYMIZED^BRAIN^CT"),
            encode_str(0x0010, 0x0020, "LO", "RADAR-CT-2026-0101"),
            encode_str(0x0010, 0x0030, "DA", ""),
            encode_str(0x0010, 0x0040, "CS", "O"),
            # Group 0012: Clinical Trial / De-identification
            encode_str(0x0012, 0x0062, "CS", "YES"),
            encode_str(
                0x0012,
                0x0063,
                "LO",
                "SYNTHETIC_MATHEMATICAL_PHANTOM_NO_PATIENT_DATA",
            ),
            # Group 0018: Acquisition
            encode_str(0x0018, 0x0050, "DS", "5.0"),
            encode_str(0x0018, 0x0060, "DS", "120"),
            # Group 0020: Relationship & Geometry
            encode_str(0x0020, 0x000D, "UI", study_uid),
            encode_str(0x0020, 0x000E, "UI", series_uid),
            encode_str(0x0020, 0x0010, "SH", "CT-2026-0101"),
            encode_str(0x0020, 0x0011, "IS", "1"),
            encode_str(0x0020, 0x0013, "IS", str(slice_idx + 1)),
            encode_str(0x0020, 0x0032, "DS", f"-120.0\\-120.0\\{z_mm:.1f}"),
            encode_str(0x0020, 0x0037, "DS", "1.0\\0.0\\0.0\\0.0\\1.0\\0.0"),
            encode_str(0x0020, 0x0052, "UI", frame_uid),
            encode_str(0x0020, 0x1041, "DS", f"{z_mm:.1f}"),
            encode_str(
                0x0020,
                0x4000,
                "LT",
                f"NOT FOR CLINICAL USE. Slice {slice_id} Asset {image_asset_id}",
            ),
            # Group 0028: Image Presentation & Pixel Lookup
            encode_us(0x0028, 0x0002, 1),  # SamplesPerPixel
            encode_str(0x0028, 0x0004, "CS", "MONOCHROME2"),
            encode_us(0x0028, 0x0010, rows),  # Rows
            encode_us(0x0028, 0x0011, cols),  # Columns
            encode_str(0x0028, 0x0030, "DS", "0.9375\\0.9375"),  # PixelSpacing
            encode_us(0x0028, 0x0100, 16),  # BitsAllocated
            encode_us(0x0028, 0x0101, 16),  # BitsStored
            encode_us(0x0028, 0x0102, 15),  # HighBit
            encode_us(0x0028, 0x0103, 0),  # PixelRepresentation (0 = unsigned)
            encode_str(0x0028, 0x1050, "DS", "40"),  # WindowCenter
            encode_str(0x0028, 0x1051, "DS", "80"),  # WindowWidth
            encode_str(0x0028, 0x1052, "DS", "-1024"),  # RescaleIntercept
            encode_str(0x0028, 0x1053, "DS", "1"),  # RescaleSlope
            encode_str(0x0028, 0x1054, "LO", "HU"),  # RescaleType
            # Group 7FE0: Pixel Data
            encode_element(0x7FE0, 0x0010, "OW", pixel_bytes),
        ]
    )

    preamble = b"\x00" * 128 + b"DICM"
    return preamble + meta_group + dataset


SLICES_SPEC = [
    {
        "index": 0,
        "z_mm": -15.0,
        "slice_id": "00000000-0000-4000-8000-000000000101",
        "image_asset_id": "00000000-0000-4000-8000-000000000201",
        "has_ich": False,
        "ich_scale": 0.0,
    },
    {
        "index": 1,
        "z_mm": -10.0,
        "slice_id": "00000000-0000-4000-8000-000000000102",
        "image_asset_id": "00000000-0000-4000-8000-000000000202",
        "has_ich": False,
        "ich_scale": 0.0,
    },
    {
        "index": 2,
        "z_mm": 1.5,
        "slice_id": "00000000-0000-4000-8000-000000000002",
        "image_asset_id": "00000000-0000-4000-8000-000000000003",
        "has_ich": True,
        "ich_scale": 1.0,
    },
    {
        "index": 3,
        "z_mm": 6.5,
        "slice_id": "00000000-0000-4000-8000-000000000104",
        "image_asset_id": "00000000-0000-4000-8000-000000000204",
        "has_ich": True,
        "ich_scale": 0.78,
    },
    {
        "index": 4,
        "z_mm": 11.5,
        "slice_id": "00000000-0000-4000-8000-000000000105",
        "image_asset_id": "00000000-0000-4000-8000-000000000205",
        "has_ich": False,
        "ich_scale": 0.0,
    },
]


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / "apps" / "web" / "public" / "fixtures" / "dicom" / "brain-ct"
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec in SLICES_SPEC:
        dcm_bytes = build_dicom_part10(
            slice_idx=spec["index"],
            z_mm=spec["z_mm"],
            slice_id=spec["slice_id"],
            image_asset_id=spec["image_asset_id"],
            has_ich=spec["has_ich"],
            ich_scale=spec["ich_scale"],
        )
        file_path = out_dir / f"slice-{spec['index']}.dcm"
        file_path.write_bytes(dcm_bytes)
        print(
            f"[OK] Generated {file_path.relative_to(repo_root)} "
            f"({len(dcm_bytes):,} bytes, Z={spec['z_mm']}mm, ICH={spec['has_ich']})"
        )


if __name__ == "__main__":
    main()
