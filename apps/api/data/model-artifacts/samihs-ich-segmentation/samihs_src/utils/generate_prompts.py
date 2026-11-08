import torch
import random

def generate_click_prompt(img, msk, pt_label = 1):
    # return: img, prompt, prompt mask
    pt_list = []
    msk_list = []
    b, c, h, w, d = msk.size()
    msk = msk[:,0,:,:,:]
    for i in range(d):
        pt_list_s = []
        msk_list_s = []
        for j in range(b):
            msk_s = msk[j,:,:,i]
            indices = torch.nonzero(msk_s)
            if indices.size(0) == 0:
                # generate a random array between [0-h, 0-h]:
                random_index = torch.randint(0, h, (2,)).to(device = msk.device)
                new_s = msk_s
            else:
                random_index = random.choice(indices)
                label = msk_s[random_index[0], random_index[1]]
                new_s = torch.zeros_like(msk_s)
                # convert bool tensor to int
                new_s = (msk_s == label).to(dtype = torch.float)
                # new_s[msk_s == label] = 1
            pt_list_s.append(random_index)
            msk_list_s.append(new_s)
        pts = torch.stack(pt_list_s, dim=0) # b 2
        msks = torch.stack(msk_list_s, dim=0)
        pt_list.append(pts)  # c b 2
        msk_list.append(msks)
    pt = torch.stack(pt_list, dim=-1) # b 2 d
    msk = torch.stack(msk_list, dim=-1) # b h w d
    msk = msk.unsqueeze(1) # b c h w d
    return img, pt, msk #[b, 2, d], [b, c, h, w, d]

import torch

def get_click_prompt_eval(datapack, opt):
    """
    返回与 get_click_prompt 相同的结构：(coords_torch, labels_torch)
    - coords_torch: float32, [B,P,2]
    - labels_torch: torch.int, [B,P]
    """
    device = opt.device

    # 无 GT：给一个中心点 + 0 标签（B,1,2）/（B,1）
    if 'pt' not in datapack or 'p_label' not in datapack:
        b, _, h, w = datapack['image'].shape
        cx = (w - 1) / 2.0
        cy = (h - 1) / 2.0
        coords_torch = torch.tensor([[[cx, cy]]], dtype=torch.float32, device=device).repeat(b, 1, 1)
        labels_torch = torch.zeros((b, 1), dtype=torch.int, device=device)
        return (coords_torch, labels_torch)

    # 有 GT：规格化到同一 dtype / device / shape
    coords_torch = torch.as_tensor(datapack['pt'],      dtype=torch.float32, device=device)
    labels_torch = torch.as_tensor(datapack['p_label'], dtype=torch.int,     device=device)

    # 统一维度到 [B,P,2] / [B,P]
    if coords_torch.ndim == 2:  # 可能是 [P,2] 或 [B,2]
        if 'image' in datapack and datapack['image'].shape[0] == coords_torch.shape[0] == coords_torch.shape[-2]:
            # 这个分支仅当形状恰好 [B,2] 时成立 -> 转 [B,1,2]
            coords_torch = coords_torch.unsqueeze(1)
            if labels_torch.ndim == 1 and labels_torch.shape[0] == datapack['image'].shape[0]:
                labels_torch = labels_torch.unsqueeze(1)
        else:
            # 视为 [P,2] -> [1,P,2]；标签 [P] -> [1,P]
            coords_torch = coords_torch.unsqueeze(0)
            if labels_torch.ndim == 1:
                labels_torch = labels_torch.unsqueeze(0)

    elif coords_torch.ndim == 3:
        # 期望已经是 [B,P,2]，不处理
        pass
    else:
        raise ValueError(f"Unexpected pt shape: {coords_torch.shape}")

    # 标签维度对齐到 [B,P]
    if labels_torch.ndim == 1:
        labels_torch = labels_torch.unsqueeze(0)

    return (coords_torch, labels_torch)


def get_click_prompt(datapack, opt):
    if 'pt' not in datapack:
        imgs, pt, masks = generate_click_prompt(imgs, masks)
    else:
        pt = datapack['pt']
        point_labels = datapack['p_label']

    point_coords = pt
    coords_torch = torch.as_tensor(point_coords, dtype=torch.float32, device=opt.device)
    labels_torch = torch.as_tensor(point_labels, dtype=torch.int, device=opt.device)
    if len(pt.shape) == 2:
        coords_torch, labels_torch = coords_torch[None, :, :], labels_torch[None, :]
    pt = (coords_torch, labels_torch)
    return pt
