import pytest
import random
from PIL import Image
from collections import defaultdict
from typing import Dict, List, Tuple
from pathlib import Path

import torch
import numpy as np
import safetensors.torch
from skimage.metrics import structural_similarity
from diffusers import DiffusionPipeline
from onediff.infer_compiler import oneflow_compile

from onediffx.lora import load_and_fuse_lora, unfuse_lora

HEIGHT = 768
WIDTH = 512
NUM_STEPS = 30

MODEL_ID = "/share_nfs/hf_models/stable-diffusion-xl-base-1.0"
pipe = DiffusionPipeline.from_pretrained(
    MODEL_ID, variant="fp16", torch_dtype=torch.float16
).to("cuda")

loras = [
    "/share_nfs/onediff_ci/diffusers/loras/SDXL-Emoji-Lora-r4.safetensors",
    "/share_nfs/onediff_ci/diffusers/loras/sdxl_metal_lora.safetensors",
    "/share_nfs/onediff_ci/diffusers/loras/simple_drawing_xl_b1-000012.safetensors",
    "/share_nfs/onediff_ci/diffusers/loras/texta.safetensors",
    "/share_nfs/onediff_ci/diffusers/loras/watercolor_v1_sdxl_lora.safetensors",
]
loras = {x: safetensors.torch.load_file(x) for x in loras}
loras_to_load = loras.copy()
# metal and texta LoRA have low ssim
loras_to_load.pop("/share_nfs/onediff_ci/diffusers/loras/sdxl_metal_lora.safetensors")
loras_to_load.pop("/share_nfs/onediff_ci/diffusers/loras/texta.safetensors")

image_file_prefix = "/share_nfs/onediff_ci/diffusers/images"

# create target images if not exist
target_images_list = [
    f"{image_file_prefix}/test_sdxl_lora_{str(Path(name).stem)}.png" for name in loras
]
if not all(Path(x).exists() for x in target_images_list):
    print("Didn't find target images, try to generate...")
    for name, lora in loras.items():
        pipe.load_lora_weights(lora.copy())
        pipe.fuse_lora()
        image = pipe(
            "a cat",
            height=HEIGHT,
            width=WIDTH,
            num_inference_steps=NUM_STEPS,
            generator=torch.manual_seed(0),
        ).images[0]
        pipe.unfuse_lora()
        image.save(f"{image_file_prefix}/test_sdxl_lora_{str(Path(name).stem)}.png")
    torch.cuda.empty_cache()


weight_num = 20
weight_names = {
    "unet": [x for x, _ in pipe.unet.named_parameters()],
    "text_encoder": [x for x, _ in pipe.text_encoder.named_parameters()],
}
if hasattr(pipe, "text_encoder_2"):
    weight_names.update(
        {"text_encoder_2": [x for x, _ in pipe.text_encoder_2.named_parameters()]}
    )
random_weight_names = {
    k: random.choices(weight_names[k], k=weight_num) for k in weight_names
}
original_weights = defaultdict(list)
for part, names in random_weight_names.items():
    for name in names:
        original_weights[part].append([name, getattr(pipe, part).get_parameter(name)])

pipe.unet = oneflow_compile(pipe.unet)
pipe("a cat", height=HEIGHT, width=WIDTH, num_inference_steps=NUM_STEPS,).images[0]


def check_param(pipe, original_weights: Dict[str, List[Tuple[str, torch.Tensor]]]):
    for part, state_dict in original_weights.items():
        for name, weight in state_dict:
            current_weight = getattr(pipe, part).get_parameter(name)
            return torch.allclose(current_weight, weight)


@pytest.mark.parametrize("name, lora", loras_to_load.items())
def test_lora_loading(name, lora):
    generator = torch.manual_seed(0)
    load_and_fuse_lora(pipe, lora.copy())
    images_fusion = pipe(
        "a cat",
        generator=generator,
        height=HEIGHT,
        width=WIDTH,
        num_inference_steps=NUM_STEPS,
    ).images[0]
    image_name = name.split("/")[-1].split(".")[0]
    target_image = np.array(
        Image.open(f"{image_file_prefix}/test_sdxl_lora_{image_name}.png")
    )
    curr_image = np.array(images_fusion)
    ssim = structural_similarity(
        curr_image, target_image, channel_axis=-1, data_range=255
    )
    unfuse_lora(pipe)
    print(f"lora {name} ssim {ssim}")
    assert ssim > 0.9


@pytest.mark.parametrize("lora", loras.values())
def test_lora_switching(lora):
    device = random.choice(["cpu", "cuda"])
    weight = random.choice(["lora", "weight"])
    load_and_fuse_lora(
        pipe, lora.copy(), lora_scale=1.0, offload_device=device, offload_weight=weight,
    )
    unfuse_lora(pipe)
    assert check_param(pipe, original_weights)
