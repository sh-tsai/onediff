import oneflow as flow
from onediff.infer_compiler import oneflow_compile
from onediff.infer_compiler.transform import proxy_class, register
from sd_webui_onediff_utils import (
    CrossAttentionOflow,
    GroupNorm32Oflow,
    timestep_embedding,
)
from sgm.modules.attention import CrossAttention, SpatialTransformer
from sgm.modules.diffusionmodules.openaimodel import UNetModel, ResBlock
from sgm.modules.attention import BasicTransformerBlock
from sgm.modules.diffusionmodules.util import GroupNorm32

__all__ = ["compile_sgm_unet"]


# https://github.com/Stability-AI/generative-models/blob/059d8e9cd9c55aea1ef2ece39abf605efb8b7cc9/sgm/modules/diffusionmodules/openaimodel.py#L816
class UNetModelOflow(proxy_class(UNetModel)):
    def forward(self, x, timesteps=None, context=None, y=None, **kwargs):
        assert (y is not None) == (
            self.num_classes is not None
        ), "must specify y if and only if the model is class-conditional"
        hs = []
        t_emb = timestep_embedding(timesteps, self.model_channels).half()
        emb = self.time_embed(t_emb)
        x = x.half()
        context = context.half() if context is not None else context
        y = y.half() if y is not None else y
        if self.num_classes is not None:
            assert y.shape[0] == x.shape[0]
            emb = emb + self.label_emb(y)
        h = x
        for module in self.input_blocks:
            h = module(h, emb, context)
            hs.append(h)
        h = self.middle_block(h, emb, context)
        for module in self.output_blocks:
            h = flow.cat([h, hs.pop()], dim=1)
            h = module(h, emb, context)
        h = h.type(x.dtype)
        return self.out(h)


class SpatialTransformerOflow(proxy_class(SpatialTransformer)):
    # https://github.com/Stability-AI/generative-models/blob/059d8e9cd9c55aea1ef2ece39abf605efb8b7cc9/sgm/modules/attention.py#L702
    def forward(self, x, context=None):
        # note: if no context is given, cross-attention defaults to self-attention
        if not isinstance(context, list):
            context = [context]
        b, c, h, w = x.shape
        x_in = x
        x = self.norm(x)
        if not self.use_linear:
            x = self.proj_in(x)
        x = x.flatten(2, 3).permute(0, 2, 1)
        if self.use_linear:
            x = self.proj_in(x)
        for i, block in enumerate(self.transformer_blocks):
            if i > 0 and len(context) == 1:
                i = 0  # use same context for each block
            x = block(x, context=context[i])
        if self.use_linear:
            x = self.proj_out(x)
        x = x.permute(0, 2, 1).reshape_as(x_in)
        if not self.use_linear:
            x = self.proj_out(x)
        return x + x_in


torch2oflow_class_map = {
    CrossAttention: CrossAttentionOflow,
    GroupNorm32: GroupNorm32Oflow,
    SpatialTransformer: SpatialTransformerOflow,
    UNetModel: UNetModelOflow,
}
register(package_names=["sgm"], torch2oflow_class_map=torch2oflow_class_map)


def compile_sgm_unet(unet_model, *, options=None):
    if not isinstance(unet_model, UNetModel):
        return
    for module in unet_model.modules():
        if isinstance(module, BasicTransformerBlock):
            module.checkpoint = False
        if isinstance(module, ResBlock):
            module.use_checkpoint = False
    return oneflow_compile(unet_model, options=options)
