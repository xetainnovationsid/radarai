import numpy as np
import torch
from hausdorff import hausdorff_distance

def dice_coefficient(pred, gt, smooth=1e-5, both_empty_score=1.0):
    # to numpy & copy，避免原地改污染调用方
    pred = np.asarray(pred).copy()
    gt   = np.asarray(gt).copy()

    # 1) 清理 NaN/Inf
    pred = np.nan_to_num(pred, nan=0.0, posinf=0.0, neginf=0.0)
    gt   = np.nan_to_num(gt,   nan=0.0, posinf=0.0, neginf=0.0)

    # 2) 统一到 {0,1}
    pred = (pred >= 1).astype(np.float32)
    gt   = (gt   >= 1).astype(np.float32)

    N = int(gt.shape[0])
    if N == 0:
        return 0.0  # 或者 raise，按你需要

    pred_flat = pred.reshape(N, -1)
    gt_flat   = gt.reshape(N, -1)

    inter = (pred_flat * gt_flat).sum(1)
    card  = pred_flat.sum(1) + gt_flat.sum(1)

    # 3) both-empty 的定义（否则即便有 smooth，也可能想要自定义为 1.0）
    dice = (2.0 * inter + smooth) / (card + smooth)
    both_empty = (card == 0)
    if both_empty.any():
        dice = np.where(both_empty, both_empty_score, dice)

    # 4) 兜底（极端情况下仍有 NaN 就归零）
    dice = np.nan_to_num(dice, nan=both_empty_score)

    return float(dice.mean())

def sespiou_coefficient(pred, gt, smooth=1e-5):
    """ computational formula:
        sensitivity = TP/(TP+FN)
        specificity = TN/(FP+TN)
        iou = TP/(FP+TP+FN)
    """
    N = gt.shape[0]
    pred[pred >= 1] = 1
    gt[gt >= 1] = 1
    pred_flat = pred.reshape(N, -1)
    gt_flat = gt.reshape(N, -1)
    #pred_flat = pred.view(N, -1)
    #gt_flat = gt.view(N, -1)
    TP = (pred_flat * gt_flat).sum(1)
    FN = gt_flat.sum(1) - TP
    pred_flat_no = (pred_flat + 1) % 2
    gt_flat_no = (gt_flat + 1) % 2
    TN = (pred_flat_no * gt_flat_no).sum(1)
    FP = pred_flat.sum(1) - TP
    SE = (TP + smooth) / (TP + FN + smooth)
    SP = (TN + smooth) / (FP + TN + smooth)
    IOU = (TP + smooth) / (FP + TP + FN + smooth)
    return SE.sum() / N, SP.sum() / N, IOU.sum() / N

def sespiou_coefficient2(pred, gt, all=False, smooth=1e-5):
    """ computational formula:
        sensitivity = TP/(TP+FN)
        specificity = TN/(FP+TN)
        iou = TP/(FP+TP+FN)
    """
    N = gt.shape[0]
    pred[pred >= 1] = 1
    gt[gt >= 1] = 1
    pred_flat = pred.reshape(N, -1)
    gt_flat = gt.reshape(N, -1)
    #pred_flat = pred.view(N, -1)
    #gt_flat = gt.view(N, -1)
    TP = (pred_flat * gt_flat).sum(1)
    FN = gt_flat.sum(1) - TP
    pred_flat_no = (pred_flat + 1) % 2
    gt_flat_no = (gt_flat + 1) % 2
    TN = (pred_flat_no * gt_flat_no).sum(1)
    FP = pred_flat.sum(1) - TP
    SE = (TP + smooth) / (TP + FN + smooth)
    SP = (TN + smooth) / (FP + TN + smooth)
    IOU = (TP + smooth) / (FP + TP + FN + smooth)
    Acc = (TP + TN + smooth)/(TP + FP + FN + TN + smooth)
    Precision = (TP + smooth) / (TP + FP + smooth)
    Recall = (TP + smooth) / (TP + FN + smooth)
    F1 = 2*Precision*Recall/(Recall + Precision +smooth)
    if all:
        return SE.sum() / N, SP.sum() / N, IOU.sum() / N, Acc.sum()/N, F1.sum()/N, Precision.sum()/N, Recall.sum()/N
    else:
        return IOU.sum() / N, Acc.sum()/N, SE.sum() / N, SP.sum() / N

def get_matrix(pred, gt, smooth=1e-5):
    """ computational formula:
        sensitivity = TP/(TP+FN)
        specificity = TN/(FP+TN)
        iou = TP/(FP+TP+FN)
    """
    N = gt.shape[0]
    pred[pred >= 1] = 1
    gt[gt >= 1] = 1
    pred_flat = pred.reshape(N, -1)
    gt_flat = gt.reshape(N, -1)
    TP = (pred_flat * gt_flat).sum(1)
    FN = gt_flat.sum(1) - TP
    pred_flat_no = (pred_flat + 1) % 2
    gt_flat_no = (gt_flat + 1) % 2
    TN = (pred_flat_no * gt_flat_no).sum(1)
    FP = pred_flat.sum(1) - TP
    return TP, FP, TN, FN