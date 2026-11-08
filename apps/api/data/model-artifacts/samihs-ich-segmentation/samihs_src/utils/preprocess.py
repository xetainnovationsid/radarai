import SimpleITK as sitk
import numpy as np
import os
from tqdm import tqdm
import pandas as pd
import hashlib

# ---------- 路径 ----------
scans_path = '/data/wxh/Medical/tmz/metrics/brain_bleed/SAMIHS/BHSD/ct_scans_brain_window'
masks_path = '/data/wxh/Medical/tmz/metrics/brain_bleed/SAMIHS/BHSD/label_192/ground truths'

scans_path_2d = '/data/wxh/Medical/tmz/metrics/brain_bleed/SAMIHS/BHSD/ct_2d'
masks_path_2d = '/data/wxh/Medical/tmz/metrics/brain_bleed/SAMIHS/BHSD/mask_2d'
csv_out       = '/data/wxh/Medical/tmz/metrics/brain_bleed/SAMIHS/BHSD/bhsd_2d_index.csv'

os.makedirs(scans_path_2d, exist_ok=True)
os.makedirs(masks_path_2d, exist_ok=True)

# 允许的后缀
ALLOW_EXT = ('.nii', '.nii.gz')
TAG = 'BHSD'   # 文件名前缀，可改成 BCIHM 等

# 取病例 ID 列表（去扩展名）
ground_truth_ids = {os.path.splitext(f)[0].replace('.nii', '').replace('.gz', '')
                    for f in os.listdir(masks_path) if f.endswith(ALLOW_EXT)}

def removesuffix(name: str, suffix: str) -> str:
    return name[:-len(suffix)] if name.endswith(suffix) else name

def get_case_id_from_scan(fname: str) -> str:
    """从 ct_scans_brain_window 的文件名里抽出与 mask 同名的 case_id"""
    base = os.path.basename(fname)
    # 兼容 *_brain.nii / *_brain.nii.gz / *.nii / *.nii.gz
    for suf in ('_brain.nii.gz', '_brain.nii', '.nii.gz', '.nii'):
        if base.endswith(suf):
            return base[:-len(suf)]
    return os.path.splitext(base)[0]

def stable_fold(case_id: str, k: int = 5) -> int:
    """基于 case_id 的稳定哈希，避免同病例跨折泄露"""
    h = hashlib.md5(case_id.encode('utf-8')).hexdigest()
    return int(h, 16) % k

rows = []
row_id = 0

for pa in tqdm(os.listdir(scans_path)):
    if not pa.endswith(ALLOW_EXT):
        continue

    scan_fp = os.path.join(scans_path, pa)
    case_id = get_case_id_from_scan(pa)

    # 只处理有真值的病例
    if case_id not in ground_truth_ids:
        continue

    # 找对应 mask 文件（优先 .nii.gz，其次 .nii）
    mask_fp_gz  = os.path.join(masks_path, f"{case_id}.nii.gz")
    mask_fp_nii = os.path.join(masks_path, f"{case_id}.nii")
    mask_fp = mask_fp_gz if os.path.exists(mask_fp_gz) else mask_fp_nii
    if not os.path.exists(mask_fp):
        print(f"[WARN] mask not found for {case_id}, skip.")
        continue

    # 读影像 & 掩膜
    scan_img = sitk.ReadImage(scan_fp)
    mask_img = sitk.ReadImage(mask_fp)
    scan_arr  = sitk.GetArrayFromImage(scan_img)    # (Z,Y,X)
    label_arr = sitk.GetArrayFromImage(mask_img)

    # 五值 -> 二值
    label_arr = (label_arr > 0).astype(np.uint8)

    # 为该病例确定 fold
    fold_id = stable_fold(case_id, k=5)

    # 逐切片保存 & 记录
    for i in range(scan_arr.shape[0]):
        img_name  = f"{TAG}_{case_id}_{i:03d}.npy"
        mask_name = f"{TAG}_{case_id}_{i:03d}_seg.npy"

        np.save(os.path.join(scans_path_2d, img_name),  scan_arr[i])
        np.save(os.path.join(masks_path_2d, mask_name), label_arr[i])

        # 相对路径写入 CSV
        img_rel  = f"ct_2d/{img_name}"
        mask_rel = f"mask_2d/{mask_name}"
        pos_pixels = float(label_arr[i].sum())

        rows.append({
            "id": row_id,
            "img": img_rel,
            "gt": mask_rel,
            "fold": fold_id,
            "label": pos_pixels
        })
        row_id += 1

    # 可选：简单日志
    # print(pa, np.sum(scan_arr))

# 保存 CSV
df = pd.DataFrame(rows, columns=["id", "img", "gt", "fold", "label"])
df.to_csv(csv_out, index=False)
print(f"Done. Wrote {len(df)} rows to {csv_out}")