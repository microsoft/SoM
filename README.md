# Set-of-Mark Prompting -- Let's use Visual Prompting for Vision!

:grapes: \[[Read our arXiv Paper](https://arxiv.org/pdf/2310.11441.pdf)\] &nbsp; :apple: \[[Project Page](https://som-gpt4v.github.io/)\] 

:fire: We present **S**et-**o**f-**M**ark (SoM) prompting, simply overlaying a number of spatial and speakable marks on the images, to unleash the visual grounding abilities of large multimodal models (LMMs), such as GPT-4V.

![teaser_github](https://github.com/microsoft/SoM/assets/11957155/e4720105-b4b2-40c0-9303-2d8f1cb27d91)

### 🔥 News

* [10/18] We are going to release the SoM toolbox very soon. Stay tunned!

### :point_right: Comparing standard GPT-4V and its combination with SoM Prompting

![method2_xyz](https://github.com/microsoft/SoM/assets/34880758/32a269c4-8465-4eaf-aa90-48e9534649d9)
### :round_pushpin: SoM Toolbox for image partition
![method3_xyz](https://github.com/microsoft/SoM/assets/34880758/2443572b-995a-4f29-95df-3e3fc0f510d6)
Users can select which granularity of masks to generate, and which mode to use between automatic (top) and interactive (bottom). A higher alpha blending value (0.4) is used for better visualization.
### :unicorn: Interleaved Prompt
SoM enables interleaved prompts which include textual and visual content. The visual content can be represented using the region indices.
<img width="975" alt="Screenshot 2023-10-18 at 10 06 18" src="https://github.com/microsoft/SoM/assets/34880758/859edfda-ab04-450c-bd28-93762460ac1d">

### :medal_military: Mark types used in SoM
![method4_xyz](https://github.com/microsoft/SoM/assets/34880758/a9cddc47-f975-4991-b35a-72c50813c092)
### :volcano: Evaluation tasks examples
<img width="946" alt="Screenshot 2023-10-18 at 10 12 18" src="https://github.com/microsoft/SoM/assets/34880758/f5e0c0b0-58de-4b60-bf01-4906dbcb229e">

## Use case
### :tulip: Grounded Reasoning and Cross-Image Reference

<img width="972" alt="Screenshot 2023-10-18 at 10 10 41" src="https://github.com/microsoft/SoM/assets/34880758/033cd16c-876c-4c03-961e-590a4189bc9e">

In comparison to GPT-4V without SoM, adding marks enables GPT-4V to ground the
reasoning on detailed contents of the image (Left). Clear object cross-image references are observed
on the right.
17
### :camping: Problem Solving
<img width="972" alt="Screenshot 2023-10-18 at 10 18 03" src="https://github.com/microsoft/SoM/assets/34880758/8b112126-d164-47d7-b18c-b4b51b903d57">

Case study on solving CAPTCHA. GPT-4V gives the wrong answer with a wrong number
of squares while finding the correct squares with corresponding marks after SoM prompting.
### :mountain_snow: Knowledge Sharing
<img width="733" alt="Screenshot 2023-10-18 at 10 18 44" src="https://github.com/microsoft/SoM/assets/34880758/dc753c3f-ada8-47a4-83f1-1576bcfb146a">

Case study on an image of dish for GPT-4V. GPT-4V does not produce a grounded answer
with the original image. Based on SoM prompting, GPT-4V not only speaks out the ingredients but
also corresponds them to the regions.
### :mosque: Personalized Suggestion
<img width="733" alt="Screenshot 2023-10-18 at 10 19 12" src="https://github.com/microsoft/SoM/assets/34880758/88188c90-84f2-49c6-812e-44770b0c2ca5">

SoM-pormpted GPT-4V gives very precise suggestions while the original one fails, even
with hallucinated foods, e.g., soft drinks
### :blossom: Tool Usage Instruction
<img width="734" alt="Screenshot 2023-10-18 at 10 19 39" src="https://github.com/microsoft/SoM/assets/34880758/9b35b143-96af-41bd-ad83-9c1f1e0f322f">
Likewise, GPT4-V with SoM can help to provide thorough tool usage instruction
, teaching
users the function of each button on a controller. Note that this image is not fully labeled, while
GPT-4V can also provide information about the non-labeled buttons.

### :sunflower: 2D Game Planning
<img width="730" alt="Screenshot 2023-10-18 at 10 20 03" src="https://github.com/microsoft/SoM/assets/34880758/0bc86109-5512-4dee-aac9-bab0ef96ed4c">

GPT-4V with SoM gives a reasonable suggestion on how to achieve a goal in a gaming
scenario.
### :mosque: Simulated Navigation
<img width="729" alt="Screenshot 2023-10-18 at 10 21 24" src="https://github.com/microsoft/SoM/assets/34880758/7f139250-5350-4790-a35c-444ec2ec883b">

### :deciduous_tree: Results
We conduct experiments on various vision tasks to verify the effectiveness of our SoM. Results show that GPT4V+SoM outperforms specialists on most vision tasks and is comparable to MaskDINO on COCO panoptic segmentation.
![main_results](https://github.com/microsoft/SoM/assets/34880758/722ac979-6c7f-4740-9625-cac38060e0ad)

## :hearts: Acknowledgement

Our model adopts the following models to propose masks:
- [Mask DINO](https://github.com/IDEA-Research/MaskDINO)
- [SEEM](https://github.com/IDEA-Research/OpenSeeD)
- [Semantic-SAM](https://github.com/UX-Decoder/Semantic-SAM)
- [Segment Anything](https://github.com/facebookresearch/segment-anything) for the SA-1B data.

We also thank GPT-4V for providing a strong foundational model!
## :black_nib: Citation

If you find our work helpful for your research, please consider citing the following BibTeX entry.   
```bibtex
@article{yang2023setofmark,
      title={Set-of-Mark Prompting Unleashes Extraordinary Visual Grounding in GPT-4V}, 
      author={Jianwei Yang and Hao Zhang and Feng Li and Xueyan Zou and Chunyuan Li and Jianfeng Gao},
      journal={arXiv preprint arXiv:2310.11441},
      year={2023},
}
