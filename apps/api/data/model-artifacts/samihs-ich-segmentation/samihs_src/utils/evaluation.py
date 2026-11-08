# -*- coding: utf-8 -*-
# this file is utilized to evaluate the models from mode: 2D-slice level
from torch.autograd import Variable
from torch.utils.data import DataLoader
import os
import numpy as np
import torch
import torch.nn.functional as F
import utils.metrics as metrics
from hausdorff import hausdorff_distance
from utils.generate_prompts import get_click_prompt, get_click_prompt_eval
import time
import pandas as pd
from torchvision.transforms import InterpolationMode
from torchvision.transforms import functional as Func
from tqdm import tqdm
import cv2
import nibabel as nib                       # ★ 新

# ------------------------------- 可视化辅助函数 ------------------------------- #
def _overlay(gray, pred_mask, gt_mask=None, alpha=0.4):
    gray_uint8 = (gray * 255).astype(np.uint8)
    gray3      = cv2.cvtColor(gray_uint8, cv2.COLOR_GRAY2BGR)

    over = gray3.copy()
    if gt_mask is not None:                       # 绿色通道
        over[gt_mask > 0, 1] = 255
    if pred_mask is not None:                     # 红色通道
        over[pred_mask > 0, 2] = 255

    return cv2.addWeighted(gray3, 1 - alpha, over, alpha, 0)

def _color_overlay(gray, mask, color, alpha=0.8):
    g3 = cv2.cvtColor((gray * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    color_layer = np.zeros_like(g3)
    color_layer[mask > 0] = color
    return cv2.addWeighted(color_layer, alpha, g3, 1 - alpha, 0)

def _two_panel(img_left, img_right):
    return cv2.hconcat([img_left, img_right])

def _hstack_many(panels):
    """横向拼接多张同尺寸 BGR 图"""
    assert len(panels) >= 2
    h, w = panels[0].shape[:2]
    for p in panels:
        assert p.shape[:2] == (h, w), f"shape mismatch: {p.shape} vs {(h,w)}"
    return cv2.hconcat(panels)
# ----------------------------------------------------------------------------- #

def eval_mask_slice2(valloader, model, criterion, opt, args):
    if getattr(args, 'vis_dir', None):
        os.makedirs(args.vis_dir, exist_ok=True)

    model.eval()
    val_losses, mean_dice = 0, 0
    max_slice_number = opt.batch_size * (len(valloader) + 1)

    # 初始化指标容器
    fore_dice, hds_fore = [], []
    dices = np.zeros((max_slice_number, opt.classes))
    hds = np.zeros((max_slice_number, opt.classes))
    ious, accs, ses, sps = np.zeros_like(dices), np.zeros_like(dices), np.zeros_like(dices), np.zeros_like(dices)
    eval_number = 0
    sum_time = 0

    with tqdm(total=len(valloader), desc='Validation round', unit='batch', leave=False) as pbar:
        for batch_idx, datapack in enumerate(valloader):
            imgs = Variable(datapack['image'].to(dtype=torch.float32, device=opt.device))
            image_filename = datapack['image_name']

            pt = get_click_prompt_eval(datapack, opt)

            # ============== DEBUG: prompt / bbox 体检 =================
            if isinstance(pt, (tuple, list)):
                _coords, _labels = pt
                if not torch.isfinite(_coords).all():
                    print(f"[DEBUG][VAL] pt coords NaN/Inf at batch={batch_idx}")
                if not torch.isfinite(_labels.float()).all():
                    print(f"[DEBUG][VAL] pt labels NaN/Inf at batch={batch_idx}")
            else:
                print(f"[DEBUG][VAL] pt type unexpected: {type(pt)} at batch={batch_idx}")

            bbox = None  # 你的原逻辑保持不变；若你传 bbox，可在此做 clamp 并打印
            # =========================================================

            with torch.no_grad():
                start_time = time.time()
                pred = model(imgs, pt, bbox=None)
                print(f"pred mean = {pred['masks'].mean().item()}, std = {pred['masks'].std().item()}")
                sum_time += (time.time() - start_time)

            # ============== DEBUG: logits 体检 ========================
            if not isinstance(pred, dict) or 'masks' not in pred:
                print(f"[DEBUG][VAL] pred format unexpected at batch={batch_idx}: keys={list(pred.keys()) if isinstance(pred, dict) else type(pred)}")
            else:
                _logits = pred['masks']
                if not torch.isfinite(_logits).all():
                    print(f"[DEBUG][VAL] logits NaN/Inf at batch={batch_idx}",
                        " min/max:", float(_logits.min()), float(_logits.max()))
            # =========================================================

            predict = torch.sigmoid(pred['masks'])
            predict = Func.resize(predict, (512, 512), InterpolationMode.BILINEAR)
            predict = predict.detach().cpu().numpy()[:, 0, :, :] > 0.5

            b, h, w = predict.shape

            has_gt = 'low_mask' in datapack and 'label' in datapack
            if has_gt:
                masks = Variable(datapack['low_mask'].to(dtype=torch.float32, device=opt.device))
                label = Variable(datapack['label'].to(dtype=torch.float32, device=opt.device))

                # ============== DEBUG: GT 体检 & 空掩膜比例 =============
                dims = tuple(range(1, masks.ndim))
                per_sample_sum = masks.sum(dim=dims)
                empty_ratio = (per_sample_sum == 0).float().mean().item()
                if empty_ratio > 0:
                    # print(f"[DEBUG][VAL] empty GT ratio={empty_ratio:.3f} at batch={batch_idx}")
                    pass
                if not torch.isfinite(masks).all():
                    print(f"[DEBUG][VAL] masks NaN/Inf at batch={batch_idx}")
                # =======================================================

                gt = label.detach().cpu().numpy()[:, 0, :, :]
                val_loss = criterion(pred, masks)

                # ============== DEBUG: val loss 体检 ====================
                if not torch.isfinite(val_loss):
                    print(f"[DEBUG][VAL] loss NaN/Inf at batch={batch_idx} "
                        f"(loss={val_loss})")
                    # 打印更多上下文
                    print("  imgs finite:", torch.isfinite(imgs).all().item(),
                        " min/max:", float(imgs.min()), float(imgs.max()))
                    print("  logits finite:", torch.isfinite(pred['masks']).all().item(),
                        " min/max:", float(pred['masks'].min()), float(pred['masks'].max()))
                    print("  masks finite:", torch.isfinite(masks).all().item(),
                        " sum per-sample:", per_sample_sum.tolist())
                # =======================================================

                val_losses += val_loss.item()
                pbar.set_postfix(**{'loss (batch)': val_loss.item()})
            else:
                gt = [None] * b


            for j in range(b):
                pred_i = predict[j].astype(np.uint8)
                if gt[j] is not None:
                    gt_i = (gt[j] > 0).astype(np.uint8)

                    # ---- 先计算指标（不依赖是否可视化） ----
                    # both-empty 保护
                    if pred_i.sum() + gt_i.sum() == 0:
                        dice_i = 1.0
                        hd_i   = 0.0
                        iou, acc, se, sp = 1.0, 1.0, 1.0, 1.0
                    else:
                        dice_i = metrics.dice_coefficient(pred_i[None], gt_i[None])
                        iou, acc, se, sp = metrics.sespiou_coefficient2(pred_i[None], gt_i[None], all=False)
                        hd_i   = hausdorff_distance(pred_i, gt_i)

                    # 写入容器
                    dices[eval_number + j, 1] = dice_i
                    ious [eval_number + j, 1] = iou
                    accs [eval_number + j, 1] = acc
                    ses  [eval_number + j, 1] = se
                    sps  [eval_number + j, 1] = sp
                    hds  [eval_number + j, 1] = hd_i
                    if gt_i.sum() > 0:
                        fore_dice.append(dice_i)
                        hds_fore.append(hd_i)

                # ---- 只有这里保留可视化 ----
                if getattr(args, 'vis_dir', None):
                    base = os.path.splitext(image_filename[j])[0]
                    gray = imgs[j, 0].cpu().numpy()
                    gray = (gray - gray.min()) / (gray.ptp() + 1e-6)
                    if gray.shape != (h, w):
                        gray = cv2.resize(gray, (w, h), interpolation=cv2.INTER_LINEAR)

                    gray_bgr  = cv2.cvtColor((gray * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
                    panel_pred = _color_overlay(gray, pred_i, color=(0, 0, 255), alpha=0.8)

                    if gt[j] is not None:
                        panel_gt = _color_overlay(gray, (gt[j] > 0).astype(np.uint8), color=(0, 255, 0), alpha=0.8)
                        # 三联图：原图 | GT 叠加 | Pred 叠加
                        combined = _hstack_many([gray_bgr, panel_gt, panel_pred])
                    else:
                        # 无 GT 时仍旧两联图：原图 | Pred 叠加
                        combined = _two_panel(gray_bgr, panel_pred)

                    cv2.imwrite(os.path.join(args.vis_dir, f"{base}_compare.png"), combined[:, :, ::-1])

            eval_number += b
            pbar.update()

    if not has_gt:
        print("⚠️ Warning: No ground-truth masks detected. Only predictions are visualized.")
        return

    # 指标统计
    dices = dices[:eval_number, :]
    hds   = hds[:eval_number, :]
    ious, accs, ses, sps = (ious[:eval_number, :], accs[:eval_number, :],
                            ses[:eval_number, :],  sps[:eval_number, :])
    val_losses /= (batch_idx + 1)

    fore_dice_mean = np.mean(fore_dice)
    print("fore_dice_mean", fore_dice_mean)
    hds_fore_mean  = np.mean(hds_fore)
    dice_mean      = np.mean(dices, axis=0)
    print("dice_mean", dice_mean)
    dices_std      = np.std(dices,  axis=0)
    hd_mean        = np.mean(hds,   axis=0)
    hd_std         = np.std(hds,    axis=0)

    mean_dice  = np.mean(dice_mean[1:])
    mean_hdis  = np.mean(hd_mean[1:])
    print("test speed", eval_number / sum_time)

    if opt.mode == "train":
        return dices, fore_dice_mean, hds_fore_mean, val_losses
    else:
        iou_mean, iou_std = np.mean(ious, axis=0), np.std(ious, axis=0)
        acc_mean, acc_std = np.mean(accs, axis=0), np.std(accs, axis=0)
        se_mean, se_std   = np.mean(ses,  axis=0), np.std(ses,  axis=0)
        sp_mean, sp_std   = np.mean(sps,  axis=0), np.std(sps,  axis=0)

        return fore_dice_mean, hds_fore_mean, iou_mean, acc_mean, se_mean, sp_mean, dices_std[1],   hd_std[1],     iou_std,   acc_std,  se_std,  sp_std


# ------------------------------------------------------------ #
def get_eval(valloader, model, criterion, opt, args):
    if opt.eval_mode == "mask_slice":
        return eval_mask_slice2(valloader, model, criterion, opt, args)
    else:
        raise RuntimeError("Could not find the eval mode:", opt.eval_mode)
