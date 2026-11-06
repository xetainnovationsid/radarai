# Organize a flat DICOM CT dataset

`organize_dicom_series.py` groups DICOM files by their matching Study and Series
identifiers and sorts each series by physical slice position. It recognizes the
source dataset's opaque `ID_<hex>` identifiers and reads the CT storage class
from DICOM file-meta when the dataset tag is absent. The original DICOM files
are never changed. The output folders contain hard links by default, so they do
not duplicate the image data when input and output are on the same drive.

From PowerShell, run:

```powershell
cd "C:\Users\Iqbal Dovandra\Project Code\Kompe\RADAR AI\apps\api"
.\.venv\Scripts\python.exe .\scripts\organize_dicom_series.py `
  --input "C:\Users\Iqbal Dovandra\Downloads\radar-private\Brain_CT_data" `
  --output "C:\Users\Iqbal Dovandra\Downloads\radar-private\Brain_CT_data_sorted"
```

The output preserves `train` and `test` as separate top-level folders, then
creates a numbered study and series folder. Slice filenames are numbered in
physical position order. Images at the same physical position are kept and
ordered deterministically by their anonymized SOP identifier; no slice is
discarded. `manifest.csv` maps each output slice to its source path and Z
coordinate. Folder numbers and the manifest contain no Study/Series identifiers.

To check all files without creating an output folder, add `--dry-run` to the
command. It reports whether every series can be grouped and ordered.

Use `--mode copy` if hard links are unavailable. This duplicates the DICOM data
and requires enough free disk space. The program stops without producing output
when it finds malformed files, mixed or inconsistent series geometry, duplicate
positions, or an unorderable multi-slice series.

The upload API also checks that the Part 10 File Meta SOP identifiers match the
identifiers in each DICOM dataset. To make a separate copy that repairs only
those two File Meta identifiers when they are missing or inconsistent, run:

```powershell
.\.venv\Scripts\python.exe .\scripts\organize_dicom_series.py `
  --input "C:\Users\Iqbal Dovandra\Downloads\radar-private\Brain_CT_data" `
  --output "C:\Users\Iqbal Dovandra\Downloads\radar-private\Brain_CT_data_sorted_repaired" `
  --mode copy --repair-file-meta
```

This option requires copy mode. It leaves the source untouched and does not
change pixel data or patient metadata. It does not guess a missing or invalid
Transfer Syntax UID; those files are reported and need to be re-exported or
repaired with a DICOM-aware tool. Always inspect the dry-run summary before
creating the output.

This utility organizes files only. It does not train a model, upload images, or
make clinical predictions.
