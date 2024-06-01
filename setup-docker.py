
print("setup docker started")

import fire

from seem.modeling import build_model as build_model_seem
# seem
from seem.modeling.BaseModel import BaseModel as BaseModel_Seem
from seem.utils.distributed import init_distributed as init_distributed_seem
# sam
from segment_anything import sam_model_registry
from semantic_sam import build_model
# semantic sam
from semantic_sam.BaseModel import BaseModel
from semantic_sam.utils.arguments import load_opt_from_config_file


semsam_cfg = "configs/semantic_sam_only_sa-1b_swinL.yaml"
seem_cfg = "configs/seem_focall_unicl_lang_v1.yaml"

semsam_ckpt = "./swinl_only_sam_many2many.pth"
sam_ckpt = "./sam_vit_h_4b8939.pth"
seem_ckpt = "./seem_focall_v1.pt"

opt_semsam = load_opt_from_config_file(semsam_cfg)
opt_seem = load_opt_from_config_file(seem_cfg)
opt_seem = init_distributed_seem(opt_seem)

# Build models

try:
    model_semsam = BaseModel(opt_semsam, build_model(opt_semsam)).from_pretrained(semsam_ckpt).eval()
except Exception as e:
    print(f"An error occurred while initializing model_semsam: {e}")

try:
    model_sam = sam_model_registry["vit_h"](checkpoint=sam_ckpt).eval()
except Exception as e:
    print(f"An error occurred while initializing model_sam: {e}")

try:
    model_seem = BaseModel_Seem(opt_seem, build_model_seem(opt_seem)).from_pretrained(seem_ckpt).eval()
except Exception as e:
    print(f"An error occurred while initializing model_seem: {e}")

print("setup docker completed")