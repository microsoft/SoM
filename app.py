# segmentation_cli.py

import torch
import numpy as np
from scipy.ndimage import label
import fire
from PIL import Image

# seem
from seem.modeling.BaseModel import BaseModel as BaseModel_Seem
from seem.utils.distributed import init_distributed as init_distributed_seem
from seem.modeling import build_model as build_model_seem
from task_adapter.seem.tasks import inference_seem_pano, inference_seem_interactive

# semantic sam
from semantic_sam.BaseModel import BaseModel
from semantic_sam import build_model
from semantic_sam.utils.dist import init_distributed_mode
from semantic_sam.utils.arguments import load_opt_from_config_file
from semantic_sam.utils.constants import COCO_PANOPTIC_CLASSES
from task_adapter.semantic_sam.tasks import inference_semsam_m2m_auto

# sam
from segment_anything import sam_model_registry
from task_adapter.sam.tasks.inference_sam_m2m_auto import inference_sam_m2m_auto
from task_adapter.sam.tasks.inference_sam_m2m_interactive import inference_sam_m2m_interactive

# Load configurations
semsam_cfg = "configs/semantic_sam_only_sa-1b_swinL.yaml"
seem_cfg = "configs/seem_focall_unicl_lang_v1.yaml"

semsam_ckpt = "./swinl_only_sam_many2many.pth"
sam_ckpt = "./sam_vit_h_4b8939.pth"
seem_ckpt = "./seem_focall_v1.pt"

opt_semsam = load_opt_from_config_file(semsam_cfg)
opt_seem = load_opt_from_config_file(seem_cfg)
opt_seem = init_distributed_seem(opt_seem)

# Build models
model_semsam = BaseModel(opt_semsam, build_model(opt_semsam)).from_pretrained(semsam_ckpt).eval().cuda()
model_sam = sam_model_registry["vit_h"](checkpoint=sam_ckpt).eval().cuda()
model_seem = BaseModel_Seem(opt_seem, build_model_seem(opt_seem)).from_pretrained(seem_ckpt).eval().cuda()

with torch.no_grad():
    with torch.autocast(device_type='cuda', dtype=torch.float16):
        model_seem.model.sem_seg_head.predictor.lang_encoder.get_text_embeddings(COCO_PANOPTIC_CLASSES + ["background"], is_eval=True)

@torch.no_grad()
def inference(image_path, slider=2, mode='Automatic', alpha=0.1, label_mode='Number', anno_mode=['Mask', 'Mark']):
    image = Image.open(image_path).convert('RGB')
    _mask = None  # Assuming no mask provided in CLI version

    if slider < 1.5:
        model_name = 'seem'
    elif slider > 2.5:
        model_name = 'sam'
    else:
        if mode == 'Automatic':
            model_name = 'semantic-sam'
            if slider < 1.5 + 0.14:
                level = [1]
            elif slider < 1.5 + 0.28:
                level = [2]
            elif slider < 1.5 + 0.42:
                level = [3]
            elif slider < 1.5 + 0.56:
                level = [4]
            elif slider < 1.5 + 0.70:
                level = [5]
            elif slider < 1.5 + 0.84:
                level = [6]
            else:
                level = [6, 1, 2, 3, 4, 5]
        else:
            model_name = 'sam'

    if label_mode == 'Alphabet':
        label_mode = 'a'
    else:
        label_mode = '1'

    text_size, hole_scale, island_scale = 640, 100, 100
    text, text_part, text_thresh = '', '', '0.0'

    with torch.autocast(device_type='cuda', dtype=torch.float16):
        semantic = False

        if mode == "Interactive" and _mask is not None:
            labeled_array, num_features = label(np.asarray(_mask))
            spatial_masks = torch.stack([torch.from_numpy(labeled_array == i+1) for i in range(num_features)])

        if model_name == 'semantic-sam':
            model = model_semsam
            output, mask = inference_semsam_m2m_auto(model, image, level, text, text_part, text_thresh, text_size, hole_scale, island_scale, semantic, label_mode=label_mode, alpha=alpha, anno_mode=anno_mode)

        elif model_name == 'sam':
            model = model_sam
            if mode == "Automatic":
                output, mask = inference_sam_m2m_auto(model, image, text_size, label_mode, alpha, anno_mode)
            elif mode == "Interactive" and _mask is not None:
                output, mask = inference_sam_m2m_interactive(model, image, spatial_masks, text_size, label_mode, alpha, anno_mode)

        elif model_name == 'seem':
            model = model_seem
            if mode == "Automatic":
                output, mask = inference_seem_pano(model, image, text_size, label_mode, alpha, anno_mode)
            elif mode == "Interactive" and _mask is not None:
                output, mask = inference_seem_interactive(model, image, spatial_masks, text_size, label_mode, alpha, anno_mode)

        return output


import os

output_dir = os.getenv('OUTPUT_DIR', './output')
os.makedirs(output_dir, exist_ok=True)

def main(image_path="./examples/ironing_man.jpg", slider=2, mode='Automatic', alpha=0.1, label_mode='Number', anno_mode=['Mask', 'Mark']):
    if os.path.isdir(image_path):
        print(f"{image_path} is a directory")
        for file in os.listdir(image_path):
            fp = os.path.join(image_path, file)
            print("found {fp}")
            main(fp)
        return
    
    
    imageName= os.path.basename(image_path)
    output = inference(image_path, slider, mode, alpha, label_mode, anno_mode)
    
    output_image:Image
    
    if isinstance(output, np.ndarray):
        output_image = Image.fromarray(output)
    else:
        output_image = output

    saveImageLoc = os.path.join(output_dir, f"seg-{imageName}")
    output_image.save(saveImageLoc)
    print(f"save image in {saveImageLoc}")

if __name__ == '__main__':
    fire.Fire(main)

# doc: --image_path path/to/your/image.jpg --slider 2 --mode Automatic --alpha 0.1 --label_mode Number --anno_mode Mask Mark