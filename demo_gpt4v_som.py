# --------------------------------------------------------
# Set-of-Mark (SoM) Prompting for Visual Grounding in GPT-4V
# Copyright (c) 2023 Microsoft
# Licensed under The MIT License [see LICENSE for details]
# Written by:
#   Jianwei Yang (jianwyan@microsoft.com)
#   Xueyan Zou (xueyan@cs.wisc.edu)
#   Hao Zhang (hzhangcx@connect.ust.hk)
# --------------------------------------------------------
import io
import gradio as gr
import torch
import argparse
from PIL import Image
# seem
from seem.modeling.BaseModel import BaseModel as BaseModel_Seem
from seem.utils.distributed import init_distributed as init_distributed_seem
from seem.modeling import build_model as build_model_seem
from task_adapter.seem.tasks import interactive_seem_m2m_auto, inference_seem_pano, inference_seem_interactive

# semantic sam
from semantic_sam.BaseModel import BaseModel
from semantic_sam import build_model
from semantic_sam.utils.dist import init_distributed_mode
from semantic_sam.utils.arguments import load_opt_from_config_file
from semantic_sam.utils.constants import COCO_PANOPTIC_CLASSES
from task_adapter.semantic_sam.tasks import inference_semsam_m2m_auto, prompt_switch

# sam
from segment_anything import sam_model_registry
from task_adapter.sam.tasks.inference_sam_m2m_auto import inference_sam_m2m_auto
from task_adapter.sam.tasks.inference_sam_m2m_interactive import inference_sam_m2m_interactive


from task_adapter.utils.visualizer import Visualizer
from detectron2.data import MetadataCatalog
metadata = MetadataCatalog.get('coco_2017_train_panoptic')

from scipy.ndimage import label
import numpy as np

from gpt4v import request_gpt4v
from openai import OpenAI
from pydub import AudioSegment
from pydub.playback import play

import matplotlib.colors as mcolors
css4_colors = mcolors.CSS4_COLORS
color_proposals = [list(mcolors.hex2color(color)) for color in css4_colors.values()]

client = OpenAI()

'''
build args
'''
semsam_cfg = "configs/semantic_sam_only_sa-1b_swinL.yaml"
seem_cfg = "configs/seem_focall_unicl_lang_v1.yaml"

semsam_ckpt = "./swinl_only_sam_many2many.pth"
sam_ckpt = "./sam_vit_h_4b8939.pth"
seem_ckpt = "./seem_focall_v1.pt"

opt_semsam = load_opt_from_config_file(semsam_cfg)
opt_seem = load_opt_from_config_file(seem_cfg)
opt_seem = init_distributed_seem(opt_seem)


'''
build model
'''
model_semsam = BaseModel(opt_semsam, build_model(opt_semsam)).from_pretrained(semsam_ckpt).eval().cuda()
model_sam = sam_model_registry["vit_h"](checkpoint=sam_ckpt).eval().cuda()
model_seem = BaseModel_Seem(opt_seem, build_model_seem(opt_seem)).from_pretrained(seem_ckpt).eval().cuda()

with torch.no_grad():
    with torch.autocast(device_type='cuda', dtype=torch.float16):
        model_seem.model.sem_seg_head.predictor.lang_encoder.get_text_embeddings(COCO_PANOPTIC_CLASSES + ["background"], is_eval=True)

history_images = []
history_masks = []
history_texts = []
@torch.no_grad()
def inference(image, slider, mode, alpha, label_mode, anno_mode, *args, **kwargs):
    global history_images; history_images = []
    global history_masks; history_masks = []    

    _image = image['background'].convert('RGB')
    _mask = image['layers'][0].convert('L') if image['layers'] else None

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

    text_size, hole_scale, island_scale=640,100,100
    text, text_part, text_thresh = '','','0.0'
    with torch.autocast(device_type='cuda', dtype=torch.float16):
        semantic=False

        if mode == "Interactive":
            labeled_array, num_features = label(np.asarray(_mask))
            spatial_masks = torch.stack([torch.from_numpy(labeled_array == i+1) for i in range(num_features)])

        if model_name == 'semantic-sam':
            model = model_semsam
            output, mask = inference_semsam_m2m_auto(model, _image, level, text, text_part, text_thresh, text_size, hole_scale, island_scale, semantic, label_mode=label_mode, alpha=alpha, anno_mode=anno_mode, *args, **kwargs)

        elif model_name == 'sam':
            model = model_sam
            if mode == "Automatic":
                output, mask = inference_sam_m2m_auto(model, _image, text_size, label_mode, alpha, anno_mode)
            elif mode == "Interactive":
                output, mask = inference_sam_m2m_interactive(model, _image, spatial_masks, text_size, label_mode, alpha, anno_mode)

        elif model_name == 'seem':
            model = model_seem
            if mode == "Automatic":
                output, mask = inference_seem_pano(model, _image, text_size, label_mode, alpha, anno_mode)
            elif mode == "Interactive":
                output, mask = inference_seem_interactive(model, _image, spatial_masks, text_size, label_mode, alpha, anno_mode)

        # convert output to PIL image
        history_masks.append(mask)
        history_images.append(Image.fromarray(output))
        return (output, [])


def gpt4v_response(message, history):
    global history_images
    global history_texts; history_texts = []    
    try:
        res = request_gpt4v(message, history_images[0])
        history_texts.append(res)
        return res
    except Exception as e:
        return None

def highlight(mode, alpha, label_mode, anno_mode, *args, **kwargs):
    res = history_texts[0]
    # find the seperate numbers in sentence res
    res = res.split(' ')
    res = [r.replace('.','').replace(',','').replace(')','').replace('"','') for r in res]
    # find all numbers in '[]'
    res = [r for r in res if '[' in r]
    res = [r.split('[')[1] for r in res]
    res = [r.split(']')[0] for r in res]
    res = [r for r in res if r.isdigit()]
    res = list(set(res))
    sections = []
    for i, r in enumerate(res):
        mask_i = history_masks[0][int(r)-1]['segmentation']
        sections.append((mask_i, r))
    return (history_images[0], sections)

'''
launch app
'''

demo = gr.Blocks()
image = gr.ImageMask(label="Input", type="pil", sources=["upload"], interactive=True, brush=gr.Brush(colors=["#FFFFFF"]))
slider = gr.Slider(1, 3, value=1.8, label="Granularity") # info="Choose in [1, 1.5), [1.5, 2.5), [2.5, 3] for [seem, semantic-sam (multi-level), sam]"
mode = gr.Radio(['Automatic', 'Interactive', ], value='Automatic', label="Segmentation Mode")
anno_mode = gr.CheckboxGroup(choices=["Mark", "Mask", "Box"], value=['Mark'], label="Annotation Mode")
image_out = gr.AnnotatedImage(label="SoM Visual Prompt", height=512)
runBtn = gr.Button("Run")
highlightBtn = gr.Button("Highlight")
bot = gr.Chatbot(label="GPT-4V + SoM", height=256)
slider_alpha = gr.Slider(0, 1, value=0.05, label="Mask Alpha") #info="Choose in [0, 1]"
label_mode = gr.Radio(['Number', 'Alphabet'], value='Number', label="Mark Mode")

title = "Set-of-Mark (SoM) Visual Prompting for Extraordinary Visual Grounding in GPT-4V"
description = "This is a demo for SoM Prompting to unleash extraordinary visual grounding in GPT-4V. Please upload an image and them click the 'Run' button to get the image with marks. Then chat with GPT-4V below!"

with demo:
    gr.Markdown("<h1 style='text-align: center'><img src='https://som-gpt4v.github.io/website/img/som_logo.png' style='height:50px;display:inline-block'/>  Set-of-Mark (SoM) Prompting Unleashes Extraordinary Visual Grounding in GPT-4V</h1>")
    # gr.Markdown("<h2 style='text-align: center; margin-bottom: 1rem'>Project: <a href='https://som-gpt4v.github.io/'>link</a>     arXiv: <a href='https://arxiv.org/abs/2310.11441'>link</a>     Code: <a href='https://github.com/microsoft/SoM'>link</a></h2>")
    with gr.Row():
        with gr.Column():
            image.render()
            slider.render()
            with gr.Accordion("Detailed prompt settings (e.g., mark type)", open=False):
                with gr.Row():
                    mode.render()
                    anno_mode.render()
                with gr.Row():
                    slider_alpha.render()
                    label_mode.render()
        with gr.Column():
            image_out.render()
            runBtn.render()
            highlightBtn.render()
    with gr.Row():    
        gr.ChatInterface(chatbot=bot, fn=gpt4v_response)

    runBtn.click(inference, inputs=[image, slider, mode, slider_alpha, label_mode, anno_mode],
              outputs = image_out)
    highlightBtn.click(highlight, inputs=[image, mode, slider_alpha, label_mode, anno_mode],
              outputs = image_out)

demo.queue().launch(share=True,server_port=6092)

