# SoM-Bench: Evaluating Visual Grounding with Visual Prompting

We build a new benchmark called SoM-Bench to evaluate the visual grounding capability of LLMs with visual prompting.

## Dataset

| Vision Taks |  Source |  #Images | #Instances | Marks | Metric | Data
| -------- | -------- | -------- | -------- | -------- | -------- | -------- |
| Open-Vocab Segmentation | [COCO](https://cocodataset.org/#home) | 100 | 567 | Numeric IDs and Masks | Precision | [Download](https://github.com/microsoft/SoM/releases/download/v1.0/coco_ovseg.zip)
| Open-Vocab Segmentation | [ADE20K](https://groups.csail.mit.edu/vision/datasets/ADE20K/) | 100 | 488 | Numeric IDs and Masks | Precision | [Download](https://github.com/microsoft/SoM/releases/download/v1.0/ade20k_ovseg.zip)
| Phrase Grounding | [Flickr30K](https://shannon.cs.illinois.edu/DenotationGraph/) | 100 | 274 | Numeric IDs and Masks and Boxes | Recall @ 1 | [Download](https://github.com/microsoft/SoM/releases/download/v1.0/flickr30k_grounding.zip)
| Referring Comprehension | [RefCOCO](https://github.com/lichengunc/refer) | 100 | 177 | Numeric IDs and Masks | ACC @ 0.5 | [Download](https://github.com/microsoft/SoM/releases/download/v1.0/refcocog_refseg.zip)
| Referring Segmentation | [RefCOCO](https://github.com/lichengunc/refer) | 100 | 177 | Numeric IDs and Masks | mIoU | [Download](https://github.com/microsoft/SoM/releases/download/v1.0/refcocog_refseg.zip)

## Dataset Structure

### Open-Vocab Segmentation on COCO

We provide COCO in the following structure:

```
coco_ovseg
├── som_images
    ├── 000000000285_0.jpg
    ├── 000000000872_0.jpg
    |── 000000000872_5.jpg
    ├── ...
    ├── 000000002153_5.jpg
    └── 000000002261_0.jpg
```

For some of the samples, the regions are very dense, so we split the regions into multiple groups of size 5,. For example, `000000000872_0.jpg` has 5 regions, and `000000000872_5.jpg` has the other 5 regions. Note that you can use the image_id to track the original image.

We used the following language prompt for the task:
```
I have labeled a bright numeric ID at the center for each visual object in the image. Please enumerate their names. You must answer by selecting from the following names: [COCO Vocabulary]
```

### Open-Vocab Segmentation on ADE20K

```
ade20k_ovseg
├── som_images
    ├── ADE_val_00000001_0.jpg
    ├── ADE_val_00000001_5.jpg
    |── ADE_val_00000011_5.jpg
    ├── ...
    ├── ADE_val_00000039_5.jpg
    └── ADE_val_00000040_0.jpg
```
Similar to COCO, the regions in ADE20K are also very dense, so we split the regions into multiple groups of size 5,. For example, `ADE_val_00000001_0.jpg` has 5 regions, and `ADE_val_00000001_5.jpg` has the other 5 regions. Note that you can use the image_id to track the original image.

We used the following language prompt for the task:
```
I have labeled a bright numeric ID at the center for each visual object in the image. Please enumerate their names. You must answer by selecting from the following names: [ADE20K Vocabulary]
```

### Phrase Grounding on Flickr30K

```
flickr30k_grounding
├── som_images
    ├── 14868339.jpg
    ├── 14868339_wbox.jpg
    |── 14868339.json
    ├── ...
    ├── 302740416.jpg
    |── 319185571_wbox.jpg
    └── 302740416.json
```

For Flickr30K, we provide the image with numeric IDs and masks, and also the image with additional bounding boxes. The json file containing the ground truth bounding boxes and the corresponding phrases. Note that the bounding boxes are in the format of [x1, y1, x2, y2].

We used the following language prompt for the task:
```
I have labeled a bright numeric ID at the center for each visual object in the image. Given the image showing a man in glasses holding a piece of paper, find the corresponding regions for a man in glasses, a piece of paper.
```

### Referring Expression Comprehension and Segmentation on RefCOCOg

```
refcocog_refseg
├── som_images
    ├── 000000000795.jpg
    |── 000000000795.json
    ├── ...
    |── 000000007852.jpg
    └── 000000007852.json
```

For RefCOCOg, we provide the image with numeric IDs and masks, and also the json file containing the referring expressions and the corresponding referring ids. 

We used the following language prompt for the task:
```
I have labeled a bright numeric ID at the center for each visual object in the image. Please tell me the IDs for: The laptop behind the beer bottle; Laptop turned on.
```
